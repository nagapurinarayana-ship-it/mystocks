from datetime import datetime
from decimal import Decimal
from zoneinfo import ZoneInfo
import json

import pytest

from intraday.domain import Instrument, TradeSignal
from intraday.execution.paper import (
    FeeSchedule,
    PaperExecutionEngine,
    PaperPosition,
)

IST = ZoneInfo("Asia/Kolkata")


def fees(brokerage_rate="0.0001"):
    return FeeSchedule(
        brokerage_rate=Decimal(brokerage_rate),
        brokerage_cap_per_order=Decimal("20"),
        exchange_transaction_rate=Decimal("0.00001"),
        sebi_turnover_rate=Decimal("0.000001"),
        gst_rate=Decimal("0.18"),
        stt_sell_rate=Decimal("0.00025"),
        stamp_buy_rate=Decimal("0.00003"),
        slippage_bps=Decimal("5"),
    )


def instrument():
    return Instrument(
        "RELIANCE", "NSE_EQ|INE002A01018", "Reliance Industries",
        Decimal("0.05"), 1,
    )


def signal():
    return TradeSignal(
        strategy_id="vwap_momentum",
        symbol="RELIANCE",
        generated_at=datetime(2026, 11, 4, 10, 0, tzinfo=IST),
        entry_reference=100.0,
        stop_price=99.0,
        target_price=102.0,
        volume_ratio=1.5,
        score=70,
        explanation="persistence test setup",
    )


def test_pending_signal_state_round_trips_through_json_and_restore():
    original = PaperExecutionEngine(fees())
    original._day = datetime(2026, 11, 4, tzinfo=IST).date()
    original._day_start_cash = Decimal("1000")
    original._daily_net_pnl = Decimal("-1.25")
    assert original.submit_signal(signal(), instrument())

    snapshot = json.loads(json.dumps(original.export_state()))
    restored = PaperExecutionEngine(fees())
    restored.restore_state(snapshot)

    assert restored.cash == Decimal("1000")
    assert restored._daily_net_pnl == Decimal("-1.25")
    assert restored._day == original._day
    assert restored.pending is not None
    assert restored.pending[0] == original.pending[0]
    assert restored.pending[1] == original.pending[1]
    assert restored.position is None


def test_open_position_state_round_trips_and_keeps_stop_tick_and_daily_guard():
    original = PaperExecutionEngine(fees())
    original.cash = Decimal("899.50")
    original._day = datetime(2026, 11, 4, tzinfo=IST).date()
    original._day_start_cash = Decimal("1000")
    original._daily_net_pnl = Decimal("-3.50")
    original._realised_net_pnl = Decimal("12.75")
    original.position = PaperPosition(
        symbol="RELIANCE",
        quantity=1,
        entry_price=Decimal("100.50"),
        stop_price=Decimal("99.00"),
        target_price=Decimal("103.00"),
        entry_fee=Decimal("0.20"),
        tick_size=Decimal("0.05"),
        opened_at=datetime(2026, 11, 4, 10, 5, tzinfo=IST),
        strategy_id="vwap_momentum",
        bars_held=2,
    )
    snapshot = json.loads(json.dumps(original.export_state()))

    restored = PaperExecutionEngine(fees())
    restored.restore_state(snapshot)
    assert restored.cash == Decimal("899.50")
    assert restored.position is not None
    assert restored.position.quantity == 1
    assert restored.position.stop_price == Decimal("99.00")
    assert restored.position.tick_size == Decimal("0.05")
    assert restored.position.bars_held == 2
    assert restored.daily_net_pnl == Decimal("-3.50")
    assert restored.realised_net_pnl == Decimal("12.75")
    assert restored.daily_loss_limit == Decimal("10.00")


def test_restore_rejects_changed_broker_fee_schedule_without_resetting_engine():
    original = PaperExecutionEngine(fees("0.0001"))
    original.submit_signal(signal(), instrument())
    snapshot = original.export_state()

    restored = PaperExecutionEngine(fees("0.0002"))
    before = restored.export_state()
    with pytest.raises(ValueError, match="fee schedule differs"):
        restored.restore_state(snapshot)
    assert restored.export_state() == before


@pytest.mark.parametrize(
    "mutation",
    [
        lambda state: state.update(version=99),
        lambda state: state.update(cash="NaN"),
        lambda state: state.update(overnight_exit_pending=True),
        lambda state: state.update(position={
            "symbol": "RELIANCE", "quantity": 0, "entry_price": "100",
            "stop_price": "99", "target_price": "102", "entry_fee": "0",
            "tick_size": "0.05", "opened_at": "2026-11-04T10:00:00+05:30",
            "strategy_id": "vwap_momentum", "bars_held": 0,
        }),
    ],
)
def test_corrupt_or_unsafe_paper_state_is_rejected_before_assignment(mutation):
    original = PaperExecutionEngine(fees())
    valid = original.export_state()
    invalid = json.loads(json.dumps(valid))
    mutation(invalid)

    restored = PaperExecutionEngine(fees())
    before = restored.export_state()
    with pytest.raises((ValueError, TypeError, KeyError)):
        restored.restore_state(invalid)
    assert restored.export_state() == before



def test_halted_paper_account_preserves_open_position_and_survives_restart():
    original = PaperExecutionEngine(fees())
    original.cash = Decimal("899.50")
    original.position = PaperPosition(
        symbol="RELIANCE",
        quantity=1,
        entry_price=Decimal("100.50"),
        stop_price=Decimal("99.00"),
        target_price=Decimal("103.00"),
        entry_fee=Decimal("0.20"),
        tick_size=Decimal("0.05"),
        opened_at=datetime(2026, 11, 4, 10, 5, tzinfo=IST),
        strategy_id="vwap_momentum",
        bars_held=2,
    )
    halted = original.halt(
        "No fresh market tick for open RELIANCE position within 15s; manual review required."
    )
    assert halted.event_type == "risk_halt"
    assert original.position is not None
    assert original.position.symbol == "RELIANCE"
    assert original.pending is None
    assert original.halted_reason is not None
    assert original.submit_signal(signal(), instrument()) is False

    snapshot = json.loads(json.dumps(original.export_state()))
    assert snapshot["version"] == 3
    restored = PaperExecutionEngine(fees())
    restored.restore_state(snapshot)

    assert restored.halted_reason == original.halted_reason
    assert restored.position is not None
    assert restored.position.symbol == "RELIANCE"
    assert restored.cash == Decimal("899.50")


def test_halted_paper_account_does_not_simulate_an_exit_from_late_or_missing_bar():
    from datetime import timedelta
    from intraday.domain import CompletedBar

    paper = PaperExecutionEngine(fees())
    paper.position = PaperPosition(
        symbol="RELIANCE",
        quantity=1,
        entry_price=Decimal("100.50"),
        stop_price=Decimal("99.00"),
        target_price=Decimal("103.00"),
        entry_fee=Decimal("0.20"),
        tick_size=Decimal("0.05"),
        opened_at=datetime(2026, 11, 4, 10, 5, tzinfo=IST),
        strategy_id="vwap_momentum",
    )
    paper.halt("Feed gap; position unresolved")
    bar = CompletedBar(
        "RELIANCE",
        datetime(2026, 11, 4, 10, 10, tzinfo=IST),
        datetime(2026, 11, 4, 10, 15, tzinfo=IST),
        98, 98.5, 97, 97.5, 1000,
    )
    assert paper.on_bar(bar) is None
    assert paper.force_session_close(bar) is None
    assert paper.position is not None
    assert paper.trades == []


def test_restore_rejects_invalid_halt_reason_without_resetting_existing_engine():
    original = PaperExecutionEngine(fees())
    invalid = original.export_state()
    invalid["halted_reason"] = "x" * 501
    restored = PaperExecutionEngine(fees())
    before = restored.export_state()

    with pytest.raises(ValueError, match="halt reason"):
        restored.restore_state(invalid)
    assert restored.export_state() == before
