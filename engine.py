from __future__ import annotations

import numpy as np
import pandas as pd

from config import StrategyConfig


def features(df: pd.DataFrame) -> pd.DataFrame:
    x = df.copy()
    c, h, l, v = x["Close"], x["High"], x["Low"], x["Volume"]
    x["ret_1"] = c.pct_change()
    x["ret_5"] = c.pct_change(5)
    x["ret_20"] = c.pct_change(20)
    x["sma20"] = c.rolling(20).mean()
    x["sma50"] = c.rolling(50).mean()
    x["sma200"] = c.rolling(200).mean()
    x["atr14"] = pd.concat([(h-l), (h-c.shift()).abs(), (l-c.shift()).abs()], axis=1).max(axis=1).rolling(14).mean()
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
    x["signal"] = x["trend"] & x["momentum"] & (x["vol_ratio"] >= 1.2) & (x["rsi14"].between(50, 72))
    return x.dropna()


def outcome(df: pd.DataFrame, signal_i: int, cfg: StrategyConfig) -> str:
    # Entry is next day's open, so the signal cannot use future information.
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
            return "loss"  # conservative daily-OHLC assumption
        if hit_target:
            return "win"
        if hit_stop:
            return "loss"
    return "timeout"


def historical_stats(df: pd.DataFrame, cfg: StrategyConfig) -> dict:
    x = features(df)
    outcomes = [outcome(x, i, cfg) for i in range(len(x) - 1)]
    outcomes = [o for o in outcomes if o in {"win", "loss", "timeout"}]
    n = len(outcomes)
    wins = outcomes.count("win")
    losses = outcomes.count("loss")
    p_win = wins / n if n else 0.0
    p_loss = losses / n if n else 0.0
    # Timeout is treated as approximately flat before costs for this first model.
    ev = p_win * cfg.target_pct - p_loss * cfg.stop_pct - cfg.round_trip_cost_pct
    return {"samples": n, "wins": wins, "losses": losses, "timeouts": outcomes.count("timeout"),
            "win_probability": p_win, "loss_probability": p_loss, "expected_value": ev}


def current_signal(df: pd.DataFrame) -> dict:
    x = features(df)
    row = x.iloc[-1]
    return {
        "signal": bool(row["signal"]), "close": float(row["Close"]),
        "rsi": float(row["rsi14"]), "vol_ratio": float(row["vol_ratio"]),
        "ret_5": float(row["ret_5"]), "ret_20": float(row["ret_20"]),
        "trend": bool(row["trend"]), "breakout20": bool(row["breakout20"]),
    }


def rank_universe(data: dict[str, pd.DataFrame], cfg: StrategyConfig) -> pd.DataFrame:
    rows = []
    for symbol, raw in data.items():
        if len(raw) < 260:
            continue
        stats = historical_stats(raw, cfg)
        sig = current_signal(raw)
        avg_volume = float(raw["Volume"].tail(20).mean())
        if raw["Close"].iloc[-1] < cfg.min_price or avg_volume < cfg.min_avg_volume:
            continue
        score = (stats["win_probability"] * 100) + (stats["expected_value"] * 1000)
        if sig["signal"]:
            score += 5
        rows.append({"symbol": symbol, **stats, **sig, "avg_volume20": avg_volume, "score": score})
    if not rows:
        return pd.DataFrame()
    out = pd.DataFrame(rows)
    eligible = out[(out["samples"] >= cfg.min_samples) & (out["win_probability"] >= cfg.min_probability) &
                   (out["expected_value"] >= cfg.min_expected_value) & out["signal"]]
    return eligible.sort_values(["score", "win_probability"], ascending=False).head(cfg.top_n).reset_index(drop=True)
