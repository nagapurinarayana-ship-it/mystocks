from __future__ import annotations

import pandas as pd
from engine import features, outcome
from config import StrategyConfig


def rolling_report(df: pd.DataFrame, cfg: StrategyConfig, train_years: int = 3, test_months: int = 6) -> pd.DataFrame:
    """Generate strictly chronological out-of-sample windows.

    The training period is currently used only to define the walk-forward clock;
    signal parameters remain fixed. This keeps the report honest while providing
    a framework for later model selection inside each training window.
    """
    x = features(df)
    if x.empty:
        return pd.DataFrame()
    rows = []
    cursor = x.index.min() + pd.DateOffset(years=train_years)
    end = x.index.max()
    while cursor < end:
        test_end = min(cursor + pd.DateOffset(months=test_months), end)
        test = x[(x.index >= cursor) & (x.index < test_end)]
        for idx in test.index:
            i = x.index.get_loc(idx)
            if not bool(x.iloc[i]["signal"]):
                continue
            result = outcome(x, i, cfg)
            if result in {"win", "loss", "timeout"}:
                rows.append({"date": idx, "outcome": result, "test_window": f"{cursor.date()}:{test_end.date()}"})
        cursor = test_end
    return pd.DataFrame(rows)


def summarize(result: pd.DataFrame, cfg: StrategyConfig) -> dict:
    if result.empty:
        return {"samples": 0, "wins": 0, "losses": 0, "timeouts": 0, "win_rate": 0.0, "expected_value": 0.0}
    wins = int((result.outcome == "win").sum())
    losses = int((result.outcome == "loss").sum())
    timeouts = int((result.outcome == "timeout").sum())
    n = len(result)
    p_win, p_loss = wins / n, losses / n
    ev = p_win * cfg.target_pct - p_loss * cfg.stop_pct - cfg.round_trip_cost_pct
    return {"samples": n, "wins": wins, "losses": losses, "timeouts": timeouts,
            "win_rate": p_win, "expected_value": ev}
