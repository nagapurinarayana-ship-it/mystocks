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
from intraday.ledger import PaperLedger  # noqa: E402

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

        with PaperLedger("data/mystocks_intraday.sqlite3") as ledger:
            now_iso = datetime.now(timezone.utc).isoformat()
            ledger.record_event(now_iso, "INFO", "scanner_starting", "Intraday live scanner starting")

            def handle_tick(tick) -> None:
                now = datetime.now(timezone.utc)
                if not scanner.on_tick(tick, now=now):
                    return
                candidates = scanner.opportunities(now=now)
                for item in candidates:
                    inserted = ledger.record_signal(item)
                    if inserted:
                        logging.info(
                            "RADAR %s strategy=%s entry~%.2f stop=%.2f target=%.2f volume=%.2fx",
                            item.symbol, item.strategy_id, item.entry_reference,
                            item.stop_price, item.target_price, item.volume_ratio,
                        )
                        ledger.record_event(
                            item.generated_at.isoformat(), "INFO", "signal_discovered",
                            f"{item.strategy_id} candidate for {item.symbol}; no broker order sent",
                        )

            client = UpstoxV3MarketDataClient(
                [item.instrument_key for item in instruments],
                on_tick=handle_tick,
                symbol_by_key={item.instrument_key: item.symbol for item in instruments},
            )
            client.connect()
            try:
                previous_state = None
                while True:
                    now = datetime.now(timezone.utc)
                    if not client.connected:
                        state = "disconnected"
                    elif not scanner.feed_is_fresh(now=now):
                        state = "stale"
                    else:
                        state = "healthy"
                    if state != previous_state:
                        logging.warning("Market feed state: %s", state)
                        ledger.record_event(
                            now.isoformat(), "WARNING" if state != "healthy" else "INFO",
                            f"feed_{state}", client.last_error or f"Market feed state changed to {state}",
                        )
                        previous_state = state
                    time.sleep(2)
            except KeyboardInterrupt:
                logging.info("Stopping market-data radar")
                ledger.record_event(datetime.now(timezone.utc).isoformat(), "INFO",
                                    "scanner_stopped", "Scanner stopped by operator")
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
