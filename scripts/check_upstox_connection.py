"""Authenticated Upstox V3 market-data smoke test (no orders, no account access).

Run this locally during NSE regular market hours with UPSTOX_ACCESS_TOKEN set in
the process environment. The script intentionally never prints auth URLs/tokens.
"""

from __future__ import annotations

import argparse
from datetime import datetime, time as clock_time, timezone
import os
from pathlib import Path
import sys
import threading
import time
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from intraday.market_data.quotes_v3 import (  # noqa: E402
    MarketQuoteError,
    UpstoxFullMarketQuotesV3Client,
)
from intraday.market_data.upstox_v3 import (  # noqa: E402
    UpstoxFeedError,
    UpstoxV3MarketDataClient,
)
from scripts.run_intraday_radar import load_instruments  # noqa: E402


IST = ZoneInfo("Asia/Kolkata")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Verify one authenticated Upstox V3 WebSocket instrument and REST top-of-book quote."
    )
    parser.add_argument("--symbol", default="RELIANCE", help="NSE cash-equity symbol (default: RELIANCE)")
    parser.add_argument(
        "--timeout-seconds",
        type=float,
        default=30.0,
        help="maximum wait for first WebSocket tick (10-120 seconds)",
    )
    args = parser.parse_args()
    args.symbol = args.symbol.strip().upper()
    if not args.symbol:
        parser.error("--symbol cannot be empty")
    if not 10 <= args.timeout_seconds <= 120:
        parser.error("--timeout-seconds must be between 10 and 120")
    return args


def main() -> int:
    args = parse_args()
    access_token = os.getenv("UPSTOX_ACCESS_TOKEN", "")
    if not access_token.strip():
        print("Missing UPSTOX_ACCESS_TOKEN. Set it locally using the official Upstox OAuth flow.")
        return 2

    now_local = datetime.now(IST)
    if (
        now_local.weekday() >= 5
        or not (clock_time(9, 15) <= now_local.time().replace(tzinfo=None) < clock_time(15, 30))
    ):
        print(
            "NSE regular session is closed. Run this smoke test on a weekday "
            "between 09:15 and 15:30 IST."
        )
        return 3

    try:
        instruments = load_instruments()
        instrument = next(
            (item for item in instruments if item.symbol.upper() == args.symbol),
            None,
        )
        if instrument is None:
            print(f"{args.symbol} is not in the eligible NSE cash-equity instrument master.")
            return 4

        received_ticks = []
        first_tick = threading.Event()

        def on_tick(tick) -> None:
            if tick.instrument_key != instrument.instrument_key:
                return
            received_ticks.append(tick)
            first_tick.set()

        feed = UpstoxV3MarketDataClient(
            [instrument.instrument_key],
            on_tick=on_tick,
            access_token=access_token,
            symbol_by_key={instrument.instrument_key: instrument.symbol},
            max_reconnect_attempts=2,
            reconnect_interval_seconds=3,
        )
        try:
            feed.connect()
            if not first_tick.wait(timeout=args.timeout_seconds):
                detail = feed.last_error or "no matching LTPC tick arrived before timeout"
                print(f"WebSocket smoke test failed: {detail}")
                return 5

            quote_client = UpstoxFullMarketQuotesV3Client(access_token=access_token)
            quote_now = datetime.now(timezone.utc)
            try:
                quotes = quote_client.fetch_quotes((instrument,), now=quote_now)
            except MarketQuoteError as exc:
                print(f"REST quote smoke test failed: {exc}")
                return 6

            quote = quotes.get(instrument.instrument_key)
            if (
                quote is None
                or quote.best_bid is None
                or quote.best_ask is None
                or not quote.best_bid_quantity
                or not quote.best_ask_quantity
            ):
                print(
                    "WebSocket tick received, but no fresh two-sided REST top-of-book "
                    "quote was available. No trading action was taken."
                )
                return 7

            latest = received_ticks[-1]
            print(
                f"Upstox V3 market-data smoke test passed for {instrument.symbol}. "
                f"LTPC ₹{latest.price:.2f}; bid ₹{quote.best_bid:.2f}; "
                f"ask ₹{quote.best_ask:.2f}; bid qty {quote.best_bid_quantity}; "
                f"ask qty {quote.best_ask_quantity}. "
                "No orders or account actions were performed."
            )
            return 0
        finally:
            feed.disconnect()
    except (UpstoxFeedError, MarketQuoteError) as exc:
        print(f"Upstox market-data smoke test failed: {exc}")
        return 8
    except Exception as exc:
        # Log the exception class only; never echo request headers or response data.
        print(f"Market-data smoke test stopped safely: {type(exc).__name__}")
        return 9


if __name__ == "__main__":
    raise SystemExit(main())
