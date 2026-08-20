from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import pandas as pd

from config import StrategyConfig
from research_data import ResearchDataConfig, load_universe
from universe import validate_universe
from nse_universe import discover_current_nse_symbols, save_universe, load_saved_universe
from research_policy import history_tier
from engine import features
from research_report import rolling_report, summarize
from walk_forward_eval import evaluate_walk_forward, aggregate

WINDOW_YEARS = (10, 5, 3, 2, 1)
MIN_RESEARCH_ROWS = 252
MIN_WALK_FORWARD_ROWS = 1008


def trailing_window(df: pd.DataFrame, years: int) -> pd.DataFrame:
    if df.empty:
        return df
    end = df.index.max()
    start = end - pd.DateOffset(years=years)
    return df.loc[df.index >= start].copy()


def classify_status(df: pd.DataFrame) -> tuple[str, str]:
    if df.empty:
        return 'no_data', 'No historical OHLCV data returned'
    observations = len(df)
    years = max(0.0, (df.index.max() - df.index.min()).days / 365.25) if observations > 1 else 0.0
    if observations < MIN_RESEARCH_ROWS:
        return 'limited_history', f'{observations} observations; insufficient for full statistical research'
    if years < 1:
        return 'less_than_1_year', f'{years:.2f} years available; exploratory only'
    return 'research_eligible', 'Sufficient history for baseline research'


def main() -> None:
    parser = argparse.ArgumentParser(description='Run multi-history MyStocks research.')
    parser.add_argument('--years', type=int, default=10)
    parser.add_argument('--refresh', action='store_true')
    parser.add_argument('--discover-nse', action='store_true')
    parser.add_argument('--symbols', nargs='*', default=None)
    args = parser.parse_args()

    if args.discover_nse:
        try:
            discovered = discover_current_nse_symbols()
            save_universe(discovered)
            print(f'Discovered {len(discovered)} current NSE symbols')
        except Exception as exc:
            print(f'NSE discovery failed; using saved/starter universe: {exc}')

    cfg = StrategyConfig()
    symbols = args.symbols or load_saved_universe() or validate_universe()
    data = load_universe(symbols, ResearchDataConfig(years=max(args.years, 10), refresh=args.refresh))

    baseline_rows = []
    wf_rows = []
    wf_summary_rows = []
    universe_rows = []

    for symbol in symbols:
        df = data.get(symbol, pd.DataFrame())
        status, status_detail = classify_status(df)
        full_years = max(0.0, (df.index.max() - df.index.min()).days / 365.25) if len(df) > 1 else 0.0
        tier = history_tier(full_years) if not df.empty else None
        universe_rows.append({
            'symbol': symbol,
            'observations': len(df),
            'available_history_years': round(full_years, 2),
            'history_tier': tier.name if tier else 'no_history',
            'status': status,
            'status_detail': status_detail,
        })
        if df.empty or len(df) < MIN_RESEARCH_ROWS:
            continue
        try:
            for window_years in WINDOW_YEARS:
                wdf = trailing_window(df, window_years)
                actual_years = max(0.0, (wdf.index.max() - wdf.index.min()).days / 365.25) if len(wdf) > 1 else 0.0
                if len(wdf) < MIN_RESEARCH_ROWS:
                    continue
                features(wdf)
                r = rolling_report(wdf, cfg)
                s = summarize(r, cfg)
                s.update({'symbol': symbol, 'baseline_years': window_years, 'actual_years': round(actual_years, 2), 'available_history_years': round(full_years, 2), 'history_tier': tier.name})
                baseline_rows.append(s)
                if len(wdf) >= MIN_WALK_FORWARD_ROWS:
                    folds = evaluate_walk_forward(wdf, cfg)
                    if not folds.empty:
                        folds = folds.copy()
                        folds['symbol'] = symbol
                        folds['baseline_years'] = window_years
                        wf_rows.extend(folds.to_dict('records'))
                        agg = aggregate(folds)
                        agg.update({'symbol': symbol, 'baseline_years': window_years, 'available_history_years': round(full_years, 2), 'history_tier': tier.name})
                        wf_summary_rows.append(agg)
        except Exception as exc:
            print(f'Research failed for {symbol}: {exc}')
            universe_rows[-1]['status'] = 'research_error'
            universe_rows[-1]['status_detail'] = str(exc)

    Path('data').mkdir(exist_ok=True)
    universe = pd.DataFrame(universe_rows).sort_values(['status', 'symbol'])
    universe.to_csv('data/nse_research_universe.csv', index=False)

    baseline = pd.DataFrame(baseline_rows)
    if not baseline.empty:
        baseline = baseline.sort_values(['baseline_years', 'expected_value', 'win_rate'], ascending=[False, False, False])
    baseline.to_csv('data/research_baselines.csv', index=False)
    baseline.to_csv('data/research_summary.csv', index=False)

    wf = pd.DataFrame(wf_rows)
    wf.to_csv('data/walk_forward_folds.csv', index=False)
    wfs = pd.DataFrame(wf_summary_rows)
    if not wfs.empty:
        wfs = wfs.sort_values(['baseline_years', 'expected_value'], ascending=[False, False])
    wfs.to_csv('data/walk_forward_summary.csv', index=False)

    short_rows = [r for r in universe_rows if r['status'] in {'limited_history', 'less_than_1_year'}]
    pd.DataFrame(short_rows).to_csv('data/less_than_1_year.csv', index=False)

    print(f'=== COMPLETE NSE UNIVERSE: {len(universe_rows)} symbols ===')
    print(universe['status'].value_counts().to_string())
    print('=== RESEARCH BASELINES ===')
    print(baseline.to_string(index=False))
    print('=== WALK-FORWARD SUMMARY ===')
    print(wfs.to_string(index=False))


if __name__ == '__main__':
    main()
