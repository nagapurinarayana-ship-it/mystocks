"""Connect completed-bar scanner events to the autonomous paper engine."""

from __future__ import annotations

from dataclasses import dataclass
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

    def on_tick(self, tick: MarketTick, now: datetime | None = None) -> CoordinatorUpdate:
        with self._lock:
            return self._on_tick_locked(tick, now)

    def _on_tick_locked(self, tick: MarketTick, now: datetime | None = None) -> CoordinatorUpdate:
        accepted = self.scanner.on_tick(tick, now=now)
        if not accepted:
            return CoordinatorUpdate(False, 0, (), None, self.scanner.feed_is_fresh(now=now))

        completed = self.scanner.drain_completed_bars()
        events: list[PaperEvent] = []
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
                return signal
            return None

        return CoordinatorUpdate(
            accepted_tick=True,
            completed_bars=len(completed),
            paper_events=tuple(events),
            queued_signal=queued,
            feed_fresh=fresh,
        )
