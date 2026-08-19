import pandas as pd

from config import StrategyConfig
from engine import outcome


def frame(rows):
    idx = pd.date_range("2025-01-01", periods=len(rows), freq="D")
    return pd.DataFrame(rows, index=idx)


def test_target_before_stop():
    df = frame([
        {"Open": 100, "High": 100, "Low": 100, "Close": 100, "Volume": 1000},
        {"Open": 100, "High": 103, "Low": 99, "Close": 102, "Volume": 1000},
    ])
    assert outcome(df, 0, StrategyConfig(target_pct=.02, stop_pct=.01, max_hold_days=1)) == "win"


def test_stop_before_target_is_conservative():
    df = frame([
        {"Open": 100, "High": 100, "Low": 100, "Close": 100, "Volume": 1000},
        {"Open": 100, "High": 103, "Low": 98, "Close": 101, "Volume": 1000},
    ])
    assert outcome(df, 0, StrategyConfig(target_pct=.02, stop_pct=.01, max_hold_days=1)) == "loss"
