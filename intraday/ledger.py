"""Durable SQLite audit ledger for intraday signals, paper fills and system events."""

from __future__ import annotations

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
                               'scanner_starting', 'scanner_stopped')
                ORDER BY id DESC LIMIT 1
                """
            ).fetchone()
            return dict(row) if row else None

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
