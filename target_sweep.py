from __future__ import annotations

from dataclasses import dataclass, replace
import pandas as pd
from engine import features, outcome
from config import StrategyConfig

@dataclass(frozen=True)
class TargetStopResult:
    target_pct: float
    stop_pct: float
    horizon: int
    samples: int
    wins: int
    losses: int
    timeouts: int
    win_rate: float
    expected_value: float


def evaluate(df: pd.DataFrame, base: StrategyConfig, target: float, stop: float, horizon: int) -> TargetStopResult:
    cfg = replace(base, target_pct=target, stop_pct=stop, max_hold_days=horizon)
    x = features(df)
    wins = losses = timeouts = 0
    for i in range(len(x) - 1):
        if not bool(x.iloc[i]["signal"]):
            continue
        r = outcome(x, i, cfg)
        if r == "win": wins += 1
        elif r == "loss": losses += 1
        elif r == "timeout": timeouts += 1
    n = wins + losses + timeouts
    p_win = wins / n if n else 0.0
    p_loss = losses / n if n else 0.0
    # Every attempted trade pays costs. A timeout contributes zero price return,
    # so it is neither counted as a win nor silently removed from expectancy.
    ev = p_win * target - p_loss * stop - base.round_trip_cost_pct if n else -base.round_trip_cost_pct
    return TargetStopResult(target, stop, horizon, n, wins, losses, timeouts, p_win, ev)


def sweep(df: pd.DataFrame, base: StrategyConfig,
          targets=(0.01, 0.015, 0.02, 0.025, 0.03),
          stops=(0.005, 0.0075, 0.01, 0.015),
          horizons=(1, 2, 3, 5)) -> pd.DataFrame:
    rows = [evaluate(df, base, t, s, h).__dict__ for t in targets for s in stops for h in horizons]
    return pd.DataFrame(rows).sort_values("expected_value", ascending=False).reset_index(drop=True)
