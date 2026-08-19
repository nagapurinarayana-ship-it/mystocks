from __future__ import annotations
from pathlib import Path
from config import StrategyConfig
from data_sources import DataSourceConfig, load_universe
from universe import validate_universe
from daily_radar import rank_daily, to_frame

def main() -> None:
    symbols = validate_universe()
    data = load_universe(symbols, DataSourceConfig(years=10, refresh=True))
    picks = rank_daily(data, StrategyConfig())
    out = to_frame(picks)
    Path("data").mkdir(exist_ok=True)
    out.to_csv("data/daily_picks.csv", index=False)
    print(out.to_string(index=False) if not out.empty else "NO QUALIFYING SETUPS")

if __name__ == "__main__":
    main()
