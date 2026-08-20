from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import time

import pandas as pd
import yfinance as yf

DATA_DIR = Path('data')
DATA_DIR.mkdir(exist_ok=True)

# Yahoo/yfinance can rate-limit large bursts, while one request per symbol is
# far too slow for the full NSE universe. Keep batches modest and let
# yfinance parallelise requests within each batch.
DOWNLOAD_BATCH_SIZE = 40
DOWNLOAD_RETRIES = 2
DOWNLOAD_RETRY_DELAY_SECONDS = 3


@dataclass(frozen=True)
class ResearchDataConfig:
    years: int = 10
    min_rows: int = 20
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
    """Download a batch and split yfinance's multi-ticker result by symbol."""
    end = pd.Timestamp.now(tz='Asia/Kolkata').tz_localize(None).normalize() + pd.Timedelta(days=1)
    start = end - pd.DateOffset(years=cfg.years)

    last_error: Exception | None = None
    for attempt in range(1, DOWNLOAD_RETRIES + 1):
        try:
            raw = yf.download(
                symbols,
                start=start.date().isoformat(),
                end=end.date().isoformat(),
                auto_adjust=True,
                progress=False,
                group_by='ticker',
                threads=True,
                timeout=30,
            )
            if raw.empty:
                raise ValueError('No historical data returned for batch')

            result: dict[str, pd.DataFrame] = {}
            if len(symbols) == 1:
                frames = {symbols[0]: raw}
            elif isinstance(raw.columns, pd.MultiIndex):
                frames = {}
                available = set(raw.columns.get_level_values(0))
                for symbol in symbols:
                    if symbol in available:
                        frames[symbol] = raw[symbol]
            else:
                # Defensive fallback for a provider response that collapses
                # the column index unexpectedly.
                frames = {symbols[0]: raw}

            for symbol, frame in frames.items():
                try:
                    out = normalise(frame)
                    if len(out) < cfg.min_rows:
                        print(f'Skipping {symbol}: Only {len(out)} rows for {symbol}; minimum {cfg.min_rows} required')
                        continue
                    safe = symbol.replace('^', 'IDX_').replace('.', '_')
                    out.to_csv(DATA_DIR / f'{safe}_{cfg.years}y.csv')
                    result[symbol] = out
                except Exception as exc:
                    print(f'Skipping {symbol}: {exc}')
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
    if symbol not in result:
        raise ValueError(f'No usable historical data returned for {symbol}')
    return result[symbol]


def load_universe(symbols: list[str], cfg: ResearchDataConfig) -> dict[str, pd.DataFrame]:
    """Load the universe efficiently, using cached files when possible.

    Refresh mode still refreshes every requested symbol, but downloads them in
    batches instead of making a separate network request for every ticker.
    This is critical for the 2,000+ symbol NSE universe and avoids hitting the
    GitHub-hosted runner's six-hour job limit.
    """
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
            # Do not fall back to 40 individual downloads: that recreates the
            # original six-hour failure mode. A failed batch is safely skipped
            # and can be retried on the next scheduled run.
            for symbol in batch:
                print(f'Skipping {symbol}: batch download failed: {exc}')

    return result
