from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import os
import time

import pandas as pd
import yfinance as yf

DATA_DIR = Path("data")
DATA_DIR.mkdir(exist_ok=True)

@dataclass(frozen=True)
class DataSourceConfig:
    provider: str = "yahoo"
    years: int = 10
    min_rows: int = 1260
    refresh: bool = False


def _normalise(df: pd.DataFrame) -> pd.DataFrame:
    if isinstance(df.columns, pd.MultiIndex):
        df.columns = [c[0] for c in df.columns]
    cols = {str(c).lower(): c for c in df.columns}
    required = {"open", "high", "low", "close", "volume"}
    missing = required - set(cols)
    if missing:
        raise ValueError(f"Missing OHLCV columns: {sorted(missing)}")
    out = df.rename(columns={cols[k]: k.title() for k in required})
    out.index = pd.to_datetime(out.index).tz_localize(None)
    return out[["Open", "High", "Low", "Close", "Volume"]].dropna().sort_index()


def yahoo_history(symbol: str, years: int = 10, refresh: bool = False) -> pd.DataFrame:
    safe = symbol.replace("^", "IDX_").replace(".", "_")
    path = DATA_DIR / f"{safe}_{years}y.csv"
    if path.exists() and not refresh:
        return _normalise(pd.read_csv(path, index_col=0, parse_dates=True))
    end = pd.Timestamp.now(tz="Asia/Kolkata").tz_localize(None).normalize() + pd.Timedelta(days=1)
    start = end - pd.DateOffset(years=years)
    df = yf.download(symbol, start=start.date().isoformat(), end=end.date().isoformat(),
                     auto_adjust=True, progress=False, group_by="column", threads=False)
    if df.empty:
        raise ValueError(f"No historical data returned for {symbol}")
    out = _normalise(df)
    if len(out) < 1260:
        raise ValueError(f"Only {len(out)} rows for {symbol}; minimum 1260 required")
    out.to_csv(path)
    return out


def load_symbol(symbol: str, cfg: DataSourceConfig = DataSourceConfig()) -> pd.DataFrame:
    provider = os.getenv("MYSTOCKS_DATA_PROVIDER", cfg.provider).lower()
    if provider == "yahoo":
        return yahoo_history(symbol, cfg.years, cfg.refresh)
    if provider == "upstox":
        raise NotImplementedError("Upstox adapter is intentionally explicit: configure credentials and instrument keys before enabling it.")
    raise ValueError(f"Unsupported data provider: {provider}")


def load_universe(symbols: list[str], cfg: DataSourceConfig = DataSourceConfig()) -> dict[str, pd.DataFrame]:
    result: dict[str, pd.DataFrame] = {}
    for symbol in symbols:
        try:
            result[symbol] = load_symbol(symbol, cfg)
            time.sleep(0.15)
        except Exception as exc:
            print(f"Skipping {symbol}: {exc}")
    return result
