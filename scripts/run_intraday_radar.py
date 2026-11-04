"""Run the live Upstox LTPC scanner and REST-depth validated paper pipeline.

Set UPSTOX_ACCESS_TOKEN in the process environment before running. This runner
uses an LTPC-only WebSocket for broad discovery and the Full Market Quotes V3
REST endpoint for the maximum-three candidate shortlist. No broker order
placement methods are used or available here.
"""

from __future__ import annotations

import gzip
import json
import logging
import os
import sys
import time
from datetime import datetime, time as clock_time, timezone
from zoneinfo import ZoneInfo
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
from intraday.market_data.upstox_v3 import UpstoxV3MarketDataClient  # noqa: E402
from intraday.market_data.quotes_v3 import (  # noqa: E402
    MarketQuoteError,
    UpstoxFullMarketQuotesV3Client,
)
from intraday.scanner import IntradayScanner  # noqa: E402
from intraday.ledger import PaperLedger  # noqa: E402
from intraday.execution.paper import FeeSchedule, PaperExecutionEngine  # noqa: E402
from intraday.coordinator import AutonomousPaperCoordinator  # noqa: E402
from intraday.execution.configuration import load_fee_schedule_from_environment  # noqa: E402

INSTRUMENTS_URL = "https://assets.upstox.com/market-quote/instruments/exchange/NSE.json.gz"
IST = ZoneInfo("Asia/Kolkata")
LTPC_INDIVIDUAL_LIMIT = 5000
QUOTE_REFRESH_SECONDS = 5.0


def load_optional_fee_schedule() -> FeeSchedule | None:
    """Return only a complete, explicit tariff for the selected broker."""
    return load_fee_schedule_from_environment()


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
        "Broker NSE instrument master: %d rows, %d eligible EQ instruments, %d excluded",
        reconciliation.source_rows,
        len(reconciliation.eligible),
        len(reconciliation.excluded),
    )
    if len(reconciliation.eligible) > LTPC_INDIVIDUAL_LIMIT:
        raise RuntimeError(
            f"Eligible instrument count {len(reconciliation.eligible)} exceeds the "
            f"Upstox LTPC-only limit of {LTPC_INDIVIDUAL_LIMIT}; refusing to silently omit symbols"
        )
    Path("data").mkdir(exist_ok=True)
    Path("data/intraday-universe-exclusions.json").write_text(
        json.dumps(reconciliation.excluded, indent=2), encoding="utf-8"
    )
    Path("data/intraday-universe-summary.json").write_text(
        json.dumps(
            {
                "source": "Upstox NSE BOD instrument master",
                "source_rows": reconciliation.source_rows,
                "eligible_rows": len(reconciliation.eligible),
                "excluded_rows": len(reconciliation.excluded),
                "accounted_rows": reconciliation.accounted_rows,
                "coverage_complete": reconciliation.accounted_rows == reconciliation.source_rows,
                "ltpc_subscription_limit": LTPC_INDIVIDUAL_LIMIT,
                "subscription_mode": "LTPC-only WebSocket plus REST depth for shortlist",
                "observed_at": datetime.now(timezone.utc).isoformat(),
            },
            indent=2,
        ),
        encoding="utf-8",
    )
    return reconciliation.eligible


def _market_state(client: UpstoxV3MarketDataClient, scanner: IntradayScanner, now: datetime) -> str:
    local_now = now.astimezone(IST)
    market_open = (
        local_now.weekday() < 5
        and (local_now.hour, local_now.minute) >= (9, 15)
        and (local_now.hour, local_now.minute) < (15, 30)
    )
    if not client.connected:
        return "disconnected"
    if not market_open:
        return "market_closed"
    if not scanner.feed_is_fresh(now=now):
        return "stale"
    return "healthy"


def main() -> int:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(message)s",
    )
    access_token = os.getenv("UPSTOX_ACCESS_TOKEN", "")
    if not access_token.strip():
        logging.error("Set UPSTOX_ACCESS_TOKEN through the official OAuth process; no token is stored in Git.")
        return 2

    try:
        instruments = load_instruments()
        scanner = IntradayScanner(instruments, max_opportunities=3)
        logging.info(
            "Starting LTPC-only live subscription for all %d eligible NSE cash equities",
            len(instruments),
        )

        fee_schedule = load_optional_fee_schedule()
        if fee_schedule is None:
            logging.warning(
                "Paper fills disabled: configure all broker-specific MYSTOCKS_PAPER_FEE_* values "
                "from the selected broker tariff. Live scanning and shortlist quote snapshots remain active."
            )

        quotes_client = UpstoxFullMarketQuotesV3Client(access_token=access_token)

        with PaperLedger("data/mystocks_intraday.sqlite3") as ledger:
            saved_paper_state = ledger.load_paper_state()
            paper_engine = PaperExecutionEngine(fee_schedule) if fee_schedule is not None else None
            paper_coordinator = None

            if paper_engine is not None:
                if saved_paper_state is not None:
                    # If the snapshot is corrupt or the tariff changed, stop safely:
                    # never silently reset the paper account to ₹1,000.
                    paper_engine.restore_state(saved_paper_state)
                    ledger.record_event(
                        datetime.now(timezone.utc).isoformat(), "INFO",
                        "paper_state_restored",
                        "Saved paper cash, daily risk and open/pending state restored",
                    )
                else:
                    ledger.save_paper_state(
                        paper_engine.export_state(),
                        datetime.now(timezone.utc).isoformat(),
                    )
                    ledger.record_event(
                        datetime.now(timezone.utc).isoformat(), "INFO",
                        "paper_state_initialised",
                        "Initial ₹1,000 paper account state saved",
                    )
                paper_coordinator = AutonomousPaperCoordinator(scanner, paper_engine, ledger)
                ledger.record_event(
                    datetime.now(timezone.utc).isoformat(), "INFO",
                    "paper_engine_enabled",
                    "Autonomous paper simulation enabled with explicit broker tariff; live orders remain disabled",
                )
            elif saved_paper_state is not None:
                ledger.record_event(
                    datetime.now(timezone.utc).isoformat(), "WARNING",
                    "paper_state_not_loaded",
                    "A saved paper account exists, but paper execution is disabled until the complete matching fee schedule is configured",
                )

            ledger.record_event(
                datetime.now(timezone.utc).isoformat(), "INFO",
                "scanner_starting",
                "Intraday scanner starting with LTPC-only WebSocket and REST shortlist depth",
            )

            def handle_tick(tick) -> None:
                now = datetime.now(timezone.utc)
                if paper_coordinator is not None:
                    update = paper_coordinator.on_tick(tick, now=now)
                    if not update.accepted_tick:
                        return
                    for event in update.paper_events:
                        logging.info("PAPER %s %s", event.event_type, event.message)
                else:
                    if not scanner.on_tick(tick, now=now):
                        return
                    scanner.opportunities(now=now)

                for item in scanner.candidate_signals(now=now):
                    inserted = ledger.record_signal(item)
                    if inserted:
                        logging.info(
                            "RADAR %s strategy=%s entry~%.2f stop=%.2f target=%.2f volume=%.2fx",
                            item.symbol, item.strategy_id, item.entry_reference,
                            item.stop_price, item.target_price, item.volume_ratio,
                        )
                        ledger.record_event(
                            item.generated_at.isoformat(), "INFO", "signal_discovered",
                            f"{item.strategy_id} candidate for {item.symbol}; awaiting REST depth validation",
                        )

            client = UpstoxV3MarketDataClient(
                [item.instrument_key for item in instruments],
                on_tick=handle_tick,
                access_token=access_token,
                symbol_by_key={item.instrument_key: item.symbol for item in instruments},
            )
            client.connect()
            previous_state = None
            last_quote_poll = 0.0
            quote_status: dict[tuple[str, str, datetime], str] = {}

            try:
                while True:
                    now = datetime.now(timezone.utc)
                    state = _market_state(client, scanner, now)
                    if state != previous_state:
                        severity = "WARNING" if state in {"disconnected", "stale"} else "INFO"
                        ledger.record_event(
                            now.isoformat(), severity, f"feed_{state}",
                            client.last_error or f"Market feed state changed to {state}",
                        )
                        logging.info("Market feed state: %s", state)
                        previous_state = state

                    active_candidates = scanner.candidate_signals(now=now)
                    monotonic_now = time.monotonic()
                    if (
                        state == "healthy"
                        and active_candidates
                        and monotonic_now - last_quote_poll >= QUOTE_REFRESH_SECONDS
                    ):
                        instruments_to_quote = tuple(
                            scanner.instruments[item.symbol]
                            for item in active_candidates
                            if item.symbol in scanner.instruments
                        )
                        last_quote_poll = monotonic_now
                        try:
                            quotes = quotes_client.fetch_quotes(instruments_to_quote)
                            quote_now = datetime.now(timezone.utc)
                            for quote_tick in quotes.values():
                                scanner.update_quote(quote_tick, now=quote_now)

                            for signal in active_candidates:
                                key = (signal.symbol, signal.strategy_id, signal.generated_at)
                                valid, reason = scanner.validate_candidate_depth(signal, now=quote_now)
                                if quote_status.get(key) != reason:
                                    quote_status[key] = reason
                                    ledger.record_event(
                                        now.isoformat(),
                                        "INFO" if valid else "WARNING",
                                        "candidate_depth_validated" if valid else "candidate_depth_waiting",
                                        f"{signal.symbol} {signal.strategy_id}: {reason}",
                                    )
                            if paper_coordinator is not None:
                                queued = paper_coordinator.evaluate_candidates(now=quote_now)
                                if queued is not None:
                                    logging.info(
                                        "PAPER signal queued after REST depth validation: %s %s",
                                        queued.symbol, queued.strategy_id,
                                    )
                        except (MarketQuoteError, requests.RequestException) as exc:
                            # The scanner continues, but no new candidate can pass depth validation.
                            ledger.record_event(
                                now.isoformat(), "WARNING", "candidate_quote_request_failed",
                                f"Shortlist quote refresh failed: {type(exc).__name__}",
                            )
                            logging.warning("Shortlist quote refresh failed: %s", type(exc).__name__)

                    time.sleep(1)
            except KeyboardInterrupt:
                logging.info("Stopping market-data radar")
                ledger.record_event(
                    datetime.now(timezone.utc).isoformat(), "INFO",
                    "scanner_stopped", "Scanner stopped by operator",
                )
            finally:
                client.disconnect()
    except requests.RequestException as exc:
        logging.exception("Could not download Upstox instrument master: %s", type(exc).__name__)
        return 3
    except Exception as exc:
        logging.exception("Intraday radar stopped safely: %s", type(exc).__name__)
        return 4
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
