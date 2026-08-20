from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import time

import pandas as pd
import yfinance as yf

DATA_DIR = Path('data')
DATA_DIR.mkdir(exist_ok=True)

DOWNLOAD_BATCH_SIZE = 40
DOWNLOAD_RETRIES = 2
DOWNLOAD_RETRY_DELAY_SECONDS = 3


@dataclass(frozen=True)
class ResearchDataConfig:
    years: int = 10
    # Keep even very short histories in the loaded universe. Statistical
    # research applies its own minimum-observation rules later.
    min_rows: int = 1
    refresh: bool = False


def normalise(df: pd.DataFrame) -> pd.DataFrame:
    if isinstance(df.columns, pd.MultiIndex):
        df.columns = [c[0] for c in df.columns]
    cols = {str(c).strip().lower(): c for c in df.columns}
    required = {'open', 'high', 'low', 'close', 'volume'}
    missing = required - set(cols)
    if missing:
        raise ValueError(f'Missing OHLCV columns: {sorted(missing)}')
    out = df.rename(columns={cols[k]: k.title() for k in required})
    out.index = pd.to_datetime(out.index).tz_localize(None)
    return out[['Open', 'High', 'Low', 'Close', 'Volume']].dropna().sort_index()


def _download_batch(symbols: list[str], cfg: ResearchDataConfig) -> dict[str, pd.DataFrame]:
    end = pd.Timestamp.now(tz='Asia/Kolkata').tz_localize(None).normalize() + pd.Timedelta(days=1)
    start = end - pd.DateOffset(years=cfg.years)
    last_error: Exception | None = None
    for attempt in range(1, DOWNLOAD_RETRIES + 1):
        try:
            raw = yf.download(
                symbols, start=start.date().isoformat(), end=end.date().isoformat(),
                auto_adjust=True, progress=False, group_by='ticker', threads=True, timeout=30,
            )
            if raw.empty:
                raise ValueError('No historical data returned for batch')
            if len(symbols) == 1:
                frames = {symbols[0]: raw}
            elif isinstance(raw.columns, pd.MultiIndex):
                frames = {s: raw[s] for s in symbols if s in set(raw.columns.get_level_values(0))}
            else:
                frames = {symbols[0]: raw}
            result: dict[str, pd.DataFrame] = {}
            for symbol, frame in frames.items():
                try:
                    out = normalise(frame)
                    # Do NOT discard short histories. They are part of the
                    # complete universe and are classified by run_research.
                    safe = symbol.replace('^', 'IDX_').replace('.', '_')
                    out.to_csv(DATA_DIR / f'{safe}_{cfg.years}y.csv')
                    result[symbol] = out
                except Exception as exc:
                    print(f'Unable to normalise {symbol}: {exc}')
            return result
        except Exception as exc:
            last_error = exc
            if attempt < DOWNLOAD_RETRIES:
                print(f'Batch download failed ({len(symbols)} symbols), retrying: {exc}')
                time.sleep(DOWNLOAD_RETRY_DELAY_SECONDS * attempt)
    raise RuntimeError(f'Batch download failed after {DOWNLOAD_RETRIES} attempts: {last_error}')


def load_symbol(symbol: str, cfg: ResearchDataConfig) -> pd.DataFrame:
    safe = symbol.replace('^', 'IDX_').replace('.', '_')
    path = DATA_DIR / f'{safe}_{cfg.years}y.csv'
    if path.exists() and not cfg.refresh:
        return normalise(pd.read_csv(path, index_col=0, parse_dates=True))
    result = _download_batch([symbol], cfg)
    return result.get(symbol, pd.DataFrame())


def load_universe(symbols: list[str], cfg: ResearchDataConfig) -> dict[str, pd.DataFrame]:
    """Load every requested symbol without applying a history-quality filter."""
    result: dict[str, pd.DataFrame] = {}
    pending: list[str] = []
    for symbol in symbols:
        safe = symbol.replace('^', 'IDX_').replace('.', '_')
        path = DATA_DIR / f'{safe}_{cfg.years}y.csv'
        if path.exists() and not cfg.refresh:
            try:
                result[symbol] = normalise(pd.read_csv(path, index_col=0, parse_dates=True))
                continue
            except Exception as exc:
                print(f'Cached data invalid for {symbol}; refreshing: {exc}')
        pending.append(symbol)

    total_batches = (len(pending) + DOWNLOAD_BATCH_SIZE - 1) // DOWNLOAD_BATCH_SIZE
    for batch_number, start in enumerate(range(0, len(pending), DOWNLOAD_BATCH_SIZE), start=1):
        batch = pending[start:start + DOWNLOAD_BATCH_SIZE]
        print(f'Downloading research data batch {batch_number}/{total_batches} ({len(batch)} symbols)')
        try:
            result.update(_download_batch(batch, cfg))
        except Exception as exc:
            for symbol in batch:
                print(f'No data for {symbol}: batch download failed: {exc}')
    # Include every requested symbol, even when the provider returned no rows.
    for symbol in symbols:
        result.setdefault(symbol, pd.DataFrame())
    return result
