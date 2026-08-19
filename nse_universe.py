from __future__ import annotations

from io import BytesIO
from pathlib import Path
import zipfile
import pandas as pd
import requests

NSE_EQUITY_URL = "https://www.nseindia.com/api/master-quote"
NSE_LIST_URL = "https://www.nseindia.com/api/equity-stockIndices?index=NIFTY%20500"

# NSE's public reports page currently exposes a downloadable "Securities available
# for Equity segment" CSV. The exact download URL is intentionally configurable,
# because NSE periodically changes its report endpoints.
DEFAULT_EQUITY_CSV_URL = "https://www.nseindia.com/api/equity-stockIndices?index=NIFTY%20500"


def discover_current_nse_symbols(timeout: int = 30) -> list[str]:
    headers = {
        "User-Agent": "Mozilla/5.0 MyStocks research client",
        "Accept": "application/json,text/plain,*/*",
        "Referer": "https://www.nseindia.com/",
    }
    with requests.Session() as s:
        s.headers.update(headers)
        s.get("https://www.nseindia.com/", timeout=timeout)
        r = s.get(NSE_LIST_URL, timeout=timeout)
        r.raise_for_status()
        data = r.json()
    rows = data.get("data", [])
    symbols = sorted({str(x["symbol"]).strip() for x in rows if x.get("symbol")})
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
