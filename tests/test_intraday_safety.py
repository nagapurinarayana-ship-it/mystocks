from decimal import Decimal

import pytest

from intraday.config import DEFAULT_CAPITAL_POLICY, CapitalPolicy
from intraday.execution.gate import (
    ExecutionGate,
    ExecutionMode,
    LiveExecutionDisabledError,
)
from intraday.risk.sizing import calculate_cash_position_size


def test_default_capital_policy_is_limited_to_one_thousand_rupees():
    policy = DEFAULT_CAPITAL_POLICY
    assert policy.starting_capital == Decimal("1000.00")
    assert policy.risk_budget_per_trade == Decimal("5.00000")
    assert policy.daily_loss_limit == Decimal("10.0000")
    assert policy.max_open_positions == 1
    assert policy.recurring_data_budget == Decimal("0.00")
    assert policy.allow_leverage is False
    assert policy.allow_external_topups is False
    assert policy.allow_automatic_withdrawals is False


def test_capital_policy_rejects_leverage_and_external_funding():
    with pytest.raises(ValueError):
        CapitalPolicy(allow_leverage=True)
    with pytest.raises(ValueError):
        CapitalPolicy(allow_external_topups=True)
    with pytest.raises(ValueError):
        CapitalPolicy(allow_automatic_withdrawals=True)


def test_position_size_obeys_cash_and_risk_caps():
    result = calculate_cash_position_size(
        available_cash="1000",
        entry_price="100",
        stop_price="95",
        estimated_round_trip_cost_per_share="0.20",
    )
    # Risk budget = ₹5; each share risks ₹5 plus ₹0.20 estimated costs.
    assert result.quantity == 0
    assert result.allowed is False


def test_position_size_can_return_one_share_when_within_risk_budget():
    result = calculate_cash_position_size(
        available_cash="1000",
        entry_price="100",
        stop_price="96",
        estimated_round_trip_cost_per_share="0.20",
    )
    assert result.quantity == 1
    assert result.notional == Decimal("100")
    assert result.planned_price_loss + result.estimated_round_trip_cost <= result.risk_budget


def test_no_trade_when_one_share_exceeds_available_cash():
    result = calculate_cash_position_size(
        available_cash="1000",
        entry_price="1001",
        stop_price="990",
    )
    assert result.quantity == 0
    assert not result.allowed


def test_position_sizing_rejects_invalid_or_missing_risk_inputs():
    with pytest.raises(ValueError):
        calculate_cash_position_size(available_cash="1000", entry_price="0", stop_price="-1")
    with pytest.raises(ValueError):
        calculate_cash_position_size(available_cash="1000", entry_price="100", stop_price="100")
    with pytest.raises(ValueError):
        calculate_cash_position_size(
            available_cash="1000", entry_price="100", stop_price="95",
            estimated_round_trip_cost_per_share="-0.01",
        )


@pytest.mark.parametrize("mode", [ExecutionMode.RESEARCH, ExecutionMode.PAPER, ExecutionMode.LIVE])
def test_live_orders_are_disabled_in_every_mode(mode):
    gate = ExecutionGate(mode=mode)
    assert gate.live_execution_enabled is False
    with pytest.raises(LiveExecutionDisabledError):
        gate.require_live_execution()


def test_paper_mode_must_be_selected_explicitly():
    with pytest.raises(LiveExecutionDisabledError):
        ExecutionGate().require_paper_mode()
    ExecutionGate(mode=ExecutionMode.PAPER).require_paper_mode()
