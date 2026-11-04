"""Typed domain contracts for the independent intraday subsystem."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from math import isfinite


def require_aware(value: datetime, field: str) -> None:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{field} must be timezone-aware")


@dataclass(frozen=True, slots=True)
class Instrument:
    symbol: str
    instrument_key: str
    name: str
    tick_size: Decimal
    lot_size: int = 1
    security_type: str = "NORMAL"

    def __post_init__(self) -> None:
        if not self.symbol or not self.instrument_key:
            raise ValueError("instrument symbol and key are required")
        if not self.tick_size.is_finite() or self.tick_size <= 0:
            raise ValueError("tick_size must be positive")
        if self.lot_size != 1:
            raise ValueError("cash-equity scanner supports whole-share lot size 1 only")


@dataclass(frozen=True, slots=True)
class MarketTick:
    symbol: str
    instrument_key: str
    price: float
    exchange_time: datetime
    received_at: datetime
    last_trade_quantity: int = 0
    cumulative_volume: int | None = None
    best_bid: float | None = None
    best_ask: float | None = None
    best_bid_quantity: int | None = None
    best_ask_quantity: int | None = None
    upper_circuit_limit: float | None = None
    lower_circuit_limit: float | None = None

    def __post_init__(self) -> None:
        require_aware(self.exchange_time, "exchange_time")
        require_aware(self.received_at, "received_at")
        if not self.symbol or not self.instrument_key:
            raise ValueError("tick symbol and instrument key are required")
        if not isfinite(self.price) or self.price <= 0:
            raise ValueError("tick price must be positive")
        if self.last_trade_quantity < 0:
            raise ValueError("last_trade_quantity cannot be negative")
        if self.cumulative_volume is not None and self.cumulative_volume < 0:
            raise ValueError("cumulative_volume cannot be negative")
        if self.best_bid is not None and (not isfinite(self.best_bid) or self.best_bid <= 0):
            raise ValueError("best_bid must be positive")
        if self.best_ask is not None and (not isfinite(self.best_ask) or self.best_ask <= 0):
            raise ValueError("best_ask must be positive")
        if self.best_bid is not None and self.best_ask is not None and self.best_bid > self.best_ask:
            raise ValueError("crossed market quote is invalid")
        if self.best_bid_quantity is not None and self.best_bid_quantity < 0:
            raise ValueError("best_bid_quantity cannot be negative")
        if self.best_ask_quantity is not None and self.best_ask_quantity < 0:
            raise ValueError("best_ask_quantity cannot be negative")
        if self.upper_circuit_limit is not None and (
            not isfinite(self.upper_circuit_limit) or self.upper_circuit_limit <= 0
        ):
            raise ValueError("upper_circuit_limit must be positive and finite")
        if self.lower_circuit_limit is not None and (
            not isfinite(self.lower_circuit_limit) or self.lower_circuit_limit <= 0
        ):
            raise ValueError("lower_circuit_limit must be positive and finite")
        if (
            self.upper_circuit_limit is not None
            and self.lower_circuit_limit is not None
            and self.lower_circuit_limit >= self.upper_circuit_limit
        ):
            raise ValueError("circuit band is invalid")


@dataclass(frozen=True, slots=True)
class CompletedBar:
    symbol: str
    start_time: datetime
    end_time: datetime
    open: float
    high: float
    low: float
    close: float
    volume: int

    def __post_init__(self) -> None:
        require_aware(self.start_time, "start_time")
        require_aware(self.end_time, "end_time")
        if self.end_time <= self.start_time:
            raise ValueError("bar end_time must follow start_time")
        if not all(isfinite(value) for value in (self.open, self.high, self.low, self.close)) or min(self.open, self.high, self.low, self.close) <= 0:
            raise ValueError("bar prices must be positive")
        if self.high < max(self.open, self.close, self.low):
            raise ValueError("bar high is inconsistent")
        if self.low > min(self.open, self.close, self.high):
            raise ValueError("bar low is inconsistent")
        if self.volume < 0:
            raise ValueError("bar volume cannot be negative")


@dataclass(frozen=True, slots=True)
class TradeSignal:
    strategy_id: str
    symbol: str
    generated_at: datetime
    entry_reference: float
    stop_price: float
    target_price: float
    volume_ratio: float
    score: float
    explanation: str

    def __post_init__(self) -> None:
        require_aware(self.generated_at, "generated_at")
        if not all(isfinite(value) for value in (self.entry_reference, self.stop_price, self.target_price, self.volume_ratio, self.score)) or self.entry_reference <= 0 or self.stop_price <= 0 or self.target_price <= 0:
            raise ValueError("signal prices must be positive")
        if not self.stop_price < self.entry_reference < self.target_price:
            raise ValueError("long signal must have stop < entry < target")
        if self.volume_ratio < 0 or self.score < 0:
            raise ValueError("signal metrics cannot be negative")
