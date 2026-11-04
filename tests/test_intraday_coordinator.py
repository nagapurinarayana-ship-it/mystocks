from datetime import datetime, timedelta, timezone
from decimal import Decimal
from zoneinfo import ZoneInfo

from intraday.coordinator import AutonomousPaperCoordinator
from intraday.domain import Instrument, MarketTick, TradeSignal
from intraday.execution.paper import FeeSchedule, PaperExecutionEngine, PaperPosition
from intraday.scanner import IntradayScanner
from intraday.ledger import PaperLedger

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



def test_coordinator_cancels_new_paper_entries_after_1515_ist():
    coordinator, paper, signal, tick, now = components(with_depth=True)
    late_exchange = datetime(2026, 11, 4, 15, 15, 5, tzinfo=IST)
    late_now = late_exchange.astimezone(timezone.utc)
    late_tick = MarketTick(
        symbol="RELIANCE", instrument_key="NSE_EQ|INE002A01018",
        price=100, exchange_time=late_exchange, received_at=late_now,
        last_trade_quantity=10, best_bid=99.95, best_ask=100.05,
        best_bid_quantity=100, best_ask_quantity=100,
    )
    result = coordinator.on_tick(late_tick, now=late_now)
    assert result.queued_signal is None
    assert paper.pending is None


def test_coordinator_paper_square_off_uses_real_position_symbol_tick_after_1525():
    coordinator, paper, signal, tick, now = components(with_depth=True)
    paper.position = PaperPosition(
        symbol="RELIANCE",
        quantity=1,
        entry_price=Decimal("100.00"),
        stop_price=Decimal("99.00"),
        target_price=Decimal("102.00"),
        entry_fee=Decimal("0"),
        tick_size=Decimal("0.05"),
        opened_at=datetime(2026, 11, 4, 10, 0, tzinfo=IST),
        strategy_id="vwap_momentum",
    )
    exchange_time = datetime(2026, 11, 4, 15, 25, 1, tzinfo=IST)
    received = exchange_time.astimezone(timezone.utc)
    close_tick = MarketTick(
        symbol="RELIANCE", instrument_key="NSE_EQ|INE002A01018",
        price=101.0, exchange_time=exchange_time, received_at=received,
        last_trade_quantity=15, best_bid=100.95, best_ask=101.05,
        best_bid_quantity=100, best_ask_quantity=100,
    )
    result = coordinator.on_tick(close_tick, now=received)
    assert any(event.event_type == "exit_filled" for event in result.paper_events)
    assert paper.position is None
    assert paper.trades[-1].exit_reason == "session_close"



def test_coordinator_checkpoints_queued_paper_state_for_restart(tmp_path):
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
    generated = datetime(2026, 11, 4, 10, 0, tzinfo=IST)
    signal = TradeSignal(
        "vwap_momentum", "RELIANCE", generated,
        100, 99, 102, 1.5, 70, "persist candidate",
    )
    scanner._candidate_signals[("RELIANCE", "vwap_momentum", generated)] = signal
    now = datetime(2026, 11, 4, 4, 30, 3, tzinfo=timezone.utc)
    tick = MarketTick(
        "RELIANCE", instrument.instrument_key, 100,
        generated + timedelta(seconds=3), now,
        last_trade_quantity=10,
        best_bid=99.95, best_ask=100.05,
        best_bid_quantity=100, best_ask_quantity=100,
    )

    database = tmp_path / "coordinator-state.sqlite3"
    with PaperLedger(database) as ledger:
        coordinator = AutonomousPaperCoordinator(scanner, paper, ledger)
        update = coordinator.on_tick(tick, now=now)
        assert update.queued_signal == signal
        saved = ledger.load_paper_state()
        assert saved is not None
        assert saved["pending"]["signal"]["symbol"] == "RELIANCE"
        assert saved["cash"] == "1000.00"

    with PaperLedger(database) as reopened:
        restored_engine = PaperExecutionEngine(fees)
        restored_engine.restore_state(reopened.load_paper_state())
        assert restored_engine.pending is not None
        assert restored_engine.pending[0] == signal
        assert restored_engine.cash == Decimal("1000.00")
