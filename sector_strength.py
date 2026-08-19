from __future__ import annotations

import pandas as pd


def returns(series: pd.Series, windows=(5, 20, 60)) -> dict[str, float]:
    s = series.dropna()
    out = {}
    for w in windows:
        out[f"ret_{w}d"] = float(s.pct_change(w).iloc[-1]) if len(s) > w else float("nan")
    return out


def relative_strength(stock: pd.Series, sector: pd.Series, window: int = 20) -> float:
    if len(stock) <= window or len(sector) <= window:
        return float("nan")
    return float(stock.pct_change(window).iloc[-1] - sector.pct_change(window).iloc[-1])
