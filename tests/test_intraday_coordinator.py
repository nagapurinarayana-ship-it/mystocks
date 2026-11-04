from datetime import datetime, timedelta, timezone
from decimal import Decimal
from zoneinfo import ZoneInfo

from intraday.coordinator import AutonomousPaperCoordinator
from intraday.domain import Instrument, MarketTick, TradeSignal
from intraday.execution.paper import FeeSchedule, PaperExecutionEngine
from intraday.scanner import IntradayScanner

IST = ZoneInfo("Asia/Kolkata")


def components(with_depth=True):
    instrument = Instrument(
        "RELIANCE", "NSE_EQ|INE002A01018", "Reliance Industries",
        Decimal("0.05"), 1,
    )
    scanner = IntradayScanner((instrument,))
    fees = FeeSchedule(
        brokerage_rate=Decimal("0.0001"),
        brokerage_cap_per_order=Decimal("20"),
        exchange_transaction_rate=Decimal("0.00001"),
        sebi_turnover_rate=Decimal("0.000001"),
        gst_rate=Decimal("0.18"),
        stt_sell_rate=Decimal("0.00025"),
        stamp_buy_rate=Decimal("0.00003"),
        slippage_bps=Decimal("5"),
    )
    paper = PaperExecutionEngine(fees)
    coordinator = AutonomousPaperCoordinator(scanner, paper)
    generated = datetime(2026, 11, 4, 10, 0, tzinfo=IST)
    signal = TradeSignal(
        "vwap_momentum", "RELIANCE", generated,
        100, 99, 102, 1.5, 70, "test candidate",
    )
    scanner._candidate_signals[("RELIANCE", "vwap_momentum", generated)] = signal
    now = datetime(2026, 11, 4, 4, 30, 3, tzinfo=timezone.utc)
    tick = MarketTick(
        symbol="RELIANCE",
        instrument_key=instrument.instrument_key,
        price=100,
        exchange_time=generated + timedelta(seconds=3),
        received_at=now,
        last_trade_quantity=10,
        best_bid=99.95 if with_depth else None,
        best_ask=100.05 if with_depth else None,
        best_bid_quantity=100 if with_depth else None,
        best_ask_quantity=100 if with_depth else None,
    )
    return coordinator, paper, signal, tick, now


def test_coordinator_queues_paper_signal_only_after_depth_validation():
    coordinator, paper, signal, tick, now = components(with_depth=True)
    result = coordinator.on_tick(tick, now=now)
    assert result.accepted_tick is True
    assert result.feed_fresh is True
    assert result.queued_signal == signal
    assert paper.pending is not None
    assert paper.position is None


def test_coordinator_does_not_queue_signal_without_full_depth():
    coordinator, paper, signal, tick, now = components(with_depth=False)
    result = coordinator.on_tick(tick, now=now)
    assert result.accepted_tick is True
    assert result.queued_signal is None
    assert paper.pending is None
    assert paper.position is None
