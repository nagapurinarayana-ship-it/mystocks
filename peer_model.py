from __future__ import annotations

import pandas as pd


def relative_strength(stock: pd.Series, benchmark: pd.Series, window: int = 20) -> float:
    s = stock.dropna().pct_change(window).iloc[-1]
    b = benchmark.dropna().pct_change(window).iloc[-1]
    return float(s - b)


def peer_similarity(features: pd.DataFrame, current: pd.Series, columns: list[str], k: int = 25) -> pd.Series:
    """Simple historical nearest-neighbour distribution for emerging stocks.

    This is deliberately a research primitive, not a production model. It uses
    only rows supplied by the caller, so callers must provide a point-in-time
    training set and never include the current/future observation.
    """
    x = features[columns].dropna().copy()
    if x.empty:
        return pd.Series(dtype=float)
    z = (x - x.mean()) / x.std(ddof=0).replace(0, 1)
    q = ((current[columns] - x.mean()) / x.std(ddof=0).replace(0, 1)).fillna(0)
    dist = ((z - q) ** 2).sum(axis=1).sort_values().head(k)
    return dist
