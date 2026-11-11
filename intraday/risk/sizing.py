"""Cash-only position sizing with estimated round-trip costs included."""

from dataclasses import dataclass
from decimal import Decimal, InvalidOperation, ROUND_FLOOR


def _decimal(value: Decimal | int | float | str, field: str) -> Decimal:
    try:
        result = value if isinstance(value, Decimal) else Decimal(str(value))
    except (InvalidOperation, ValueError, TypeError) as exc:
        raise ValueError(f"{field} must be a valid number") from exc
    if not result.is_finite():
        raise ValueError(f"{field} must be finite")
    return result


@dataclass(frozen=True)
class PositionSize:
    quantity: int
    notional: Decimal
    risk_budget: Decimal
    planned_price_loss: Decimal
    estimated_round_trip_cost: Decimal
    reason: str

    @property
    def allowed(self) -> bool:
        return self.quantity > 0


def calculate_cash_position_size(
    *,
    available_cash: Decimal | int | float | str,
    entry_price: Decimal | int | float | str,
    stop_price: Decimal | int | float | str,
    estimated_round_trip_cost_per_share: Decimal | int | float | str = Decimal("0"),
    risk_fraction: Decimal | int | float | str = Decimal("0.005"),
) -> PositionSize:
    """Return a whole-share long position; returns zero quantity when risk disallows it.

    Costs are supplied per share by the broker-specific cost estimator. If the
    feed or cost estimate is unavailable, the caller should not submit an order.
    This function never uses margin or leverage.
    """
    cash = _decimal(available_cash, "available_cash")
    entry = _decimal(entry_price, "entry_price")
    stop = _decimal(stop_price, "stop_price")
    cost = _decimal(estimated_round_trip_cost_per_share, "estimated_round_trip_cost_per_share")
    fraction = _decimal(risk_fraction, "risk_fraction")

    if cash < 0:
        raise ValueError("available_cash cannot be negative")
    if entry <= 0:
        raise ValueError("entry_price must be positive")
    if stop <= 0 or stop >= entry:
        raise ValueError("a long-only stop_price must be positive and below entry_price")
    if cost < 0:
        raise ValueError("estimated round-trip cost cannot be negative")
    if not Decimal("0") < fraction <= Decimal("0.01"):
        raise ValueError("risk_fraction must be in (0, 1%]")

    risk_budget = cash * fraction
    risk_per_share = entry - stop
    all_in_risk_per_share = risk_per_share + cost
    if cash < entry or risk_budget <= 0 or all_in_risk_per_share <= 0:
        return PositionSize(0, Decimal("0"), risk_budget, Decimal("0"), Decimal("0"),
                            "Insufficient cash or no usable risk budget")

    cash_quantity = int((cash / entry).to_integral_value(rounding=ROUND_FLOOR))
    risk_quantity = int((risk_budget / all_in_risk_per_share).to_integral_value(rounding=ROUND_FLOOR))
    quantity = min(cash_quantity, risk_quantity)
    if quantity < 1:
        return PositionSize(0, Decimal("0"), risk_budget, Decimal("0"), Decimal("0"),
                            "One whole share would exceed the configured risk budget")

    notional = entry * quantity
    planned_loss = risk_per_share * quantity
    total_cost = cost * quantity
    if planned_loss + total_cost > risk_budget:
        # Defensive post-condition: never round upward into a risk breach.
        return PositionSize(0, Decimal("0"), risk_budget, Decimal("0"), Decimal("0"),
                            "Estimated stop loss and costs exceed the risk budget")

    return PositionSize(quantity, notional, risk_budget, planned_loss, total_cost,
                        "Cash and configured risk limits satisfied")
