"""Connect completed-bar scanner events to the autonomous paper engine."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from intraday.execution.paper import PaperEvent, PaperExecutionEngine
from intraday.scanner import IntradayScanner
from intraday.domain import MarketTick, TradeSignal


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
    ) -> None:
        self.scanner = scanner
        self.paper_engine = paper_engine

    def on_tick(self, tick: MarketTick, now: datetime | None = None) -> CoordinatorUpdate:
        accepted = self.scanner.on_tick(tick, now=now)
        if not accepted:
            return CoordinatorUpdate(False, 0, (), None, self.scanner.feed_is_fresh(now=now))

        completed = self.scanner.drain_completed_bars()
        events: list[PaperEvent] = []
        for bar in completed:
            event = self.paper_engine.on_bar(bar)
            if event is not None:
                events.append(event)

        queued: TradeSignal | None = None
        fresh = self.scanner.feed_is_fresh(now=now)
        if (
            fresh
            and self.paper_engine.position is None
            and self.paper_engine.pending is None
        ):
            for signal in self.scanner.opportunities(now=now):
                instrument = self.scanner.instruments.get(signal.symbol)
                if instrument is not None and self.paper_engine.submit_signal(signal, instrument):
                    queued = signal
                    break

        return CoordinatorUpdate(
            accepted_tick=True,
            completed_bars=len(completed),
            paper_events=tuple(events),
            queued_signal=queued,
            feed_fresh=fresh,
        )
