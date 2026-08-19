from __future__ import annotations

import math
import numpy as np
import pandas as pd

from config import StrategyConfig


def features(df: pd.DataFrame) -> pd.DataFrame:
    x = df.copy().sort_index()
    c, h, l, v = x["Close"], x["High"], x["Low"], x["Volume"]
    x["ret_1"] = c.pct_change()
    x["ret_5"] = c.pct_change(5)
    x["ret_20"] = c.pct_change(20)
    x["sma20"] = c.rolling(20).mean()
    x["sma50"] = c.rolling(50).mean()
    x["sma200"] = c.rolling(200).mean()
    tr = pd.concat([(h - l), (h - c.shift()).abs(), (l - c.shift()).abs()], axis=1).max(axis=1)
    x["atr14"] = tr.rolling(14).mean()
    delta = c.diff()
    gain = delta.clip(lower=0).rolling(14).mean()
    loss = (-delta.clip(upper=0)).rolling(14).mean()
    rs = gain / loss.replace(0, np.nan)
    x["rsi14"] = 100 - (100 / (1 + rs))
    x["vol_ratio"] = v / v.rolling(20).mean()
    x["high20"] = h.shift(1).rolling(20).max()
    x["low20"] = l.shift(1).rolling(20).min()
    x["trend"] = (c > x["sma20"]) & (x["sma20"] > x["sma50"])
    x["breakout20"] = c > x["high20"]
    x["momentum"] = (x["ret_5"] > 0) & (x["ret_20"] > 0)
    x["signal"] = x["trend"] & x["momentum"] & (x["vol_ratio"] >= 1.2) & x["rsi14"].between(50, 72)
    return x.dropna()


def outcome(df: pd.DataFrame, signal_i: int, cfg: StrategyConfig) -> str:
    if signal_i + 1 >= len(df):
        return "no_data"
    entry = float(df.iloc[signal_i + 1]["Open"])
    target = entry * (1 + cfg.target_pct)
    stop = entry * (1 - cfg.stop_pct)
    end = min(signal_i + 1 + cfg.max_hold_days, len(df) - 1)
    for j in range(signal_i + 1, end + 1):
        row = df.iloc[j]
        hit_target = float(row["High"]) >= target
        hit_stop = float(row["Low"]) <= stop
        if hit_target and hit_stop:
            return "loss"
        if hit_target:
            return "win"
        if hit_stop:
            return "loss"
    return "timeout"


def _wilson_lower(wins: int, n: int, z: float = 1.96) -> float:
    if n <= 0:
        return 0.0
    p = wins / n
    denom = 1 + z * z / n
    centre = p + z * z / (2 * n)
    spread = z * math.sqrt((p * (1 - p) + z * z / (4 * n)) / n)
    return (centre - spread) / denom


def historical_stats(df: pd.DataFrame, cfg: StrategyConfig) -> dict:
    """Evaluate only historical rows where the exact signal was present."""
    x = features(df)
    outcomes = []
    for i in range(len(x) - 1):
        if bool(x.iloc[i]["signal"]):
            o = outcome(x, i, cfg)
            if o in {"win", "loss", "timeout"}:
                outcomes.append(o)
    n = len(outcomes)
    wins = outcomes.count("win")
    losses = outcomes.count("loss")
    timeouts = outcomes.count("timeout")
    p_win = wins / n if n else 0.0
    p_loss = losses / n if n else 0.0
    ev = p_win * cfg.target_pct - p_loss * cfg.stop_pct - cfg.round_trip_cost_pct
    return {
        "samples": n, "wins": wins, "losses": losses, "timeouts": timeouts,
        "win_probability": p_win, "loss_probability": p_loss,
        "timeout_probability": timeouts / n if n else 0.0,
        "win_probability_lower95": _wilson_lower(wins, n),
        "expected_value": ev,
    }


def current_signal(df: pd.DataFrame) -> dict:
    x = features(df)
    if x.empty:
        return {"signal": False}
    row = x.iloc[-1]
    return {
        "signal": bool(row["signal"]), "close": float(row["Close"]),
        "rsi": float(row["rsi14"]), "vol_ratio": float(row["vol_ratio"]),
        "ret_5": float(row["ret_5"]), "ret_20": float(row["ret_20"]),
        "trend": bool(row["trend"]), "breakout20": bool(row["breakout20"]),
        "atr_pct": float(row["atr14"] / row["Close"]),
    }


def rank_universe(data: dict[str, pd.DataFrame], cfg: StrategyConfig) -> pd.DataFrame:
    rows = []
    for symbol, raw in data.items():
        if len(raw) < cfg.min_history_rows:
            continue
        stats = historical_stats(raw, cfg)
        sig = current_signal(raw)
        if not sig.get("signal", False):
            continue
        avg_volume = float(raw["Volume"].tail(20).mean())
        last_close = float(raw["Close"].iloc[-1])
        if last_close < cfg.min_price or avg_volume < cfg.min_avg_volume:
            continue
        score = (
            100 * stats["win_probability_lower95"]
            + 500 * max(stats["expected_value"], 0)
            + 3 * min(sig.get("vol_ratio", 0), 3)
            + (2 if sig.get("breakout20") else 0)
        )
        rows.append({"symbol": symbol, **stats, **sig, "avg_volume20": avg_volume, "score": score})
    if not rows:
        return pd.DataFrame()
    out = pd.DataFrame(rows)
    eligible = out[
        (out["samples"] >= cfg.min_samples)
        & (out["win_probability_lower95"] >= cfg.min_probability_lower95)
        & (out["expected_value"] >= cfg.min_expected_value)
    ]
    return eligible.sort_values(["score", "win_probability_lower95", "samples"], ascending=False).head(cfg.top_n).reset_index(drop=True)
