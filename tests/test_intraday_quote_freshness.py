from datetime import datetime, timedelta, timezone
from decimal import Decimal
from zoneinfo import ZoneInfo

from intraday.domain import Instrument, MarketTick, TradeSignal
from intraday.scanner import IntradayScanner

IST = ZoneInfo("Asia/Kolkata")


def make_instrument():
    return Instrument(
        "RELIANCE", "NSE_EQ|INE002A01018", "Reliance Industries",
        Decimal("0.05"), 1,
    )


def make_signal(generated):
    return TradeSignal(
        "vwap_momentum", "RELIANCE", generated, 100, 99, 102, 1.5, 70, "test",
    )


def test_rest_depth_snapshot_updates_quote_but_not_websocket_feed_health():
    instrument = make_instrument()
    scanner = IntradayScanner((instrument,))
    generated = datetime(2026, 11, 4, 10, 0, tzinfo=IST)
    signal = make_signal(generated)
    scanner._candidate_signals[("RELIANCE", "vwap_momentum", generated)] = signal

    now = datetime(2026, 11, 4, 4, 30, 1, tzinfo=timezone.utc)
    ws_tick = MarketTick(
        symbol="RELIANCE", instrument_key=instrument.instrument_key, price=100,
        exchange_time=generated + timedelta(seconds=1), received_at=now,
        last_trade_quantity=10,
    )
    assert scanner.on_tick(ws_tick, now=now)
    original_feed_timestamp = scanner.last_feed_receive

    rest_quote = MarketTick(
        symbol="RELIANCE", instrument_key=instrument.instrument_key, price=100.1,
        exchange_time=generated + timedelta(seconds=2), received_at=now + timedelta(seconds=1),
        best_bid=100.05, best_ask=100.15,
        best_bid_quantity=200, best_ask_quantity=180,
        upper_circuit_limit=110, lower_circuit_limit=90,
    )
    assert scanner.update_quote(rest_quote, now=now + timedelta(seconds=1))
    assert scanner.last_feed_receive == original_feed_timestamp
    assert scanner.validate_candidate_depth(
        signal, now=now + timedelta(seconds=1)
    ) == (True, "depth_validated")


def test_rest_depth_price_drift_over_half_percent_rejects_candidate():
    instrument = make_instrument()
    scanner = IntradayScanner((instrument,))
    generated = datetime(2026, 11, 4, 10, 0, tzinfo=IST)
    signal = make_signal(generated)
    scanner._candidate_signals[("RELIANCE", "vwap_momentum", generated)] = signal

    now = datetime(2026, 11, 4, 4, 30, 1, tzinfo=timezone.utc)
    ws_tick = MarketTick(
        "RELIANCE", instrument.instrument_key, 100,
        generated + timedelta(seconds=1), now, last_trade_quantity=10,
    )
    scanner.on_tick(ws_tick, now=now)
    quote = MarketTick(
        "RELIANCE", instrument.instrument_key, 100.6,
        generated + timedelta(seconds=2), now + timedelta(seconds=1),
        best_bid=100.55, best_ask=100.65,
        best_bid_quantity=100, best_ask_quantity=100,
    )
    assert scanner.update_quote(quote, now=now + timedelta(seconds=1))
    assert scanner.validate_candidate_depth(
        signal, now=now + timedelta(seconds=1)
    ) == (False, "candidate_price_moved_over_0_5_percent")


def test_candidate_from_a_symbol_with_stale_ltp_is_removed_even_if_another_symbol_is_live():
    reliance = make_instrument()
    tcs = Instrument("TCS", "NSE_EQ|TCSKEY", "TCS", Decimal("0.05"), 1)
    scanner = IntradayScanner((reliance, tcs))
    now = datetime(2026, 11, 4, 4, 30, 10, tzinfo=timezone.utc)
    generated = datetime(2026, 11, 4, 10, 0, tzinfo=IST)
    stale_signal = TradeSignal(
        "vwap_momentum", "TCS", generated, 100, 99, 102, 1.5, 70, "test",
    )
    scanner._candidate_signals[("TCS", "vwap_momentum", generated)] = stale_signal

    live_tick = MarketTick(
        "RELIANCE", reliance.instrument_key, 100,
        now.astimezone(IST), now, last_trade_quantity=10,
    )
    scanner.on_tick(live_tick, now=now)
    assert scanner.feed_is_fresh(now=now) is True
    assert scanner.candidate_signals(now=now) == ()
