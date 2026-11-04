"""Connect completed-bar scanner events to the autonomous paper engine."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from intraday.execution.paper import PaperEvent, PaperExecutionEngine
from intraday.scanner import IntradayScanner
from intraday.domain import MarketTick, TradeSignal
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

    def on_tick(self, tick: MarketTick, now: datetime | None = None) -> CoordinatorUpdate:
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
                    if self.ledger is not None:
                        self.ledger.record_signal(signal)
                        self.ledger.record_event(
                            signal.generated_at.isoformat(), "INFO",
                            "paper_signal_queued",
                            f"{signal.strategy_id} candidate queued for {signal.symbol}",
                        )
                    break

        return CoordinatorUpdate(
            accepted_tick=True,
            completed_bars=len(completed),
            paper_events=tuple(events),
            queued_signal=queued,
            feed_fresh=fresh,
        )
