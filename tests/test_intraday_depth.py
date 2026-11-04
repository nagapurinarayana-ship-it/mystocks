from datetime import datetime, timedelta, timezone
from decimal import Decimal
from zoneinfo import ZoneInfo

from intraday.domain import Instrument, MarketTick, TradeSignal
from intraday.scanner import IntradayScanner

IST = ZoneInfo("Asia/Kolkata")


def test_candidate_depth_requires_fresh_two_sided_liquidity_and_acceptable_spread():
    instrument = Instrument(
        "RELIANCE", "NSE_EQ|INE002A01018", "Reliance Industries",
        Decimal("0.05"), 1,
    )
    scanner = IntradayScanner((instrument,))
    generated = datetime(2026, 11, 4, 10, 0, tzinfo=IST)
    signal = TradeSignal(
        strategy_id="vwap_momentum", symbol="RELIANCE",
        generated_at=generated, entry_reference=100,
        stop_price=99, target_price=102, volume_ratio=1.5,
        score=70, explanation="candidate fixture",
    )
    scanner._candidate_signals[("RELIANCE", "vwap_momentum", generated)] = signal

    now = datetime(2026, 11, 4, 4, 30, 1, tzinfo=timezone.utc)
    tick_time = generated + timedelta(seconds=1)
    tick = MarketTick(
        symbol="RELIANCE", instrument_key=instrument.instrument_key,
        price=100, exchange_time=tick_time, received_at=now,
        last_trade_quantity=10, best_bid=99.95, best_ask=100.05,
        best_bid_quantity=120, best_ask_quantity=80,
    )
    assert scanner.on_tick(tick, now=now)
    assert scanner.validate_candidate_depth(signal, now=now) == (True, "depth_validated")


def test_candidate_depth_rejects_missing_depth_and_stale_quotes():
    instrument = Instrument(
        "RELIANCE", "NSE_EQ|INE002A01018", "Reliance Industries",
        Decimal("0.05"), 1,
    )
    scanner = IntradayScanner((instrument,))
    generated = datetime(2026, 11, 4, 10, 0, tzinfo=IST)
    signal = TradeSignal(
        "vwap_momentum", "RELIANCE", generated, 100, 99, 102, 1.5, 70, "test",
    )
    scanner._candidate_signals[("RELIANCE", "vwap_momentum", generated)] = signal
    now = datetime(2026, 11, 4, 4, 30, 1, tzinfo=timezone.utc)
    tick = MarketTick(
        symbol="RELIANCE", instrument_key=instrument.instrument_key, price=100,
        exchange_time=generated + timedelta(seconds=1), received_at=now,
        last_trade_quantity=10,
    )
    scanner.on_tick(tick, now=now)
    assert scanner.validate_candidate_depth(signal, now=now) == (False, "full_depth_not_received")
    later = now + timedelta(seconds=7)
    assert scanner.validate_candidate_depth(signal, now=later) == (False, "market_feed_stale")


def test_candidate_depth_rejects_wide_spread_even_if_ltpc_tick_is_fresh():
    instrument = Instrument(
        "RELIANCE", "NSE_EQ|INE002A01018", "Reliance Industries",
        Decimal("0.05"), 1,
    )
    scanner = IntradayScanner((instrument,))
    generated = datetime(2026, 11, 4, 10, 0, tzinfo=IST)
    signal = TradeSignal(
        "vwap_momentum", "RELIANCE", generated, 100, 99, 102, 1.5, 70, "test",
    )
    scanner._candidate_signals[("RELIANCE", "vwap_momentum", generated)] = signal
    now = datetime(2026, 11, 4, 4, 30, 1, tzinfo=timezone.utc)
    tick = MarketTick(
        symbol="RELIANCE", instrument_key=instrument.instrument_key, price=100,
        exchange_time=generated + timedelta(seconds=1), received_at=now,
        last_trade_quantity=10, best_bid=99.4, best_ask=100.6,
        best_bid_quantity=120, best_ask_quantity=80,
    )
    scanner.on_tick(tick, now=now)
    assert scanner.validate_candidate_depth(signal, now=now) == (False, "spread_too_wide")
