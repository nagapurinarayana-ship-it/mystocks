"""Durable SQLite audit ledger for intraday signals, paper fills and system events."""

from __future__ import annotations

import json
import sqlite3
import threading
from pathlib import Path
from typing import Any

from intraday.domain import TradeSignal
from intraday.execution.paper import PaperTrade


SCHEMA = """
PRAGMA foreign_keys = ON;
CREATE TABLE IF NOT EXISTS intraday_signals (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    symbol TEXT NOT NULL,
    strategy_id TEXT NOT NULL,
    generated_at TEXT NOT NULL,
    entry_reference TEXT NOT NULL,
    stop_price TEXT NOT NULL,
    target_price TEXT NOT NULL,
    volume_ratio TEXT NOT NULL,
    score TEXT NOT NULL,
    explanation TEXT NOT NULL,
    UNIQUE(symbol, strategy_id, generated_at)
);
CREATE INDEX IF NOT EXISTS ix_intraday_signals_generated
    ON intraday_signals(generated_at DESC);
CREATE TABLE IF NOT EXISTS intraday_paper_trades (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    symbol TEXT NOT NULL,
    strategy_id TEXT NOT NULL,
    quantity INTEGER NOT NULL,
    entry_price TEXT NOT NULL,
    exit_price TEXT NOT NULL,
    entry_time TEXT NOT NULL,
    exit_time TEXT NOT NULL,
    gross_pnl TEXT NOT NULL,
    charges TEXT NOT NULL,
    net_pnl TEXT NOT NULL,
    exit_reason TEXT NOT NULL,
    UNIQUE(symbol, strategy_id, entry_time, exit_time, quantity)
);
CREATE INDEX IF NOT EXISTS ix_intraday_paper_trades_exit
    ON intraday_paper_trades(exit_time DESC);
CREATE TABLE IF NOT EXISTS intraday_system_events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    occurred_at TEXT NOT NULL,
    severity TEXT NOT NULL,
    code TEXT NOT NULL,
    message TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS ix_intraday_events_time
    ON intraday_system_events(occurred_at DESC);
CREATE TABLE IF NOT EXISTS intraday_paper_state (
    id INTEGER PRIMARY KEY CHECK (id = 1),
    state_json TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS intraday_forward_validation (
    session_date TEXT PRIMARY KEY,
    status TEXT NOT NULL,
    snapshot_json TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS ix_intraday_forward_validation_status
    ON intraday_forward_validation(status, session_date DESC);
"""


class PaperLedger:
    """Thread-safe, local audit store. Never stores broker credentials or tokens."""

    def __init__(self, database_path: str | Path = "data/mystocks_intraday.sqlite3") -> None:
        self.database_path = str(database_path)
        if self.database_path != ":memory:":
            Path(self.database_path).parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()
        self._connection = sqlite3.connect(
            self.database_path, timeout=10, check_same_thread=False
        )
        self._connection.row_factory = sqlite3.Row
        self._connection.execute("PRAGMA journal_mode = WAL")
        self._connection.executescript(SCHEMA)
        self._connection.commit()

    def close(self) -> None:
        with self._lock:
            self._connection.close()

    def __enter__(self) -> "PaperLedger":
        return self

    def __exit__(self, *_: Any) -> None:
        self.close()

    def record_signal(self, signal: TradeSignal) -> bool:
        with self._lock, self._connection:
            cursor = self._connection.execute(
                """
                INSERT OR IGNORE INTO intraday_signals
                (symbol, strategy_id, generated_at, entry_reference, stop_price,
                 target_price, volume_ratio, score, explanation)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    signal.symbol, signal.strategy_id, signal.generated_at.isoformat(),
                    str(signal.entry_reference), str(signal.stop_price),
                    str(signal.target_price), str(signal.volume_ratio),
                    str(signal.score), signal.explanation,
                ),
            )
            return cursor.rowcount == 1

    def record_trade(self, trade: PaperTrade) -> bool:
        with self._lock, self._connection:
            cursor = self._connection.execute(
                """
                INSERT OR IGNORE INTO intraday_paper_trades
                (symbol, strategy_id, quantity, entry_price, exit_price, entry_time,
                 exit_time, gross_pnl, charges, net_pnl, exit_reason)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    trade.symbol, trade.strategy_id, trade.quantity,
                    str(trade.entry_price), str(trade.exit_price),
                    trade.entry_time.isoformat(), trade.exit_time.isoformat(),
                    str(trade.gross_pnl), str(trade.charges), str(trade.net_pnl),
                    trade.exit_reason,
                ),
            )
            return cursor.rowcount == 1

    def record_event(
        self, occurred_at: str, severity: str, code: str, message: str
    ) -> None:
        with self._lock, self._connection:
            self._connection.execute(
                """
                INSERT INTO intraday_system_events
                (occurred_at, severity, code, message) VALUES (?, ?, ?, ?)
                """,
                (occurred_at, severity, code, message[:1000]),
            )

    def recent_signals(self, limit: int = 25) -> list[dict[str, Any]]:
        if not 1 <= limit <= 500:
            raise ValueError("limit must be between 1 and 500")
        with self._lock:
            rows = self._connection.execute(
                "SELECT * FROM intraday_signals ORDER BY generated_at DESC LIMIT ?",
                (limit,),
            ).fetchall()
            return [dict(row) for row in rows]

    def recent_trades(self, limit: int = 25) -> list[dict[str, Any]]:
        if not 1 <= limit <= 500:
            raise ValueError("limit must be between 1 and 500")
        with self._lock:
            rows = self._connection.execute(
                "SELECT * FROM intraday_paper_trades ORDER BY exit_time DESC LIMIT ?",
                (limit,),
            ).fetchall()
            return [dict(row) for row in rows]

    def latest_event(self) -> dict[str, Any] | None:
        with self._lock:
            row = self._connection.execute(
                "SELECT * FROM intraday_system_events ORDER BY id DESC LIMIT 1"
            ).fetchone()
            return dict(row) if row else None

    def latest_feed_event(self) -> dict[str, Any] | None:
        with self._lock:
            row = self._connection.execute(
                """
                SELECT * FROM intraday_system_events
                WHERE code IN ('feed_healthy', 'feed_stale', 'feed_disconnected',
                               'feed_market_closed', 'scanner_starting', 'scanner_stopped')
                ORDER BY id DESC LIMIT 1
                """
            ).fetchone()
            return dict(row) if row else None

    def save_paper_state(self, state: dict[str, Any], updated_at: str) -> None:
        """Persist the single resumable paper account snapshot atomically."""
        if not isinstance(state, dict):
            raise ValueError("paper state must be a dictionary")
        try:
            encoded = json.dumps(state, separators=(",", ":"), sort_keys=True, allow_nan=False)
        except (TypeError, ValueError) as exc:
            raise ValueError("paper state is not valid JSON data") from exc
        with self._lock, self._connection:
            self._connection.execute(
                """
                INSERT INTO intraday_paper_state (id, state_json, updated_at)
                VALUES (1, ?, ?)
                ON CONFLICT(id) DO UPDATE SET
                    state_json = excluded.state_json,
                    updated_at = excluded.updated_at
                """,
                (encoded, updated_at),
            )

    def load_paper_state(self) -> dict[str, Any] | None:
        """Load saved state; malformed or corrupt data raises and must not reset cash."""
        with self._lock:
            row = self._connection.execute(
                "SELECT state_json FROM intraday_paper_state WHERE id = 1"
            ).fetchone()
            if row is None:
                return None
            try:
                state = json.loads(row["state_json"])
            except (TypeError, json.JSONDecodeError) as exc:
                raise ValueError("saved paper state is corrupt; refusing a silent reset") from exc
            if not isinstance(state, dict):
                raise ValueError("saved paper state has an invalid shape")
            return state

    def paper_state_updated_at(self) -> str | None:
        with self._lock:
            row = self._connection.execute(
                "SELECT updated_at FROM intraday_paper_state WHERE id = 1"
            ).fetchone()
            return str(row["updated_at"]) if row else None

    def save_forward_session(self, snapshot: dict[str, Any], updated_at: str) -> None:
        """Persist one date-keyed forward-validation session snapshot."""
        if not isinstance(snapshot, dict):
            raise ValueError("forward session snapshot must be a dictionary")
        session_date = snapshot.get("session_date")
        status = snapshot.get("status")
        if not isinstance(session_date, str) or len(session_date) != 10:
            raise ValueError("forward session date must be YYYY-MM-DD")
        if status not in {"in_progress", "qualified", "incomplete", "interrupted"}:
            raise ValueError("forward session status is invalid")
        try:
            encoded = json.dumps(
                snapshot, separators=(",", ":"), sort_keys=True, allow_nan=False
            )
        except (TypeError, ValueError) as exc:
            raise ValueError("forward session snapshot is not valid JSON data") from exc
        with self._lock, self._connection:
            self._connection.execute(
                """
                INSERT INTO intraday_forward_validation
                    (session_date, status, snapshot_json, updated_at)
                VALUES (?, ?, ?, ?)
                ON CONFLICT(session_date) DO UPDATE SET
                    status = excluded.status,
                    snapshot_json = excluded.snapshot_json,
                    updated_at = excluded.updated_at
                """,
                (session_date, status, encoded, updated_at),
            )

    def load_forward_session(self, session_date: str) -> dict[str, Any] | None:
        with self._lock:
            row = self._connection.execute(
                "SELECT snapshot_json FROM intraday_forward_validation WHERE session_date = ?",
                (session_date,),
            ).fetchone()
            if row is None:
                return None
            try:
                snapshot = json.loads(row["snapshot_json"])
            except (TypeError, json.JSONDecodeError) as exc:
                raise ValueError("saved forward-validation session is corrupt") from exc
            if not isinstance(snapshot, dict):
                raise ValueError("saved forward-validation session has an invalid shape")
            return snapshot

    def forward_sessions(self, limit: int = 100) -> list[dict[str, Any]]:
        if not 1 <= limit <= 1000:
            raise ValueError("limit must be between 1 and 1000")
        with self._lock:
            rows = self._connection.execute(
                """
                SELECT snapshot_json FROM intraday_forward_validation
                ORDER BY session_date DESC LIMIT ?
                """,
                (limit,),
            ).fetchall()
        result = []
        for row in rows:
            try:
                snapshot = json.loads(row["snapshot_json"])
            except (TypeError, json.JSONDecodeError) as exc:
                raise ValueError("saved forward-validation session is corrupt") from exc
            if not isinstance(snapshot, dict):
                raise ValueError("saved forward-validation session has an invalid shape")
            result.append(snapshot)
        return result

    def forward_validation_summary(self) -> dict[str, int]:
        with self._lock:
            rows = self._connection.execute(
                """
                SELECT status, COUNT(*) AS count
                FROM intraday_forward_validation
                GROUP BY status
                """
            ).fetchall()
        counts = {
            "total_sessions": 0,
            "qualified_sessions": 0,
            "incomplete_sessions": 0,
            "interrupted_sessions": 0,
            "in_progress_sessions": 0,
        }
        for row in rows:
            status = str(row["status"])
            count = int(row["count"])
            counts["total_sessions"] += count
            key = {
                "qualified": "qualified_sessions",
                "incomplete": "incomplete_sessions",
                "interrupted": "interrupted_sessions",
                "in_progress": "in_progress_sessions",
            }.get(status)
            if key:
                counts[key] = count
        return counts

    def interrupt_open_forward_sessions(self, occurred_at: str) -> int:
        """Mark sessions left open by a previous process as interrupted."""
        with self._lock, self._connection:
            rows = self._connection.execute(
                """
                SELECT session_date, snapshot_json
                FROM intraday_forward_validation
                WHERE status = 'in_progress'
                """
            ).fetchall()
            for row in rows:
                try:
                    snapshot = json.loads(row["snapshot_json"])
                except (TypeError, json.JSONDecodeError) as exc:
                    raise ValueError("saved forward-validation session is corrupt") from exc
                if not isinstance(snapshot, dict):
                    raise ValueError("saved forward-validation session has an invalid shape")
                snapshot["status"] = "interrupted"
                snapshot["interruption_reason"] = (
                    "scanner process restarted before this market session was finalized"
                )
                encoded = json.dumps(
                    snapshot, separators=(",", ":"), sort_keys=True, allow_nan=False
                )
                self._connection.execute(
                    """
                    UPDATE intraday_forward_validation
                    SET status = 'interrupted', snapshot_json = ?, updated_at = ?
                    WHERE session_date = ?
                    """,
                    (encoded, occurred_at, row["session_date"]),
                )
            return len(rows)

    def paper_performance(self) -> dict[str, Any]:
        with self._lock:
            row = self._connection.execute(
                """
                SELECT COUNT(*) AS trades,
                       COALESCE(SUM(CAST(net_pnl AS REAL)), 0) AS realised_net_pnl,
                       COALESCE(SUM(CASE WHEN CAST(net_pnl AS REAL) > 0 THEN 1 ELSE 0 END), 0) AS wins,
                       COALESCE(SUM(CASE WHEN CAST(net_pnl AS REAL) < 0 THEN 1 ELSE 0 END), 0) AS losses,
                       COALESCE(SUM(CAST(charges AS REAL)), 0) AS charges
                FROM intraday_paper_trades
                """
            ).fetchone()
            return dict(row)
