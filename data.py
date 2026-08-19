from __future__ import annotations

from datetime import date, timedelta
from pathlib import Path

import pandas as pd
import yfinance as yf

DATA_DIR = Path("data")
DATA_DIR.mkdir(exist_ok=True)


def download_history(symbol: str, years: int = 10, refresh: bool = False) -> pd.DataFrame:
    safe = symbol.replace("^", "IDX_").replace(".", "_")
    path = DATA_DIR / f"{safe}_{years}y.csv"
    if path.exists() and not refresh:
        df = pd.read_csv(path, index_col=0, parse_dates=True)
        return _normalise(df)

    start = date.today() - timedelta(days=365 * years + 30)
    df = yf.download(symbol, start=start.isoformat(), end=(date.today() + timedelta(days=1)).isoformat(),
                     auto_adjust=True, progress=False, group_by="column")
    if df.empty:
        raise ValueError(f"No historical data returned for {symbol}")
    df = _normalise(df)
    df.to_csv(path)
    return df


def _normalise(df: pd.DataFrame) -> pd.DataFrame:
    if isinstance(df.columns, pd.MultiIndex):
        df.columns = [c[0] for c in df.columns]
    cols = {c.lower(): c for c in df.columns}
    required = {"open", "high", "low", "close", "volume"}
    if not required.issubset(cols):
        raise ValueError(f"Missing OHLCV columns: {required - set(cols)}")
    out = df.rename(columns={cols[k]: k.title() for k in required})
    out.index = pd.to_datetime(out.index).tz_localize(None)
    return out[["Open", "High", "Low", "Close", "Volume"]].dropna()


def download_universe(symbols: list[str], years: int = 10, refresh: bool = False) -> dict[str, pd.DataFrame]:
    result: dict[str, pd.DataFrame] = {}
    for symbol in symbols:
        try:
            result[symbol] = download_history(symbol, years=years, refresh=refresh)
        except Exception as exc:
            print(f"Skipping {symbol}: {exc}")
    return result
