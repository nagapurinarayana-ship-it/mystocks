"""Auditable forward paper-validation session tracking.

A qualified session is a data-coverage milestone only. It is not evidence of
profitability and never enables live broker execution.
"""

from __future__ import annotations

from datetime import date, datetime, time, timedelta, timezone
import threading
from zoneinfo import ZoneInfo
from typing import Any


IST = ZoneInfo("Asia/Kolkata")
SESSION_OPEN = time(9, 15)
SESSION_CLOSE = time(15, 30)
START_GRACE = timedelta(minutes=1)
EXPECTED_SESSION_SECONDS = 6.25 * 60 * 60
MIN_COVERAGE_RATIO = 0.98
MIN_HEALTHY_RATIO = 0.98
MAX_LOOP_GAPS = 5
MAX_SAMPLE_INTERVAL_SECONDS = 2.0


class ForwardSessionTracker:
    """Collect per-day feed-observation quality for the 30-session paper trial."""

    def __init__(self, started_at: datetime) -> None:
        self._require_aware(started_at, "started_at")
        local = started_at.astimezone(IST)
        if local.weekday() >= 5:
            raise ValueError("forward validation sessions must be on NSE weekdays")
        if local.time().replace(tzinfo=None) < SESSION_OPEN:
            raise ValueError("forward validation session cannot start before 09:15 IST")
        if local.time().replace(tzinfo=None) >= SESSION_CLOSE:
            raise ValueError("forward validation session cannot start at or after 15:30 IST")

        self.session_date = local.date()
        self.started_at = started_at.astimezone(timezone.utc)
        self.last_sample_at = self.started_at
        self.closed_at: datetime | None = None
        self.status = "in_progress"
        self.observed_seconds = 0.0
        self.healthy_seconds = 0.0
        self.stale_seconds = 0.0
        self.disconnected_seconds = 0.0
        self.other_seconds = 0.0
        self.loop_gap_count = 0
        self.loop_gap_seconds = 0.0
        self.accepted_ticks = 0
        self.discovered_signals = 0
        self.closed_paper_trades = 0
        self.risk_halts = 0
        self._lock = threading.RLock()

    @staticmethod
    def _require_aware(value: datetime, field: str) -> None:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError(f"{field} must be timezone-aware")

    def record_tick(self) -> None:
        with self._lock:
            if self.status == "in_progress":
                self.accepted_ticks += 1

    def record_signal(self) -> None:
        with self._lock:
            if self.status == "in_progress":
                self.discovered_signals += 1

    def record_closed_trade(self) -> None:
        with self._lock:
            if self.status == "in_progress":
                self.closed_paper_trades += 1

    def record_risk_halt(self) -> None:
        with self._lock:
            if self.status == "in_progress":
                self.risk_halts += 1

    def sample(self, now: datetime, feed_state: str) -> None:
        """Account only short, regularly observed loop intervals.

        A long pause is recorded as a monitoring gap, not counted as healthy
        coverage, and capped out of the covered-time numerator.
        """
        self._require_aware(now, "now")
        if feed_state not in {"healthy", "stale", "disconnected", "market_closed"}:
            raise ValueError("unsupported feed state")
        current = now.astimezone(timezone.utc)
        with self._lock:
            if self.status != "in_progress":
                return
            delta = (current - self.last_sample_at).total_seconds()
            if delta < 0:
                raise ValueError("forward validation samples must be chronological")
            if delta > 0:
                if delta > MAX_SAMPLE_INTERVAL_SECONDS:
                    self.loop_gap_count += 1
                    self.loop_gap_seconds += delta
                else:
                    self.observed_seconds += delta
                    if feed_state == "healthy":
                        self.healthy_seconds += delta
                    elif feed_state == "stale":
                        self.stale_seconds += delta
                    elif feed_state == "disconnected":
                        self.disconnected_seconds += delta
                    else:
                        self.other_seconds += delta
            self.last_sample_at = current

    def finish(self, closed_at: datetime) -> dict[str, Any]:
        self._require_aware(closed_at, "closed_at")
        local_close = closed_at.astimezone(IST)
        if local_close.date() != self.session_date:
            raise ValueError("forward session must close on its starting date")
        if local_close.time().replace(tzinfo=None) < SESSION_CLOSE:
            raise ValueError("forward session cannot be finalized before 15:30 IST")

        with self._lock:
            if self.status != "in_progress":
                return self.snapshot()
            self.closed_at = closed_at.astimezone(timezone.utc)
            coverage = min(1.0, self.observed_seconds / EXPECTED_SESSION_SECONDS)
            healthy_ratio = (
                self.healthy_seconds / self.observed_seconds
                if self.observed_seconds > 0 else 0.0
            )
            started_on_time = (
                self.started_at.astimezone(IST)
                <= datetime.combine(self.session_date, SESSION_OPEN, IST) + START_GRACE
            )
            criteria = {
                "started_by_09_16_ist": started_on_time,
                "ended_at_or_after_15_30_ist": True,
                "observation_coverage_at_least_98_percent": coverage >= MIN_COVERAGE_RATIO,
                "healthy_feed_at_least_98_percent": healthy_ratio >= MIN_HEALTHY_RATIO,
                "no_more_than_five_loop_gaps": self.loop_gap_count <= MAX_LOOP_GAPS,
                "at_least_one_accepted_tick": self.accepted_ticks > 0,
                "no_paper_risk_halt": self.risk_halts == 0,
            }
            self.status = "qualified" if all(criteria.values()) else "incomplete"
            return self.snapshot(criteria=criteria)

    def interrupt(self, reason: str = "process restarted before the session was finalized") -> dict[str, Any]:
        with self._lock:
            if self.status == "in_progress":
                self.status = "interrupted"
            result = self.snapshot()
            result["interruption_reason"] = reason[:500]
            return result

    def snapshot(self, criteria: dict[str, bool] | None = None) -> dict[str, Any]:
        with self._lock:
            coverage = min(1.0, self.observed_seconds / EXPECTED_SESSION_SECONDS)
            healthy_ratio = (
                self.healthy_seconds / self.observed_seconds
                if self.observed_seconds > 0 else 0.0
            )
            result: dict[str, Any] = {
                "session_date": self.session_date.isoformat(),
                "status": self.status,
                "started_at": self.started_at.isoformat(),
                "last_sample_at": self.last_sample_at.isoformat(),
                "closed_at": self.closed_at.isoformat() if self.closed_at else None,
                "expected_session_seconds": EXPECTED_SESSION_SECONDS,
                "observed_seconds": round(self.observed_seconds, 3),
                "healthy_seconds": round(self.healthy_seconds, 3),
                "stale_seconds": round(self.stale_seconds, 3),
                "disconnected_seconds": round(self.disconnected_seconds, 3),
                "other_seconds": round(self.other_seconds, 3),
                "coverage_ratio": round(coverage, 6),
                "healthy_ratio": round(healthy_ratio, 6),
                "loop_gap_count": self.loop_gap_count,
                "loop_gap_seconds": round(self.loop_gap_seconds, 3),
                "accepted_ticks": self.accepted_ticks,
                "discovered_signals": self.discovered_signals,
                "closed_paper_trades": self.closed_paper_trades,
                "risk_halts": self.risk_halts,
            }
            if criteria is not None:
                result["qualification_criteria"] = dict(criteria)
            return result

    @classmethod
    def from_snapshot(cls, snapshot: dict[str, Any]) -> "ForwardSessionTracker":
        """Rebuild an in-progress tracker for inspection; use only to mark interrupted."""
        if not isinstance(snapshot, dict):
            raise ValueError("forward session snapshot must be an object")
        started_at = datetime.fromisoformat(snapshot["started_at"])
        tracker = cls(started_at)
        tracker.status = str(snapshot["status"])
        if tracker.status not in {"in_progress", "qualified", "incomplete", "interrupted"}:
            raise ValueError("invalid forward validation session status")
        tracker.last_sample_at = datetime.fromisoformat(snapshot["last_sample_at"])
        tracker.closed_at = (
            datetime.fromisoformat(snapshot["closed_at"])
            if snapshot.get("closed_at") else None
        )
        for field in (
            "observed_seconds", "healthy_seconds", "stale_seconds",
            "disconnected_seconds", "other_seconds", "loop_gap_seconds",
        ):
            value = float(snapshot.get(field, 0))
            if value < 0:
                raise ValueError(f"{field} cannot be negative")
            setattr(tracker, field, value)
        for field in (
            "loop_gap_count", "accepted_ticks", "discovered_signals",
            "closed_paper_trades", "risk_halts",
        ):
            value = int(snapshot.get(field, 0))
            if value < 0:
                raise ValueError(f"{field} cannot be negative")
            setattr(tracker, field, value)
        return tracker
