# MyStocks — India Research Radar

Full-universe Indian equity research application for testing whether stocks can be ranked for a realistic short-term upside target. **No guaranteed returns.**

## Current architecture

- Discovers the current NSE equity universe from the official NSE equity CSV.
- Retains **every discovered symbol** during data collection, including new listings and very short histories.
- Downloads data in controlled 40-symbol batches with retries instead of one request per symbol.
- Splits the full universe across 16 GitHub Actions research shards, with at most 4 shards running concurrently.
- Produces a complete `nse_research_universe.csv` accounting file so no discovered symbol silently disappears.
- Separates data coverage from research eligibility: limited-history stocks remain visible but are not ranked as if they had mature evidence.
- Runs multi-history baseline research and chronological walk-forward evaluation for stocks with sufficient history.
- Aggregates all shard outputs into one research artifact.

## Research tracks

- **Established:** 5+ years of direct history.
- **Mid-history:** 3–5 years, reduced confidence.
- **Emerging:** 1–3 years, exploratory.
- **New:** 6–12 months, early-signal research only.
- **Insufficient:** under the minimum observations for statistical backtesting; retained for coverage but excluded from mature rankings.

Short histories are never treated as equivalent to mature histories.

## Core methodology

- Entry: next-session open after the signal.
- Default target: +2.0% from entry.
- Default stop: -1.0% from entry.
- Maximum holding period: 3 sessions.
- Same-candle target/stop ambiguity is treated conservatively as a loss.
- Expected value includes the configured round-trip cost.
- Chronological / walk-forward validation rather than random splits.
- Compare against baseline behaviour rather than assuming the strategy adds value.
- Up to three picks; **never force picks when evidence is weak**.

## Dashboard

`app.py` is a Streamlit research dashboard designed around the complete NSE universe. It provides:

- full-universe discovery
- controlled data loading
- current candidate ranking
- confidence and expected-value evidence
- complete universe coverage/status accounting
- CSV export of universe status
- explicit methodology and research guardrails

Run locally:

```bash
python -m venv .venv
# Windows: .venv\\Scripts\\activate
# macOS/Linux: source .venv/bin/activate
pip install -r requirements.txt
streamlit run app.py
```

## Research workflow

Manual full-universe run:

```bash
python scripts/run_research.py --years 10 --refresh --discover-nse
```

GitHub Actions runs the same research pipeline on pushes to `main`, on demand, and on the scheduled weekday refresh. The workflow validates the research tests, discovers the NSE universe once, distributes symbols across 16 shards, and aggregates the outputs.

## Data integrity

The current market-data source is Yahoo Finance through `yfinance`, suitable for local/personal research but not a substitute for a licensed authoritative feed for commercial/public investment conclusions. Historical constituent membership, delistings, sector membership, corporate actions and point-in-time universe data remain important limitations.

The application therefore presents research as evidence, not a prediction or investment guarantee.

## Output contract

The research workflow produces:

- `nse_current_universe.csv` — discovered current NSE universe
- `nse_research_universe.csv` — **every discovered symbol with data coverage and research status**
- `research_summary.csv` — baseline research results
- `research_baselines.csv` — baseline research results by history window
- `walk_forward_folds.csv` — chronological walk-forward fold results
- `walk_forward_summary.csv` — aggregated walk-forward results
- `less_than_1_year.csv` — limited-history exploratory cohort

The key design rule is: **100% universe coverage, 0% fake statistical confidence.**
