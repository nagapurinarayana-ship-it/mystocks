from datetime import datetime, timedelta
from decimal import Decimal
from zoneinfo import ZoneInfo

import pytest

from intraday.domain import CompletedBar, Instrument, TradeSignal
from intraday.execution.paper import FeeSchedule, PaperExecutionEngine

IST = ZoneInfo("Asia/Kolkata")


def cost_schedule():
    # Test-only tariff fixture. Production must use the selected broker's live tariff.
    return FeeSchedule(
        brokerage_rate=Decimal("0.0001"),
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
        strategy_id="test_strategy",
        symbol="RELIANCE",
        generated_at=datetime(2026, 11, 4, 9, 20, tzinfo=IST),
        entry_reference=100.0,
        stop_price=99.0,
        target_price=102.0,
        volume_ratio=1.5,
        score=70.0,
        explanation="test fixture only",
    )


def bar(start, open_price, high, low, close):
    return CompletedBar(
        symbol="RELIANCE",
        start_time=start,
        end_time=start + timedelta(minutes=5),
        open=open_price,
        high=high,
        low=low,
        close=close,
        volume=1000,
    )


def engine():
    return PaperExecutionEngine(cost_schedule())


def signal_boundary(paper):
    """The bar that generated the signal cannot also provide the entry fill."""
    assert paper.on_bar(
        bar(datetime(2026, 11, 4, 9, 20, tzinfo=IST), 100, 100.5, 99.5, 100.2)
    ) is None
    assert paper.pending is not None
    assert paper.position is None


def test_paper_entry_waits_until_the_first_bar_that_starts_after_signal_time():
    paper = engine()
    assert paper.submit_signal(signal(), instrument()) is True
    signal_boundary(paper)

    event = paper.on_bar(
        bar(datetime(2026, 11, 4, 9, 25, tzinfo=IST), 100, 100.5, 99.5, 100.2)
    )
    assert event is not None and event.event_type == "entry_filled"
    assert event.quantity >= 1
    assert event.price is not None and event.price > Decimal("100")
    assert paper.position is not None
    assert paper.cash >= 0


def test_entry_bar_stop_and_target_collision_is_stop_first():
    paper = engine()
    paper.submit_signal(signal(), instrument())
    signal_boundary(paper)
    event = paper.on_bar(
        bar(datetime(2026, 11, 4, 9, 25, tzinfo=IST), 100, 103, 98, 101)
    )
    assert event is not None and event.event_type == "entry_and_exit_same_bar"
    assert paper.position is None
    assert paper.trades[-1].exit_reason == "entry_bar_stop_first"
    assert paper.trades[-1].net_pnl < 0


def test_entry_bar_target_is_not_ignored():
    paper = engine()
    paper.submit_signal(signal(), instrument())
    signal_boundary(paper)
    event = paper.on_bar(
        bar(datetime(2026, 11, 4, 9, 25, tzinfo=IST), 100, 102.5, 99.5, 102.1)
    )
    assert event is not None and event.event_type == "entry_and_exit_same_bar"
    assert paper.position is None
    assert paper.trades[-1].exit_reason == "entry_bar_profit_target"


def test_same_bar_stop_and_target_during_later_position_bar_uses_stop_first():
    paper = engine()
    paper.submit_signal(signal(), instrument())
    signal_boundary(paper)
    entry = paper.on_bar(
        bar(datetime(2026, 11, 4, 9, 25, tzinfo=IST), 100, 100.5, 99.5, 100.2)
    )
    assert entry is not None and entry.event_type == "entry_filled"

    event = paper.on_bar(
        bar(datetime(2026, 11, 4, 9, 30, tzinfo=IST), 100, 103, 98, 101)
    )
    assert event is not None and event.event_type == "exit_filled"
    assert paper.trades[-1].exit_reason == "same_bar_stop_first"
    assert paper.position is None
    assert paper.cash < Decimal("1000")
    assert paper.trades[-1].net_pnl < 0


def test_profit_target_exit_is_recorded_net_of_broker_charges():
    paper = engine()
    paper.submit_signal(signal(), instrument())
    signal_boundary(paper)
    entry = paper.on_bar(
        bar(datetime(2026, 11, 4, 9, 25, tzinfo=IST), 100, 100.5, 99.5, 100.2)
    )
    assert entry is not None and entry.event_type == "entry_filled"

    event = paper.on_bar(
        bar(datetime(2026, 11, 4, 9, 30, tzinfo=IST), 100.5, 102.5, 100.2, 102.2)
    )
    assert event is not None
    assert paper.trades[-1].exit_reason == "profit_target"
    assert paper.trades[-1].charges > 0
    assert paper.trades[-1].net_pnl == paper.trades[-1].gross_pnl - paper.trades[-1].charges


def test_entry_is_rejected_when_eligible_open_gaps_beyond_allowed_drift():
    paper = engine()
    paper.submit_signal(signal(), instrument())
    signal_boundary(paper)
    event = paper.on_bar(
        bar(datetime(2026, 11, 4, 9, 25, tzinfo=IST), 101, 101.5, 100.5, 101.2)
    )
    assert event is not None and event.event_type == "signal_expired"
    assert paper.position is None
    assert paper.cash == Decimal("1000.00")


def test_paper_engine_rejects_second_concurrent_signal():
    paper = engine()
    assert paper.submit_signal(signal(), instrument())
    assert not paper.submit_signal(signal(), instrument())


def test_daily_risk_budget_can_reject_trade_that_cannot_fit_one_share():
    paper = engine()
    expensive_signal = TradeSignal(
        strategy_id="test",
        symbol="RELIANCE",
        generated_at=datetime(2026, 11, 4, 9, 20, tzinfo=IST),
        entry_reference=100.0,
        stop_price=90.0,
        target_price=120.0,
        volume_ratio=1.0,
        score=1.0,
        explanation="test",
    )
    paper.submit_signal(expensive_signal, instrument())
    signal_boundary(paper)
    event = paper.on_bar(
        bar(datetime(2026, 11, 4, 9, 25, tzinfo=IST), 100, 100.5, 99.5, 100.2)
    )
    assert event is not None and event.event_type == "entry_rejected"
    assert paper.position is None
    assert paper.cash == Decimal("1000.00")


def test_session_close_closes_position_and_cancels_pending_entry():
    paper = engine()
    paper.submit_signal(signal(), instrument())
    signal_boundary(paper)
    entry = paper.on_bar(
        bar(datetime(2026, 11, 4, 9, 25, tzinfo=IST), 100, 100.5, 99.5, 100.2)
    )
    assert entry is not None and entry.event_type == "entry_filled"
    event = paper.force_session_close(
        bar(datetime(2026, 11, 4, 15, 20, tzinfo=IST), 101, 101.2, 100.8, 101)
    )
    assert event is not None and event.event_type == "exit_filled"
    assert paper.position is None
    assert paper.trades[-1].exit_reason == "session_close"


def test_fee_schedule_rejects_negative_or_excessive_cost_inputs():
    with pytest.raises(ValueError):
        FeeSchedule(
            brokerage_rate=Decimal("-0.1"), brokerage_cap_per_order=Decimal("20"),
            exchange_transaction_rate=Decimal("0"), sebi_turnover_rate=Decimal("0"),
            gst_rate=Decimal("0"), stt_sell_rate=Decimal("0"),
            stamp_buy_rate=Decimal("0"), slippage_bps=Decimal("0"),
        )
    with pytest.raises(ValueError):
        FeeSchedule(
            brokerage_rate=Decimal("0"), brokerage_cap_per_order=Decimal("20"),
            exchange_transaction_rate=Decimal("0"), sebi_turnover_rate=Decimal("0"),
            gst_rate=Decimal("0"), stt_sell_rate=Decimal("0"),
            stamp_buy_rate=Decimal("0"), slippage_bps=Decimal("1001"),
        )


def test_signal_expires_if_first_eligible_bar_is_more_than_five_minutes_late():
    paper = engine()
    paper.submit_signal(signal(), instrument())
    signal_boundary(paper)
    event = paper.on_bar(
        bar(datetime(2026, 11, 4, 9, 30, tzinfo=IST), 100, 100.5, 99.5, 100.2)
    )
    assert event is not None and event.event_type == "signal_expired"
    assert paper.position is None
    assert paper.cash == Decimal("1000.00")


def test_overnight_safety_exit_waits_for_the_open_of_the_correct_symbol():
    paper = engine()
    paper.submit_signal(signal(), instrument())
    signal_boundary(paper)
    entry = paper.on_bar(
        bar(datetime(2026, 11, 4, 9, 25, tzinfo=IST), 100, 100.5, 99.5, 100.2)
    )
    assert entry is not None and entry.event_type == "entry_filled"
    assert paper.position is not None

    other_symbol_bar = CompletedBar(
        symbol="TCS",
        start_time=datetime(2026, 11, 5, 9, 15, tzinfo=IST),
        end_time=datetime(2026, 11, 5, 9, 20, tzinfo=IST),
        open=3500, high=3510, low=3490, close=3505, volume=1000,
    )
    assert paper.on_bar(other_symbol_bar) is None
    assert paper.position is not None

    position_open = bar(
        datetime(2026, 11, 5, 9, 15, tzinfo=IST),
        98, 99, 97, 98.5,
    )
    event = paper.on_bar(position_open)
    assert event is not None and event.event_type == "exit_filled"
    assert paper.trades[-1].exit_reason == "overnight_safety_exit"
    assert paper.position is None
