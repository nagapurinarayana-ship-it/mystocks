"""Connect completed-bar scanner events to the autonomous paper engine."""

from __future__ import annotations

from dataclasses import dataclass
import json
from datetime import datetime, time, timedelta
import threading
from zoneinfo import ZoneInfo

from intraday.execution.paper import PaperEvent, PaperExecutionEngine
from intraday.scanner import IntradayScanner
from intraday.domain import CompletedBar, MarketTick, TradeSignal
from intraday.ledger import PaperLedger


@dataclass(frozen=True, slots=True)
class CoordinatorUpdate:
    accepted_tick: bool
    completed_bars: int
    paper_events: tuple[PaperEvent, ...]
    queued_signal: TradeSignal | None
    feed_fresh: bool


class AutonomousPaperCoordinator:
    """Orchestrates live scan events into paper fills; never places broker orders."""

    def __init__(
        self,
        scanner: IntradayScanner,
        paper_engine: PaperExecutionEngine,
        ledger: PaperLedger | None = None,
    ) -> None:
        self.scanner = scanner
        self.paper_engine = paper_engine
        self.ledger = ledger
        self._depth_status: dict[tuple[str, str, datetime], str] = {}
        self._session_cutoff_handled = False
        self._lock = threading.RLock()
        self._last_saved_state = self._state_json()
        self._last_gap_counts = {
            item.symbol: self.scanner.bar_builder.discontinuity_count(item.symbol)
            for item in self.scanner.instruments.values()
        }

    def _state_json(self) -> str:
        return json.dumps(
            self.paper_engine.export_state(),
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        )

    def _persist_state_if_changed(self, now: datetime | None = None) -> None:
        if self.ledger is None:
            return
        encoded = self._state_json()
        if encoded == self._last_saved_state:
            return
        self.ledger.save_paper_state(
            json.loads(encoded),
            (now or datetime.now(ZoneInfo("UTC"))).isoformat(),
        )
        self._last_saved_state = encoded

    def check_position_feed(
        self, now: datetime | None = None, max_age_seconds: int = 15
    ) -> PaperEvent | None:
        """Fail closed when the symbol backing an open/pending paper trade goes stale."""
        with self._lock:
            now = now or datetime.now(ZoneInfo("UTC"))
            if self.paper_engine.halted_reason is not None:
                return None

            position = self.paper_engine.position
            if position is not None and not self.scanner.symbol_feed_is_fresh(
                position.symbol, now=now, max_age_seconds=max_age_seconds
            ):
                event = self.paper_engine.halt(
                    f"No fresh market tick for open {position.symbol} position within "
                    f"{max_age_seconds}s. The position remains unresolved; review required."
                )
                if self.ledger is not None:
                    self.ledger.record_event(
                        now.isoformat(), "CRITICAL", "paper_position_feed_stale", event.message
                    )
                self._persist_state_if_changed(now=now)
                return event

            pending = self.paper_engine.pending
            if pending is not None:
                signal, _instrument = pending
                if not self.scanner.symbol_feed_is_fresh(
                    signal.symbol, now=now, max_age_seconds=max_age_seconds
                ):
                    event = self.paper_engine.cancel_pending_entry(
                        f"Pending {signal.symbol} paper entry cancelled because its market feed "
                        f"was stale for more than {max_age_seconds}s"
                    )
                    if event is not None and self.ledger is not None:
                        self.ledger.record_event(
                            now.isoformat(), "WARNING",
                            "paper_pending_entry_feed_stale", event.message,
                        )
                    self._persist_state_if_changed(now=now)
                    return event
            return None

    def _handle_symbol_discontinuity(
        self, symbol: str, occurred_at: datetime
    ) -> PaperEvent | None:
        position = self.paper_engine.position
        pending = self.paper_engine.pending
        if self.paper_engine.halted_reason is not None:
            return None
        if position is not None and position.symbol == symbol:
            event = self.paper_engine.halt(
                f"Multi-bucket market-data gap detected for open {symbol} position. "
                "Missing candles cannot be reconstructed; position preserved as unresolved."
            )
            severity = "CRITICAL"
            code = "paper_position_feed_gap"
        elif pending is not None and pending[0].symbol == symbol:
            event = self.paper_engine.cancel_pending_entry(
                f"Pending {symbol} entry cancelled after a multi-bucket market-data gap"
            )
            severity = "WARNING"
            code = "paper_pending_entry_feed_gap"
        else:
            event = None
            severity = "WARNING"
            code = "market_data_bar_gap"
        if self.ledger is not None:
            self.ledger.record_event(
                occurred_at.isoformat(), severity, code,
                event.message if event is not None else
                f"{symbol}: partial candle discarded and stale history/VWAP context reset",
            )
        self._persist_state_if_changed(now=occurred_at)
        return event

    def on_tick(self, tick: MarketTick, now: datetime | None = None) -> CoordinatorUpdate:
        with self._lock:
            return self._on_tick_locked(tick, now)

    def _on_tick_locked(self, tick: MarketTick, now: datetime | None = None) -> CoordinatorUpdate:
        accepted = self.scanner.on_tick(tick, now=now)
        if not accepted:
            return CoordinatorUpdate(False, 0, (), None, self.scanner.feed_is_fresh(now=now))

        completed = self.scanner.drain_completed_bars()
        events: list[PaperEvent] = []
        gap_count = self.scanner.bar_builder.discontinuity_count(tick.symbol)
        previous_gap_count = self._last_gap_counts.get(tick.symbol, 0)
        if gap_count > previous_gap_count:
            self._last_gap_counts[tick.symbol] = gap_count
            gap_event = self._handle_symbol_discontinuity(
                tick.symbol, tick.exchange_time
            )
            if gap_event is not None:
                events.append(gap_event)
        for bar in completed:
            previous_trade_count = len(self.paper_engine.trades)
            event = self.paper_engine.on_bar(bar)
            if event is not None:
                events.append(event)
                if self.ledger is not None:
                    self.ledger.record_event(
                        bar.end_time.isoformat(), "INFO", event.event_type, event.message
                    )
            if self.ledger is not None and len(self.paper_engine.trades) > previous_trade_count:
                for trade in self.paper_engine.trades[previous_trade_count:]:
                    self.ledger.record_trade(trade)

        stale_event = self.check_position_feed(now=now)
        if stale_event is not None:
            events.append(stale_event)

        local_time = tick.exchange_time.astimezone(ZoneInfo("Asia/Kolkata")).time()
        if local_time >= time(15, 15):
            cancelled = self.paper_engine.cancel_pending_entry(
                "No new paper entries after 15:15 IST"
            )
            if cancelled is not None:
                events.append(cancelled)
                if self.ledger is not None:
                    self.ledger.record_event(
                        tick.exchange_time.isoformat(), "INFO",
                        cancelled.event_type, cancelled.message,
                    )

        if local_time >= time(15, 25) and self.paper_engine.position is not None:
            position = self.paper_engine.position
            if tick.symbol == position.symbol:
                mark_bar = CompletedBar(
                    symbol=tick.symbol,
                    start_time=tick.exchange_time,
                    end_time=tick.exchange_time + timedelta(microseconds=1),
                    open=tick.price,
                    high=tick.price,
                    low=tick.price,
                    close=tick.price,
                    volume=tick.last_trade_quantity,
                )
                previous_trade_count = len(self.paper_engine.trades)
                event = self.paper_engine.force_session_close(mark_bar)
                if event is not None:
                    events.append(event)
                    if self.ledger is not None:
                        self.ledger.record_event(
                            tick.exchange_time.isoformat(), "WARNING",
                            "paper_session_close", event.message,
                        )
                if self.ledger is not None and len(self.paper_engine.trades) > previous_trade_count:
                    for trade in self.paper_engine.trades[previous_trade_count:]:
                        self.ledger.record_trade(trade)

        queued = None
        fresh = self.scanner.feed_is_fresh(now=now)
        if fresh and local_time < time(15, 15):
            queued = self.evaluate_candidates(now=now)


        self._persist_state_if_changed(now=now)
        return CoordinatorUpdate(
            accepted_tick=True,
            completed_bars=len(completed),
            paper_events=tuple(events),
            queued_signal=queued,
            feed_fresh=fresh,
        )

    def evaluate_candidates(self, now: datetime | None = None) -> TradeSignal | None:
        """Queue at most one paper entry from a fresh REST-validated depth snapshot."""
        with self._lock:
            now = now or datetime.now(ZoneInfo("UTC"))
            local_time = now.astimezone(ZoneInfo("Asia/Kolkata")).time()
            if local_time >= time(15, 15):
                cancelled = self.paper_engine.cancel_pending_entry(
                    "No new paper entries after 15:15 IST"
                )
                if cancelled is not None and self.ledger is not None:
                    self.ledger.record_event(
                        now.isoformat(), "INFO", cancelled.event_type, cancelled.message
                    )
                self._persist_state_if_changed(now=now)
                return None
            if self.paper_engine.halted_reason is not None:
                return None
            if not self.scanner.feed_is_fresh(now=now):
                return None
            if self.paper_engine.position is not None or self.paper_engine.pending is not None:
                return None

            self.scanner.opportunities(now=now)
            for signal in self.scanner.candidate_signals(now=now):
                key = (signal.symbol, signal.strategy_id, signal.generated_at)
                valid, reason = self.scanner.validate_candidate_depth(signal, now=now)
                if self._depth_status.get(key) != reason:
                    self._depth_status[key] = reason
                    if self.ledger is not None:
                        self.ledger.record_event(
                            now.isoformat(),
                            "INFO" if valid else "WARNING",
                            "candidate_depth_validated" if valid else "candidate_depth_waiting",
                            f"{signal.symbol} {signal.strategy_id}: {reason}",
                        )
                if not valid:
                    continue
                instrument = self.scanner.instruments.get(signal.symbol)
                if instrument is None or not self.paper_engine.submit_signal(signal, instrument):
                    continue
                if self.ledger is not None:
                    self.ledger.record_signal(signal)
                    self.ledger.record_event(
                        signal.generated_at.isoformat(), "INFO",
                        "paper_signal_queued",
                        f"{signal.strategy_id} candidate queued for {signal.symbol} after REST depth validation",
                    )
                self._persist_state_if_changed(now=now)
                return signal
            return None
