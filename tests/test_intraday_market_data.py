from datetime import datetime, timedelta, timezone
from decimal import Decimal
from zoneinfo import ZoneInfo

from intraday.domain import CompletedBar, Instrument, MarketTick
from intraday.market_data.bars import FiveMinuteBarBuilder
from intraday.market_data.instruments import reconcile_nse_cash_equities
from intraday.market_data.quality import assess_tick
from intraday.market_data.upstox_v3 import parse_upstox_v3_message
from intraday.scanner import IntradayScanner
from intraday.strategies import (
    opening_range_breakout_signal,
    vwap_momentum_signal,
)

IST = ZoneInfo("Asia/Kolkata")
UTC = timezone.utc


def make_tick(symbol="RELIANCE", key="NSE_EQ|INE002A01018", when=None, price=100, qty=10):
    when = when or datetime(2026, 11, 4, 9, 15, 10, tzinfo=IST)
    return MarketTick(
        symbol=symbol,
        instrument_key=key,
        price=price,
        exchange_time=when,
        received_at=when.astimezone(UTC),
        last_trade_quantity=qty,
    )


def make_instrument(symbol="RELIANCE", key="NSE_EQ|INE002A01018"):
    return Instrument(symbol, key, "Reliance Industries", Decimal("0.05"), 1)


def make_bars(count=22):
    start = datetime(2026, 11, 4, 9, 15, tzinfo=IST)
    bars = []
    for i in range(count):
        close = 100 + i * 0.1
        open_price = close - 0.05
        high = close + 0.1
        low = close - 0.1
        volume = 1000
        if i == count - 1:
            open_price = close - 0.5
            close = 103.2
            high = 103.3
            low = 101.5
            volume = 2000
        bar_start = start + timedelta(minutes=5 * i)
        bars.append(CompletedBar(
            symbol="RELIANCE",
            start_time=bar_start,
            end_time=bar_start + timedelta(minutes=5),
            open=open_price,
            high=high,
            low=low,
            close=close,
            volume=volume,
        ))
    return tuple(bars)


def test_instrument_reconciliation_accounts_for_every_bod_row():
    rows = [
        {
            "segment": "NSE_EQ", "exchange": "NSE", "instrument_type": "EQ",
            "instrument_key": "NSE_EQ|INE002A01018", "trading_symbol": "RELIANCE",
            "name": "Reliance Industries", "tick_size": "0.05", "lot_size": 1,
            "security_type": "NORMAL",
        },
        {
            "segment": "NSE_FO", "exchange": "NSE", "instrument_type": "CE",
            "instrument_key": "NSE_FO|1", "trading_symbol": "RELIANCE26CE",
            "tick_size": "0.05", "lot_size": 250, "security_type": "NORMAL",
        },
        {
            "segment": "NSE_EQ", "exchange": "NSE", "instrument_type": "EQ",
            "instrument_key": "NSE_EQ|INE999A01011", "trading_symbol": "SUSPENDED",
            "tick_size": "0.05", "lot_size": 1, "security_type": "NORMAL",
        },
        {
            "segment": "NSE_EQ", "exchange": "NSE", "instrument_type": "EQ",
            "instrument_key": "NSE_EQ|INE002A01018", "trading_symbol": "RELIANCE",
            "tick_size": "0.05", "lot_size": 1, "security_type": "NORMAL",
        },
    ]
    result = reconcile_nse_cash_equities(rows, suspended_keys={"NSE_EQ|INE999A01011"})
    assert len(result.eligible) == 1
    assert len(result.excluded) == 3
    assert result.accounted_rows == result.source_rows == 4
    assert {item["reason"] for item in result.excluded} == {
        "not_nse_equity_segment", "broker_suspended_instrument", "duplicate_instrument"
    }


def test_upstox_v3_message_uses_symbol_mapping_and_ist_exchange_time():
    exchange_time = datetime(2026, 11, 4, 9, 15, 10, tzinfo=IST)
    message = {
        "feeds": {
            "NSE_EQ|INE002A01018": {
                "ltpc": {
                    "ltp": 1450.25,
                    "ltt": str(int(exchange_time.timestamp() * 1000)),
                    "ltq": "12",
                    "cp": 1440.0,
                }
            }
        },
        "currentTs": str(int(exchange_time.timestamp() * 1000)),
    }
    received = datetime(2026, 11, 4, 3, 45, 11, tzinfo=UTC)
    ticks = parse_upstox_v3_message(
        message, received_at=received,
        symbol_by_key={"NSE_EQ|INE002A01018": "RELIANCE"},
    )
    assert len(ticks) == 1
    assert ticks[0].symbol == "RELIANCE"
    assert ticks[0].price == 1450.25
    assert ticks[0].exchange_time.hour == 9
    assert ticks[0].exchange_time.minute == 15
    assert ticks[0].exchange_time.utcoffset() == timedelta(hours=5, minutes=30)
    assert ticks[0].last_trade_quantity == 12


def test_upstox_message_without_feed_payload_returns_no_ticks():
    assert parse_upstox_v3_message({"type": "market_info"}) == ()


def test_tick_quality_rejects_stale_and_future_feed_messages():
    now = datetime(2026, 11, 4, 10, 0, tzinfo=IST)
    stale = make_tick(when=now - timedelta(seconds=60))
    future = make_tick(when=now + timedelta(seconds=10))
    assert assess_tick(stale, now=now).reason == "stale_exchange_tick"
    assert assess_tick(future, now=now).reason == "exchange_timestamp_in_future"


def test_five_minute_builder_deduplicates_and_vwap_uses_only_completed_bars():
    builder = FiveMinuteBarBuilder()
    first = make_tick(price=100, qty=10)
    second = make_tick(when=first.exchange_time + timedelta(minutes=1), price=102, qty=10)
    boundary = make_tick(when=first.exchange_time + timedelta(minutes=5), price=101, qty=5)

    assert builder.ingest(first) is None
    assert builder.ingest(first) is None  # repeated latest-trade snapshot
    assert builder.ingest(second) is None
    completed = builder.ingest(boundary)

    assert completed is not None
    assert completed.start_time.hour == 9 and completed.start_time.minute == 15
    assert completed.open == 100
    assert completed.high == 102
    assert completed.low == 100
    assert completed.close == 102
    assert completed.volume == 20
    # The 09:20 working bar is excluded until it completes; no lookahead.
    assert builder.session_vwap("RELIANCE") == 101


def test_vwap_momentum_signal_requires_completed_bars_and_volume_confirmation():
    instrument = make_instrument()
    bars = make_bars()
    signal = vwap_momentum_signal(instrument, bars, session_vwap=100.5)
    assert signal is not None
    assert signal.strategy_id == "vwap_momentum"
    assert signal.stop_price < signal.entry_reference < signal.target_price
    assert signal.volume_ratio >= 1.3


def test_vwap_momentum_signal_does_not_trigger_with_stale_or_missing_vwap():
    instrument = make_instrument()
    bars = make_bars()
    assert vwap_momentum_signal(instrument, bars[:20], 100.0) is None
    assert vwap_momentum_signal(instrument, bars, None) is None


def test_opening_range_breakout_requires_first_fifteen_minutes_and_confirmation():
    instrument = make_instrument()
    bars = list(make_bars())
    bars[0] = CompletedBar("RELIANCE", bars[0].start_time, bars[0].end_time, 100, 101, 99.9, 100.5, 1000)
    bars[1] = CompletedBar("RELIANCE", bars[1].start_time, bars[1].end_time, 100.5, 101.2, 100.2, 101.0, 1000)
    bars[2] = CompletedBar("RELIANCE", bars[2].start_time, bars[2].end_time, 101.0, 101.4, 100.8, 101.2, 1000)
    last = bars[-1]
    bars[-1] = CompletedBar("RELIANCE", last.start_time, last.end_time, 102.6, 103.5, 102.5, 103.4, 2500)
    signal = opening_range_breakout_signal(instrument, tuple(bars), session_vwap=101.5)
    assert signal is not None
    assert signal.strategy_id == "opening_range_breakout"


def test_scanner_requires_fresh_feed_and_rejects_unknown_or_mismatched_instruments():
    instrument = make_instrument()
    scanner = IntradayScanner((instrument,))
    now = datetime(2026, 11, 4, 9, 15, 11, tzinfo=IST)
    assert scanner.opportunities(now=now) == ()

    wrong = make_tick(symbol="OTHER")
    assert scanner.on_tick(wrong, now=now) is False
    assert scanner.rejected_ticks["instrument_symbol_mismatch"] == 1

    good = make_tick()
    assert scanner.on_tick(good, now=now) is True
    assert scanner.feed_is_fresh(now=now) is True
