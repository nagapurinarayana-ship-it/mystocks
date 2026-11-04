"""Completed five-minute bars and session VWAP from unique exchange trades."""

from __future__ import annotations

from collections import defaultdict, deque
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Deque

from intraday.domain import CompletedBar, MarketTick


@dataclass(slots=True)
class _WorkingBar:
    symbol: str
    start: datetime
    open: float
    high: float
    low: float
    close: float
    volume: int
    value_volume: float

    def apply(self, price: float, quantity: int) -> None:
        self.high = max(self.high, price)
        self.low = min(self.low, price)
        self.close = price
        self.volume += quantity
        self.value_volume += price * quantity

    def freeze(self) -> CompletedBar:
        return CompletedBar(
            symbol=self.symbol,
            start_time=self.start,
            end_time=self.start + timedelta(minutes=5),
            open=self.open,
            high=self.high,
            low=self.low,
            close=self.close,
            volume=self.volume,
        )


class FiveMinuteBarBuilder:
    """Aggregates trade ticks into completed five-minute bars.

    Duplicate trade timestamps are ignored because the feed may repeat the
    latest-trade snapshot. Empty time buckets are not fabricated.
    """

    def __init__(self, history_limit: int = 100) -> None:
        if history_limit < 25:
            raise ValueError("history_limit must be at least 25")
        self._working: dict[str, _WorkingBar] = {}
        self._bars: dict[str, Deque[CompletedBar]] = defaultdict(
            lambda: deque(maxlen=history_limit)
        )
        self._last_trade_time: dict[str, datetime] = {}
        self._last_trade_fingerprint: dict[str, tuple[float, int]] = {}
        self._session_day: dict[str, object] = {}
        self._session_value: dict[str, float] = defaultdict(float)
        self._session_volume: dict[str, int] = defaultdict(int)

    @staticmethod
    def _bucket_start(value: datetime) -> datetime:
        minute = (value.minute // 5) * 5
        return value.replace(minute=minute, second=0, microsecond=0)

    def ingest(self, tick: MarketTick) -> CompletedBar | None:
        if tick.last_trade_quantity <= 0:
            return None
        last_time = self._last_trade_time.get(tick.symbol)
        fingerprint = (tick.price, tick.last_trade_quantity)
        if last_time is not None:
            if tick.exchange_time < last_time:
                return None
            if (
                tick.exchange_time == last_time
                and self._last_trade_fingerprint.get(tick.symbol) == fingerprint
            ):
                return None

        day = tick.exchange_time.date()
        previous_day = self._session_day.get(tick.symbol)
        completed: CompletedBar | None = None
        if previous_day is not None and day != previous_day:
            self._working.pop(tick.symbol, None)
            self._session_value[tick.symbol] = 0.0
            self._session_volume[tick.symbol] = 0
            self._bars[tick.symbol].clear()

        self._session_day[tick.symbol] = day
        self._last_trade_time[tick.symbol] = tick.exchange_time
        self._last_trade_fingerprint[tick.symbol] = fingerprint
        bucket = self._bucket_start(tick.exchange_time)
        working = self._working.get(tick.symbol)
        if working is None:
            self._working[tick.symbol] = _WorkingBar(
                tick.symbol, bucket, tick.price, tick.price, tick.price,
                tick.price, tick.last_trade_quantity, tick.price * tick.last_trade_quantity
            )
            return completed

        if bucket < working.start:
            return None
        if bucket == working.start:
            working.apply(tick.price, tick.last_trade_quantity)
            return completed

        completed = working.freeze()
        self._bars[tick.symbol].append(completed)
        self._session_value[tick.symbol] += working.value_volume
        self._session_volume[tick.symbol] += working.volume
        self._working[tick.symbol] = _WorkingBar(
            tick.symbol, bucket, tick.price, tick.price, tick.price,
            tick.price, tick.last_trade_quantity, tick.price * tick.last_trade_quantity
        )
        return completed

    def bars(self, symbol: str) -> tuple[CompletedBar, ...]:
        return tuple(self._bars.get(symbol, ()))

    def session_vwap(self, symbol: str) -> float | None:
        volume = self._session_volume.get(symbol, 0)
        if volume <= 0:
            return None
        return self._session_value[symbol] / volume
