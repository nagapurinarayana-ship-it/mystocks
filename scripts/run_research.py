from __future__ import annotations

import argparse
from pathlib import Path
import pandas as pd

from config import StrategyConfig
from data_sources import DataSourceConfig, load_universe
from universe import validate_universe
from nse_universe import discover_current_nse_symbols, save_universe, load_saved_universe
from research_policy import history_tier
from engine import features
from research_report import rolling_report, summarize


def main() -> None:
    parser = argparse.ArgumentParser(description="Download history and run MyStocks research.")
    parser.add_argument("--years", type=int, default=10)
    parser.add_argument("--refresh", action="store_true")
    parser.add_argument("--discover-nse", action="store_true", help="Refresh current NSE discovery universe first")
    parser.add_argument("--symbols", nargs="*", default=None)
    args = parser.parse_args()

    if args.discover_nse:
        try:
            discovered = discover_current_nse_symbols()
            save_universe(discovered)
        except Exception as exc:
            print(f"NSE discovery failed; using saved/starter universe: {exc}")

    cfg = StrategyConfig()
    symbols = args.symbols or load_saved_universe() or validate_universe()
    data = load_universe(symbols, DataSourceConfig(years=max(args.years, 5), refresh=args.refresh))
    reports = []
    for symbol, df in data.items():
        try:
            x = features(df)
            r = rolling_report(df, cfg)
            s = summarize(r, cfg)
            years = max(0.0, (df.index.max() - df.index.min()).days / 365.25)
            tier = history_tier(years)
            s.update({"symbol": symbol, "history_years": round(years, 2), "history_tier": tier.name})
            reports.append(s)
        except Exception as exc:
            print(f"Research failed for {symbol}: {exc}")
    out = pd.DataFrame(reports)
    if not out.empty:
        out = out.sort_values(["expected_value", "win_rate"], ascending=False)
    Path("data").mkdir(exist_ok=True)
    out.to_csv("data/research_summary.csv", index=False)
    print(out.to_string(index=False))


if __name__ == "__main__":
    main()
