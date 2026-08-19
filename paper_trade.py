from __future__ import annotations

from dataclasses import dataclass, asdict
from datetime import date
import json
from pathlib import Path


@dataclass
class PaperTrade:
    signal_date: str
    symbol: str
    entry: float
    target: float
    stop: float
    result: str = "open"
    exit_price: float | None = None
    exit_date: str | None = None


class PaperLedger:
    def __init__(self, path: str = "data/paper_trades.json"):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)

    def load(self) -> list[PaperTrade]:
        if not self.path.exists():
            return []
        return [PaperTrade(**x) for x in json.loads(self.path.read_text())]

    def save(self, trades: list[PaperTrade]) -> None:
        self.path.write_text(json.dumps([asdict(t) for t in trades], indent=2))

    def add(self, symbol: str, entry: float, target: float, stop: float, signal_date: date | None = None) -> PaperTrade:
        trades = self.load()
        trade = PaperTrade(str(signal_date or date.today()), symbol, entry, target, stop)
        trades.append(trade)
        self.save(trades)
        return trade

    def stats(self) -> dict:
        trades = self.load()
        closed = [t for t in trades if t.result in {"win", "loss"}]
        wins = sum(t.result == "win" for t in closed)
        losses = sum(t.result == "loss" for t in closed)
        return {"total": len(trades), "open": sum(t.result == "open" for t in trades),
                "closed": len(closed), "wins": wins, "losses": losses,
                "win_rate": wins / len(closed) if closed else 0.0}
