"""Fail-closed freshness checks for streaming market data."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from intraday.domain import MarketTick


@dataclass(frozen=True, slots=True)
class TickQuality:
    accepted: bool
    reason: str


def assess_tick(
    tick: MarketTick,
    now: datetime | None = None,
    max_exchange_age: timedelta = timedelta(seconds=30),
    max_future_skew: timedelta = timedelta(seconds=3),
    max_receive_delay: timedelta = timedelta(seconds=5),
) -> TickQuality:
    now = now or datetime.now(timezone.utc)
    if now.tzinfo is None or now.utcoffset() is None:
        raise ValueError("now must be timezone-aware")

    exchange_age = now - tick.exchange_time
    receive_delay = tick.received_at - tick.exchange_time

    if exchange_age < -max_future_skew:
        return TickQuality(False, "exchange_timestamp_in_future")
    if exchange_age > max_exchange_age:
        return TickQuality(False, "stale_exchange_tick")
    if receive_delay > max_receive_delay:
        return TickQuality(False, "delayed_delivery")
    if tick.received_at > now + max_future_skew:
        return TickQuality(False, "receive_timestamp_in_future")
    if tick.upper_circuit_limit is not None and tick.price >= tick.upper_circuit_limit:
        return TickQuality(False, "upper_circuit")
    if tick.lower_circuit_limit is not None and tick.price <= tick.lower_circuit_limit:
        return TickQuality(False, "lower_circuit")
    if tick.best_bid is not None and tick.best_ask is not None:
        if (tick.best_ask - tick.best_bid) / tick.best_ask > 0.02:
            return TickQuality(False, "spread_over_2_percent")
    return TickQuality(True, "accepted")
