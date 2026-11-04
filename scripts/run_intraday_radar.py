"""Run the live Upstox market-data radar locally.

Set UPSTOX_ACCESS_TOKEN in the process environment before running. Tokens are
short-lived and must be obtained through Upstox's official OAuth process.
This runner scans and prints paper/research candidates only; it cannot place
broker orders.
"""

from __future__ import annotations

import gzip
import json
import logging
import os
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import requests

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from intraday.market_data.instruments import (  # noqa: E402
    parse_upstox_instrument_payload,
    reconcile_nse_cash_equities,
)
from intraday.market_data.upstox_v3 import (  # noqa: E402
    UpstoxV3MarketDataClient,
)
from intraday.scanner import IntradayScanner  # noqa: E402

INSTRUMENTS_URL = "https://assets.upstox.com/market-quote/instruments/exchange/NSE.json.gz"


def load_instruments() -> tuple:
    response = requests.get(INSTRUMENTS_URL, timeout=(5, 30))
    response.raise_for_status()
    raw = gzip.decompress(response.content)
    payload: Any = json.loads(raw.decode("utf-8"))
    rows = parse_upstox_instrument_payload(payload)
    reconciliation = reconcile_nse_cash_equities(rows)
    if not reconciliation.eligible:
        raise RuntimeError("instrument master contains no eligible NSE cash equities")
    logging.info(
        "Instrument master: %d rows, %d eligible, %d excluded",
        reconciliation.source_rows,
        len(reconciliation.eligible),
        len(reconciliation.excluded),
    )
    Path("data").mkdir(exist_ok=True)
    exclusion_path = Path("data/intraday-universe-exclusions.json")
    exclusion_path.write_text(
        json.dumps(reconciliation.excluded, indent=2), encoding="utf-8"
    )
    return reconciliation.eligible


def main() -> int:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(message)s",
    )
    if not os.getenv("UPSTOX_ACCESS_TOKEN"):
        logging.error("Set UPSTOX_ACCESS_TOKEN in your shell; no credentials are stored in Git.")
        return 2

    try:
        instruments = load_instruments()
        scanner = IntradayScanner(instruments, max_opportunities=3)
        logging.info("Starting live LTPC subscription for %d NSE cash equities", len(instruments))

        def handle_tick(tick) -> None:
            now = datetime.now(timezone.utc)
            if not scanner.on_tick(tick, now=now):
                return
            candidates = scanner.opportunities(now=now)
            if candidates:
                logging.info(
                    "RADAR %s",
                    " | ".join(
                        f"{item.symbol} {item.strategy_id} entry~{item.entry_reference:.2f} "
                        f"stop={item.stop_price:.2f} target={item.target_price:.2f}"
                        for item in candidates
                    ),
                )

        client = UpstoxV3MarketDataClient(
            [item.instrument_key for item in instruments],
            on_tick=handle_tick,
            symbol_by_key={item.instrument_key: item.symbol for item in instruments},
        )
        client.connect()
        try:
            while True:
                if not client.connected:
                    logging.warning("Feed disconnected/degraded; suppressing trade decisions")
                time.sleep(2)
        except KeyboardInterrupt:
            logging.info("Stopping market-data radar")
        finally:
            client.disconnect()
    except requests.RequestException as exc:
        logging.exception("Could not download Upstox instrument master: %s", exc)
        return 3
    except Exception as exc:
        logging.exception("Intraday radar stopped safely: %s", exc)
        return 4
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
