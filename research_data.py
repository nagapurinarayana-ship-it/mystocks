from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import pandas as pd
import yfinance as yf

DATA_DIR = Path('data')
DATA_DIR.mkdir(exist_ok=True)

@dataclass(frozen=True)
class ResearchDataConfig:
    years: int = 10
    min_rows: int = 20
    refresh: bool = False


def normalise(df: pd.DataFrame) -> pd.DataFrame:
    if isinstance(df.columns, pd.MultiIndex):
        df.columns = [c[0] for c in df.columns]
    cols = {str(c).strip().lower(): c for c in df.columns}
    required = {'open','high','low','close','volume'}
    missing = required - set(cols)
    if missing:
        raise ValueError(f'Missing OHLCV columns: {sorted(missing)}')
    out = df.rename(columns={cols[k]: k.title() for k in required})
    out.index = pd.to_datetime(out.index).tz_localize(None)
    return out[['Open','High','Low','Close','Volume']].dropna().sort_index()


def load_symbol(symbol: str, cfg: ResearchDataConfig) -> pd.DataFrame:
    safe = symbol.replace('^','IDX_').replace('.','_')
    path = DATA_DIR / f'{safe}_{cfg.years}y.csv'
    if path.exists() and not cfg.refresh:
        return normalise(pd.read_csv(path, index_col=0, parse_dates=True))
    end = pd.Timestamp.now(tz='Asia/Kolkata').tz_localize(None).normalize() + pd.Timedelta(days=1)
    start = end - pd.DateOffset(years=cfg.years)
    df = yf.download(symbol, start=start.date().isoformat(), end=end.date().isoformat(),
                     auto_adjust=True, progress=False, group_by='column', threads=False)
    if df.empty:
        raise ValueError(f'No historical data returned for {symbol}')
    out = normalise(df)
    if len(out) < cfg.min_rows:
        raise ValueError(f'Only {len(out)} rows for {symbol}; minimum {cfg.min_rows} required')
    out.to_csv(path)
    return out


def load_universe(symbols: list[str], cfg: ResearchDataConfig) -> dict[str,pd.DataFrame]:
    result = {}
    for symbol in symbols:
        try:
            result[symbol] = load_symbol(symbol, cfg)
        except Exception as exc:
            print(f'Skipping {symbol}: {exc}')
    return result
