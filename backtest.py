from __future__ import annotations

import math
import pandas as pd

from config import StrategyConfig
from engine import features, outcome


def walk_forward(df: pd.DataFrame, cfg: StrategyConfig, train_years: int = 3, test_months: int = 6) -> pd.DataFrame:
    x = features(df)
    if x.empty:
        return pd.DataFrame()
    rows = []
    cursor = x.index.min() + pd.DateOffset(years=train_years)
    end = x.index.max()
    while cursor < end:
        test_end = min(cursor + pd.DateOffset(months=test_months), end)
        test = x[(x.index >= cursor) & (x.index < test_end)]
        for i in range(len(test)):
            global_i = x.index.get_loc(test.index[i])
            if bool(test.iloc[i]["signal"]):
                o = outcome(x, global_i, cfg)
                if o in {"win", "loss", "timeout"}:
                    rows.append({"date": test.index[i], "outcome": o})
        cursor = test_end
    result = pd.DataFrame(rows)
    if result.empty:
        return result
    result["win"] = result["outcome"].eq("win")
    result["loss"] = result["outcome"].eq("loss")
    return result


def summary(result: pd.DataFrame, cfg: StrategyConfig | None = None) -> dict:
    if result.empty:
        return {"samples": 0, "win_rate": 0.0, "expected_value": 0.0}
    n = len(result)
    wins = int(result["win"].sum())
    losses = int(result["loss"].sum())
    timeouts = int((result["outcome"] == "timeout").sum())
    win_rate = wins / n
    loss_rate = losses / n
    ev = None
    if cfg is not None:
        ev = win_rate * cfg.target_pct - loss_rate * cfg.stop_pct - cfg.round_trip_cost_pct
    se = math.sqrt(max(win_rate * (1 - win_rate) / n, 0))
    return {
        "samples": n,
        "win_rate": win_rate,
        "win_rate_lower95_normal": max(0.0, win_rate - 1.96 * se),
        "win_rate_upper95_normal": min(1.0, win_rate + 1.96 * se),
        "wins": wins,
        "losses": losses,
        "timeouts": timeouts,
        "expected_value": ev,
    }
