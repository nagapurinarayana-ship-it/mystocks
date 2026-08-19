from __future__ import annotations

import pandas as pd


def validate_ohlcv(df: pd.DataFrame) -> list[str]:
    errors: list[str] = []
    required = {"Open", "High", "Low", "Close", "Volume"}
    missing = required - set(df.columns)
    if missing:
        return [f"missing columns: {sorted(missing)}"]
    if not df.index.is_monotonic_increasing:
        errors.append("index is not chronological")
    if df.index.has_duplicates:
        errors.append("duplicate dates")
    for col in ["Open", "High", "Low", "Close"]:
        if (df[col] <= 0).any():
            errors.append(f"non-positive {col}")
    if (df["High"] < df[["Open", "Close"]].max(axis=1)).any():
        errors.append("high below open/close")
    if (df["Low"] > df[["Open", "Close"]].min(axis=1)).any():
        errors.append("low above open/close")
    if (df["Volume"] < 0).any():
        errors.append("negative volume")
    return errors
