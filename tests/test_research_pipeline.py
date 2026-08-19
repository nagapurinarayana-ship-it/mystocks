from __future__ import annotations

import numpy as np
import pandas as pd

from config import StrategyConfig
from research_policy import history_tier
from target_sweep import sweep


def synthetic_ohlcv(rows: int = 700) -> pd.DataFrame:
    idx = pd.bdate_range("2022-01-03", periods=rows)
    close = pd.Series(100 + np.linspace(0, 25, rows), index=idx)
    return pd.DataFrame({
        "Open": close * 0.999,
        "High": close * 1.01,
        "Low": close * 0.99,
        "Close": close,
        "Volume": 500_000,
    }, index=idx)


def test_history_tiers_include_new_and_insufficient():
    assert history_tier(6).name == "long"
    assert history_tier(4).name == "medium"
    assert history_tier(2).name == "short"
    assert history_tier(0.75).name == "new"
    assert history_tier(0.25).name == "insufficient"


def test_target_sweep_uses_max_hold_days_and_returns_all_horizons():
    result = sweep(synthetic_ohlcv(), StrategyConfig())
    assert not result.empty
    assert set(result["horizon"]) == {1, 2, 3, 5}
    assert set(result["target_pct"]) == {0.01, 0.015, 0.02, 0.025, 0.03}
