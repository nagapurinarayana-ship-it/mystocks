"""Live-tick to completed-bar to opportunity scanner pipeline."""

from __future__ import annotations

from datetime import datetime, timezone

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

    def on_tick(self, tick: MarketTick, now: datetime | None = None) -> bool:
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
        self.bar_builder.ingest(tick)
        return True

    def opportunities(self, now: datetime | None = None) -> tuple[TradeSignal, ...]:
        if not self.feed_is_fresh(now=now):
            return ()
        candidates: list[TradeSignal] = []
        for symbol, instrument in self.instruments.items():
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
        candidates.sort(key=lambda item: (item.score, item.volume_ratio), reverse=True)
        selected: list[TradeSignal] = []
        seen: set[str] = set()
        for candidate in candidates:
            if candidate.symbol in seen:
                continue
            selected.append(candidate)
            self._emitted_signals.add((candidate.symbol, candidate.strategy_id, candidate.generated_at))
            seen.add(candidate.symbol)
            if len(selected) >= self.max_opportunities:
                break
        return tuple(selected)

    def feed_is_fresh(self, now: datetime | None = None, max_age_seconds: int = 15) -> bool:
        if self.last_feed_receive is None:
            return False
        now = now or datetime.now(timezone.utc)
        if now.tzinfo is None or now.utcoffset() is None:
            raise ValueError("now must be timezone-aware")
        return (now - self.last_feed_receive).total_seconds() <= max_age_seconds
