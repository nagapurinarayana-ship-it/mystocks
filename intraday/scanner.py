"""Live-tick to completed-bar to opportunity scanner pipeline."""

from __future__ import annotations

from datetime import datetime, time, timezone
import threading
from zoneinfo import ZoneInfo

from intraday.domain import Instrument, MarketTick, TradeSignal
from intraday.market_data.bars import FiveMinuteBarBuilder
from intraday.market_data.quality import assess_tick
from intraday.strategies import opening_range_breakout_signal, vwap_momentum_signal


class IntradayScanner:
    def __init__(self, instruments: tuple[Instrument, ...], max_opportunities: int = 3) -> None:
        if max_opportunities < 1 or max_opportunities > 3:
            raise ValueError("max_opportunities must be between 1 and 3")
        self.instruments = {item.symbol: item for item in instruments}
        self.by_key = {item.instrument_key: item for item in instruments}
        if len(self.instruments) != len(instruments) or len(self.by_key) != len(instruments):
            raise ValueError("instrument symbols and keys must be unique")
        self.max_opportunities = max_opportunities
        self.bar_builder = FiveMinuteBarBuilder()
        self.last_feed_receive: datetime | None = None
        self.rejected_ticks: dict[str, int] = {}
        self._emitted_signals: set[tuple[str, str, datetime]] = set()
        self._completed_bars = []
        self._latest_ticks: dict[str, MarketTick] = {}
        self._candidate_signals: dict[tuple[str, str, datetime], TradeSignal] = {}
        self._last_feed_by_symbol: dict[str, datetime] = {}
        self._lock = threading.RLock()

    def on_tick(self, tick: MarketTick, now: datetime | None = None) -> bool:
        with self._lock:
            return self._on_tick_locked(tick, now)

    def _on_tick_locked(self, tick: MarketTick, now: datetime | None = None) -> bool:
        exchange_time = tick.exchange_time.astimezone(ZoneInfo("Asia/Kolkata"))
        if (
            exchange_time.weekday() >= 5
            or not (time(9, 15) <= exchange_time.time().replace(tzinfo=None) <= time(15, 30))
        ):
            self.rejected_ticks["outside_regular_session"] = self.rejected_ticks.get("outside_regular_session", 0) + 1
            return False
        if tick.instrument_key not in self.by_key:
            self.rejected_ticks["unknown_instrument"] = self.rejected_ticks.get("unknown_instrument", 0) + 1
            return False
        if self.by_key[tick.instrument_key].symbol != tick.symbol:
            self.rejected_ticks["instrument_symbol_mismatch"] = self.rejected_ticks.get("instrument_symbol_mismatch", 0) + 1
            return False
        quality = assess_tick(tick, now=now or datetime.now(timezone.utc))
        if not quality.accepted:
            self.rejected_ticks[quality.reason] = self.rejected_ticks.get(quality.reason, 0) + 1
            return False
        self.last_feed_receive = tick.received_at
        self._last_feed_by_symbol[tick.symbol] = tick.received_at
        self._latest_ticks[tick.symbol] = tick
        completed = self.bar_builder.ingest(tick)
        if completed is not None:
            self._completed_bars.append(completed)
        return True

    def drain_completed_bars(self):
        """Return bars finalized since the previous drain, in event order."""
        with self._lock:
            completed = tuple(self._completed_bars)
            self._completed_bars.clear()
            return completed

    def update_quote(self, tick: MarketTick, now: datetime | None = None) -> bool:
        """Store a REST full-quote snapshot without treating it as a trade tick."""
        with self._lock:
            instrument = self.by_key.get(tick.instrument_key)
            if instrument is None or instrument.symbol != tick.symbol:
                return False
            quality = assess_tick(tick, now=now or datetime.now(timezone.utc))
            if not quality.accepted:
                self.rejected_ticks[quality.reason] = self.rejected_ticks.get(quality.reason, 0) + 1
                return False
            if (
                tick.best_bid is None or tick.best_ask is None
                or not tick.best_bid_quantity or not tick.best_ask_quantity
            ):
                self.rejected_ticks["quote_missing_top_of_book"] = self.rejected_ticks.get(
                    "quote_missing_top_of_book", 0
                ) + 1
                return False
            self._latest_ticks[tick.symbol] = tick
            return True

    def opportunities(self, now: datetime | None = None) -> tuple[TradeSignal, ...]:
        with self._lock:
            return self._opportunities_locked(now)

    def _opportunities_locked(self, now: datetime | None = None) -> tuple[TradeSignal, ...]:
        if not self.feed_is_fresh(now=now):
            return ()
        candidates: list[TradeSignal] = []
        for symbol, instrument in self.instruments.items():
            if not self._symbol_feed_is_fresh(symbol, now=now):
                continue
            bars = self.bar_builder.bars(symbol)
            vwap = self.bar_builder.session_vwap(symbol)
            for signal in (
                vwap_momentum_signal(instrument, bars, vwap),
                opening_range_breakout_signal(instrument, bars, vwap),
            ):
                if signal is not None:
                    key = (signal.symbol, signal.strategy_id, signal.generated_at)
                    if key not in self._emitted_signals:
                        candidates.append(signal)
        self._emitted_signals.update(
            (item.symbol, item.strategy_id, item.generated_at) for item in candidates
        )
        candidates.sort(key=lambda item: (item.score, item.volume_ratio), reverse=True)
        for item in candidates:
            self._candidate_signals[(item.symbol, item.strategy_id, item.generated_at)] = item
        selected: list[TradeSignal] = []
        seen: set[str] = set()
        for candidate in candidates:
            if candidate.symbol in seen:
                continue
            selected.append(candidate)
            seen.add(candidate.symbol)
            if len(selected) >= self.max_opportunities:
                break
        return tuple(selected)

    def candidate_signals(self, now: datetime | None = None, max_age_minutes: int = 10) -> tuple[TradeSignal, ...]:
        """Return fresh candidates; stale per-symbol data invalidates a candidate."""
        with self._lock:
            now = now or datetime.now(timezone.utc)
            active = []
            for key, signal in list(self._candidate_signals.items()):
                age = (now - signal.generated_at).total_seconds()
                if (
                    age < 0 or age > max_age_minutes * 60
                    or not self._symbol_feed_is_fresh(signal.symbol, now=now)
                ):
                    self._candidate_signals.pop(key, None)
                    continue
                active.append(signal)
            active.sort(key=lambda item: (item.score, item.volume_ratio), reverse=True)
            return tuple(active[: self.max_opportunities])

    def validate_candidate_depth(
        self,
        signal: TradeSignal,
        now: datetime | None = None,
        max_quote_age_seconds: int = 5,
        max_spread_fraction: float = 0.005,
    ) -> tuple[bool, str]:
        """Require fresh, two-sided, non-empty top-of-book liquidity."""
        with self._lock:
            return self._validate_candidate_depth_locked(
                signal, now, max_quote_age_seconds, max_spread_fraction
            )

    def _validate_candidate_depth_locked(
        self,
        signal: TradeSignal,
        now: datetime | None = None,
        max_quote_age_seconds: int = 5,
        max_spread_fraction: float = 0.005,
    ) -> tuple[bool, str]:
        now = now or datetime.now(timezone.utc)
        if not self.feed_is_fresh(now=now):
            return False, "market_feed_stale"
        if not self._symbol_feed_is_fresh(signal.symbol, now=now):
            return False, "candidate_symbol_feed_stale"
        key = (signal.symbol, signal.strategy_id, signal.generated_at)
        if key not in self._candidate_signals:
            return False, "candidate_expired_or_unknown"
        tick = self._latest_ticks.get(signal.symbol)
        if tick is None:
            return False, "no_candidate_quote"
        quote_age = (now - tick.received_at).total_seconds()
        if quote_age < -1:
            return False, "quote_timestamp_in_future"
        if quote_age > max_quote_age_seconds:
            return False, "candidate_quote_stale"
        if tick.best_bid is None or tick.best_ask is None:
            return False, "full_depth_not_received"
        if not tick.best_bid_quantity or not tick.best_ask_quantity:
            return False, "empty_top_of_book"
        if tick.best_ask < tick.best_bid:
            return False, "crossed_quote"
        if tick.upper_circuit_limit is not None and (
            tick.price >= tick.upper_circuit_limit * 0.995
        ):
            return False, "near_upper_circuit"
        if tick.lower_circuit_limit is not None and (
            tick.price <= tick.lower_circuit_limit * 1.005
        ):
            return False, "near_lower_circuit"
        mid = (tick.best_bid + tick.best_ask) / 2.0
        if mid <= 0:
            return False, "invalid_quote_midpoint"
        spread = (tick.best_ask - tick.best_bid) / mid
        if spread > max_spread_fraction:
            return False, "spread_too_wide"
        if signal.entry_reference <= 0:
            return False, "invalid_signal_reference"
        price_drift = abs(tick.price - signal.entry_reference) / signal.entry_reference
        if price_drift > 0.005:
            return False, "candidate_price_moved_over_0_5_percent"
        return True, "depth_validated"

    def invalidate_symbol_candidates(self, symbol: str) -> int:
        """Drop all cached and emitted candidates after this symbol's data gap."""
        with self._lock:
            before = len(self._candidate_signals)
            self._candidate_signals = {
                key: signal
                for key, signal in self._candidate_signals.items()
                if signal.symbol != symbol
            }
            self._emitted_signals = {
                key for key in self._emitted_signals if key[0] != symbol
            }
            return before - len(self._candidate_signals)

    def symbol_feed_is_fresh(
        self, symbol: str, now: datetime | None = None, max_age_seconds: int = 15
    ) -> bool:
        """Public per-instrument feed freshness check for position watchdogs."""
        with self._lock:
            return self._symbol_feed_is_fresh(symbol, now, max_age_seconds)

    def _symbol_feed_is_fresh(
        self, symbol: str, now: datetime | None = None, max_age_seconds: int = 15
    ) -> bool:
        received = self._last_feed_by_symbol.get(symbol)
        if received is None:
            return False
        now = now or datetime.now(timezone.utc)
        age = (now - received).total_seconds()
        return -1.0 <= age <= max_age_seconds

    def feed_is_fresh(self, now: datetime | None = None, max_age_seconds: int = 15) -> bool:
        with self._lock:
            return self._feed_is_fresh_locked(now, max_age_seconds)

    def _feed_is_fresh_locked(self, now: datetime | None = None, max_age_seconds: int = 15) -> bool:
        if self.last_feed_receive is None:
            return False
        now = now or datetime.now(timezone.utc)
        if now.tzinfo is None or now.utcoffset() is None:
            raise ValueError("now must be timezone-aware")
        age = (now - self.last_feed_receive).total_seconds()
        return -1.0 <= age <= max_age_seconds
