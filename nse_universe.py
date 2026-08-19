from __future__ import annotations

from pathlib import Path
from io import BytesIO
import pandas as pd
import requests

NSE_EQUITY_CSV_URL = "https://nsearchives.nseindia.com/content/equities/EQUITY_L.csv"
NSE_LIST_URL = "https://www.nseindia.com/api/equity-stockIndices?index=NIFTY%20500"


def _headers() -> dict[str, str]:
    return {
        "User-Agent": "Mozilla/5.0 MyStocks research client",
        "Accept": "text/csv,application/json,text/plain,*/*",
        "Referer": "https://www.nseindia.com/",
    }


def discover_current_nse_symbols(timeout: int = 30) -> list[str]:
    """Discover current NSE equity symbols, preferring the official full equity CSV."""
    try:
        with requests.Session() as s:
            s.headers.update(_headers())
            s.get("https://www.nseindia.com/", timeout=timeout)
            r = s.get(NSE_EQUITY_CSV_URL, timeout=timeout)
            r.raise_for_status()
            frame = pd.read_csv(BytesIO(r.content))
        cols = {str(c).strip().upper(): c for c in frame.columns}
        symbol_col = cols.get("SYMBOL")
        series_col = cols.get("SERIES")
        if not symbol_col:
            raise ValueError("Official NSE equity CSV has no SYMBOL column")
        if series_col:
            frame = frame[frame[series_col].astype(str).str.upper().eq("EQ")]
        symbols = sorted({str(x).strip().upper() for x in frame[symbol_col].dropna() if str(x).strip()})
        if len(symbols) < 100:
            raise ValueError(f"Only {len(symbols)} symbols discovered from official CSV")
        return [f"{s}.NS" for s in symbols]
    except Exception as exc:
        print(f"Full NSE equity CSV discovery failed: {exc}; falling back to NIFTY 500")
        with requests.Session() as s:
            s.headers.update(_headers())
            s.get("https://www.nseindia.com/", timeout=timeout)
            r = s.get(NSE_LIST_URL, timeout=timeout)
            r.raise_for_status()
            rows = r.json().get("data", [])
        symbols = sorted({str(x["symbol"]).strip().upper() for x in rows if x.get("symbol")})
        return [f"{s}.NS" for s in symbols]


def save_universe(symbols: list[str], path: str = "data/nse_current_universe.csv") -> None:
    p = Path(path)
    p.parent.mkdir(exist_ok=True)
    pd.DataFrame({"symbol": sorted(set(symbols))}).to_csv(p, index=False)


def load_saved_universe(path: str = "data/nse_current_universe.csv") -> list[str]:
    p = Path(path)
    if not p.exists():
        return []
    return pd.read_csv(p)["symbol"].dropna().astype(str).tolist()
