from __future__ import annotations

import pandas as pd
from config import StrategyConfig
from target_sweep import sweep


def expanding_windows(df: pd.DataFrame, train_days: int = 756, test_days: int = 126, step_days: int = 126):
    """Yield chronological train/test windows; never shuffle time-series observations."""
    start = 0
    while start + train_days + test_days <= len(df):
        train = df.iloc[start:start + train_days]
        test = df.iloc[start + train_days:start + train_days + test_days]
        yield train, test
        start += step_days


def select_on_train(df: pd.DataFrame, cfg: StrategyConfig) -> dict:
    result = sweep(df, cfg)
    if result.empty:
        return {}
    # Select only among sufficiently sampled configurations.
    eligible = result[result["samples"] >= 30]
    return eligible.iloc[0].to_dict() if not eligible.empty else {}
