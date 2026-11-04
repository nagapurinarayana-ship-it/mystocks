"""Fetch real historical candles and produce a cost-aware intraday research report.

Requires the selected broker's exact published fee schedule in MYSTOCKS_PAPER_FEE_*
environment variables. It never submits broker orders.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from dataclasses import asdict
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from intraday.backtesting.simulation import run_intraday_backtest  # noqa: E402
from intraday.execution.configuration import (  # noqa: E402
    FeeConfigurationError,
    load_fee_schedule_from_environment,
)
from intraday.market_data.history import (  # noqa: E402
    HistoricalDataError,
    UpstoxHistoricalCandleClient,
)
from scripts.run_intraday_radar import load_instruments  # noqa: E402


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="MyStocks intraday historical backtest")
    parser.add_argument("--symbol", required=True, help="NSE cash-equity trading symbol, e.g. RELIANCE")
    parser.add_argument("--from-date", required=True, type=date.fromisoformat, help="First date YYYY-MM-DD")
    parser.add_argument("--to-date", required=True, type=date.fromisoformat, help="Last date YYYY-MM-DD")
    parser.add_argument(
        "--strategy", choices=("vwap_momentum", "opening_range_breakout"),
        default="vwap_momentum",
    )
    parser.add_argument(
        "--output", type=Path,
        help="Output JSON path; defaults to data/intraday-backtests/<symbol>-<from>-<to>.json",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    symbol = args.symbol.strip().upper()
    if args.to_date < args.from_date:
        print("ERROR: --to-date must be on or after --from-date", file=sys.stderr)
        return 2
    if not os.getenv("UPSTOX_ACCESS_TOKEN"):
        print("ERROR: set UPSTOX_ACCESS_TOKEN using the official OAuth process", file=sys.stderr)
        return 2

    try:
        fees = load_fee_schedule_from_environment()
        if fees is None:
            raise FeeConfigurationError(
                "Set all MYSTOCKS_PAPER_FEE_* inputs from the chosen broker's current published tariff; "
                "the tool does not assume fee values."
            )
        available = {item.symbol: item for item in load_instruments()}
        instrument = available.get(symbol)
        if instrument is None:
            raise ValueError(
                f"{symbol} was not present as an eligible broker-supported NSE cash equity "
                "in today's instrument master"
            )

        history = UpstoxHistoricalCandleClient().fetch_5m_bars(
            instrument, args.from_date, args.to_date
        )
        if not history.bars:
            raise HistoricalDataError("no valid historical candles were returned for this symbol/date range")

        result = run_intraday_backtest(
            instrument=instrument,
            bars=history.bars,
            strategy=args.strategy,
            cost_schedule=fees,
        )
        payload = {
            "summary": asdict(result.summary),
            "trades": list(result.trades),
            "history_quality": {
                "request_count": history.request_count,
                "invalid_rows": history.invalid_rows,
                "duplicate_rows": history.duplicate_rows,
                "valid_bars": len(history.bars),
            },
            "important_limits": [
                "This is a single-symbol research backtest, not an all-NSE point-in-time universe test.",
                "The OHLCV VWAP proxy uses typical price multiplied by volume; it is not trade-level VWAP.",
                "The OHLC fill model cannot represent queue priority, partial fills or market impact.",
                "A profitable historical result does not guarantee future performance.",
                "No broker order is placed by this script.",
            ],
        }
        output = args.output or (
            ROOT / "data" / "intraday-backtests"
            / f"{symbol}-{args.from_date.isoformat()}-{args.to_date.isoformat()}-{args.strategy}.json"
        )
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(json.dumps(payload, indent=2, allow_nan=False), encoding="utf-8")
        print(json.dumps(payload["summary"], indent=2, allow_nan=False))
        print(f"Report written to {output}")
        return 0
    except (FeeConfigurationError, HistoricalDataError, ValueError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 3
    except Exception:
        # Never print provider response bodies or credentials on an unexpected failure.
        print("ERROR: intraday backtest stopped safely; inspect local application logs.", file=sys.stderr)
        return 4


if __name__ == "__main__":
    raise SystemExit(main())
