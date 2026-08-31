import pandas as pd

from config import StrategyConfig
from engine import outcome


def frame(rows):
    idx = pd.date_range("2025-01-01", periods=len(rows), freq="D")
    return pd.DataFrame(rows, index=idx)


def test_same_candle_target_and_stop_is_conservative_loss():
    df = frame([
        {"Open": 100, "High": 100, "Low": 100, "Close": 100, "Volume": 1000},
        {"Open": 100, "High": 103, "Low": 99, "Close": 102, "Volume": 1000},
    ])
    # Daily OHLC cannot reveal whether +2% target or -1% stop happened first.
    # The research engine deliberately scores this ambiguous case as a loss.
    assert outcome(df, 0, StrategyConfig(target_pct=.02, stop_pct=.01, max_hold_days=1)) == "loss"


def test_stop_and_target_hit_same_candle_is_conservative_loss():
    df = frame([
        {"Open": 100, "High": 100, "Low": 100, "Close": 100, "Volume": 1000},
        {"Open": 100, "High": 103, "Low": 98, "Close": 101, "Volume": 1000},
    ])
    assert outcome(df, 0, StrategyConfig(target_pct=.02, stop_pct=.01, max_hold_days=1)) == "loss"
