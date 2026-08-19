from __future__ import annotations

import pandas as pd


def buy_and_hold_return(close: pd.Series) -> float:
    c = close.dropna()
    if len(c) < 2:
        return float("nan")
    return float(c.iloc[-1] / c.iloc[0] - 1)


def random_signal_hit_rate(df: pd.DataFrame, target: float = 0.02, stop: float = 0.01, horizon: int = 3) -> float:
    """Simple unconditional benchmark: measure target-before-stop from sampled sessions.

    This is not a trading strategy. It provides a baseline for whether signal
    selection materially improves on unconditional short-horizon movement.
    """
    if len(df) <= horizon:
        return float("nan")
    wins = losses = 0
    for i in range(len(df) - horizon):
        entry = float(df.iloc[i + 1]["Open"])
        if entry <= 0:
            continue
        hit = None
        for j in range(i + 1, i + horizon + 1):
            high = float(df.iloc[j]["High"])
            low = float(df.iloc[j]["Low"])
            if high >= entry * (1 + target) and low <= entry * (1 - stop):
                hit = "loss"  # conservative ambiguity
                break
            if high >= entry * (1 + target):
                hit = "win"
                break
            if low <= entry * (1 - stop):
                hit = "loss"
                break
        if hit == "win": wins += 1
        elif hit == "loss": losses += 1
    return wins / (wins + losses) if wins + losses else float("nan")
