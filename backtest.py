from __future__ import annotations

import pandas as pd

from config import StrategyConfig
from engine import features, outcome


def walk_forward(df: pd.DataFrame, cfg: StrategyConfig, train_years: int = 3, test_months: int = 6) -> pd.DataFrame:
    x = features(df)
    if x.empty:
        return pd.DataFrame()
    rows = []
    start = x.index.min()
    cursor = start + pd.DateOffset(years=train_years)
    end = x.index.max()
    while cursor < end:
        test_end = min(cursor + pd.DateOffset(months=test_months), end)
        test = x[(x.index >= cursor) & (x.index < test_end)]
        for i in range(len(test) - 1):
            global_i = x.index.get_loc(test.index[i])
            if bool(test.iloc[i]["signal"]):
                rows.append({"date": test.index[i], "outcome": outcome(x, global_i, cfg)})
        cursor = test_end
    result = pd.DataFrame(rows)
    if result.empty:
        return result
    result["win"] = result["outcome"].eq("win")
    return result


def summary(result: pd.DataFrame) -> dict:
    if result.empty:
        return {"samples": 0, "win_rate": 0.0}
    return {"samples": len(result), "win_rate": float(result["win"].mean()),
            "wins": int(result["win"].sum()), "losses": int((result["outcome"] == "loss").sum()),
            "timeouts": int((result["outcome"] == "timeout").sum())}
