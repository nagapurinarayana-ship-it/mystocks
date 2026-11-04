"""Safe default capital and operating policy for the intraday module."""

from dataclasses import dataclass
from decimal import Decimal


@dataclass(frozen=True)
class CapitalPolicy:
    """Starting-capital guardrails; these do not imply profitable trading."""

    starting_capital: Decimal = Decimal("1000.00")
    max_risk_per_trade_fraction: Decimal = Decimal("0.005")
    max_daily_loss_fraction: Decimal = Decimal("0.01")
    max_open_positions: int = 1
    allow_leverage: bool = False
    allow_external_topups: bool = False
    allow_automatic_withdrawals: bool = False
    recurring_data_budget: Decimal = Decimal("0.00")

    def __post_init__(self) -> None:
        if self.starting_capital <= 0:
            raise ValueError("starting_capital must be positive")
        if not Decimal("0") < self.max_risk_per_trade_fraction <= Decimal("0.01"):
            raise ValueError("per-trade risk fraction must be in (0, 1%]")
        if not Decimal("0") < self.max_daily_loss_fraction <= Decimal("0.02"):
            raise ValueError("daily loss fraction must be in (0, 2%]")
        if self.max_open_positions < 1:
            raise ValueError("max_open_positions must be at least 1")
        if self.recurring_data_budget < 0:
            raise ValueError("recurring_data_budget cannot be negative")
        if self.allow_leverage or self.allow_external_topups or self.allow_automatic_withdrawals:
            raise ValueError("leverage, external top-ups and automatic withdrawals are disabled")

    @property
    def risk_budget_per_trade(self) -> Decimal:
        return self.starting_capital * self.max_risk_per_trade_fraction

    @property
    def daily_loss_limit(self) -> Decimal:
        return self.starting_capital * self.max_daily_loss_fraction


DEFAULT_CAPITAL_POLICY = CapitalPolicy()
