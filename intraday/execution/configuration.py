"""Explicit broker fee-schedule configuration shared by paper and backtest tools."""

from __future__ import annotations

import os
from decimal import Decimal, InvalidOperation

from intraday.execution.paper import FeeSchedule


FEE_ENV_FIELDS = {
    "brokerage_rate": "BROKERAGE_RATE",
    "brokerage_cap_per_order": "BROKERAGE_CAP",
    "exchange_transaction_rate": "EXCHANGE_RATE",
    "sebi_turnover_rate": "SEBI_RATE",
    "gst_rate": "GST_RATE",
    "stt_sell_rate": "STT_SELL_RATE",
    "stamp_buy_rate": "STAMP_BUY_RATE",
    "slippage_bps": "SLIPPAGE_BPS",
}


class FeeConfigurationError(RuntimeError):
    """The broker tariff is absent, incomplete or invalid."""


def load_fee_schedule_from_environment(
    prefix: str = "MYSTOCKS_PAPER_FEE_",
) -> FeeSchedule | None:
    """Return None when not configured; reject partial schedules; never guess rates.

    Values are proportions, except slippage_bps which is basis points. Obtain
    every value from the selected broker's current tariff and explicit slippage
    assumptions for the instrument/timeframe being tested.
    """
    present = {
        field: os.getenv(f"{prefix}{suffix}")
        for field, suffix in FEE_ENV_FIELDS.items()
    }
    configured = {field: value for field, value in present.items() if value is not None}
    if not configured:
        return None
    missing = sorted(set(FEE_ENV_FIELDS) - set(configured))
    if missing:
        names = ", ".join(f"{prefix}{FEE_ENV_FIELDS[field]}" for field in missing)
        raise FeeConfigurationError(f"paper fee configuration is incomplete; missing: {names}")
    try:
        values = {field: Decimal(value) for field, value in configured.items()}
    except (InvalidOperation, TypeError) as exc:
        raise FeeConfigurationError("paper fee configuration contains an invalid decimal") from exc
    try:
        return FeeSchedule(**values)
    except ValueError as exc:
        raise FeeConfigurationError(f"paper fee configuration is invalid: {exc}") from exc
