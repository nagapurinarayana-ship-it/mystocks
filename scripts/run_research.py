from __future__ import annotations

import argparse
from pathlib import Path
import pandas as pd

from config import StrategyConfig
from data_sources import DataSourceConfig, load_universe
from universe import validate_universe
from engine import features, outcome
from research_report import rolling_report, summarize


def main() -> None:
    parser = argparse.ArgumentParser(description="Download history and run MyStocks research.")
    parser.add_argument("--years", type=int, default=10)
    parser.add_argument("--refresh", action="store_true")
    parser.add_argument("--symbols", nargs="*", default=None)
    args = parser.parse_args()

    cfg = StrategyConfig()
    symbols = args.symbols or validate_universe()
    data = load_universe(symbols, DataSourceConfig(years=max(args.years, 5), refresh=args.refresh))
    reports = []
    for symbol, df in data.items():
        try:
            r = rolling_report(df, cfg)
            s = summarize(r, cfg)
            s["symbol"] = symbol
            reports.append(s)
        except Exception as exc:
            print(f"Research failed for {symbol}: {exc}")
    out = pd.DataFrame(reports).sort_values(["expected_value", "win_rate"], ascending=False) if reports else pd.DataFrame()
    Path("data").mkdir(exist_ok=True)
    out.to_csv("data/research_summary.csv", index=False)
    print(out.to_string(index=False))


if __name__ == "__main__":
    main()
