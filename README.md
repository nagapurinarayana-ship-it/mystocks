# MyStocks — India Research Radar

Indian-equity research application with two distinct workspaces:

1. **Long-term micro-cap watchlist** — filing-first monitoring for a small set of manually researched companies.
2. **Short-term NSE research radar** — full-universe statistical research for realistic target/stop setups.

**No guaranteed returns.** Market data and news feeds are research aids; exchange/company filings are the source of truth for material facts.

## Long-term watchlist

The Streamlit dashboard now opens on a long-term research workspace for:

- Nila Infrastructures (`NILAINFRA.NS`)
- Ashapuri Gold Ornament (`542579.BO`)
- Madhav Infra Projects (`MADHAVIPL.NS`)

The public repository intentionally stores **watchlist/research metadata only**. It does not store private purchase price, quantity or portfolio value.

For each company the dashboard provides:

- live/delayed price and selected fundamental fields from Yahoo Finance
- 6-month, 1-year, 5-year and maximum available price history
- manually reviewed investment thesis and known risks
- thesis-breaking “kill switches” such as promoter pledge, audit problems, repeated dilution and cash-flow deterioration
- mechanical live-feed warnings where sufficient data is available
- direct NSE/BSE/company/rating-agency links for source-of-truth verification
- latest Google News RSS headlines clearly labelled as a **secondary discovery feed**

Manual research scores are dated snapshots, not analyst targets and not predictions.

## Short-term research architecture

The original research engine remains intact:

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

## Short-term methodology

- Entry: next-session open after the signal.
- Default target: +2.0% from entry.
- Default stop: -1.0% from entry.
- Maximum holding period: 3 sessions.
- Same-candle target/stop ambiguity is treated conservatively as a loss.
- Expected value includes the configured round-trip cost.
- Chronological / walk-forward validation rather than random splits.
- Compare against baseline behaviour rather than assuming the strategy adds value.
- Up to three picks; **never force picks when evidence is weak**.

## Run the dashboard locally

```bash
python -m venv .venv
# Windows: .venv\\Scripts\\activate
# macOS/Linux: source .venv/bin/activate
pip install -r requirements.txt
streamlit run app.py
```

Use the sidebar to switch between **Long-term watchlist** and **Short-term research radar**.

## Full-universe research workflow

Manual run:

```bash
python scripts/run_research.py --years 10 --refresh --discover-nse
```

GitHub Actions runs the same research pipeline on pushes to `main`, on demand, and on the scheduled weekday refresh. Tests run before the expensive full-universe workflow starts. The workflow then discovers the NSE universe once, distributes symbols across 16 shards, and aggregates the outputs.

## Data integrity and source hierarchy

Recommended evidence order for long-term decisions:

1. NSE/BSE regulatory filings and audited financial statements.
2. Company investor-relations disclosures.
3. Credit-rating-agency rationales where relevant.
4. Market-data providers and reputable financial databases for cross-checking.
5. News/search aggregators for discovery only.

Yahoo Finance through `yfinance` is used for convenient market data. It is suitable for local/personal research but is not a licensed authoritative feed for commercial/public investment conclusions. Historical constituent membership, delistings, sector membership, corporate actions and point-in-time universe data remain important limitations.

## Research output contract

The full-universe workflow produces:

- `nse_current_universe.csv` — discovered current NSE universe
- `nse_research_universe.csv` — **every discovered symbol with data coverage and research status**
- `research_summary.csv` — baseline research results
- `research_baselines.csv` — baseline research results by history window
- `walk_forward_folds.csv` — chronological walk-forward fold results
- `walk_forward_summary.csv` — aggregated walk-forward results
- `less_than_1_year.csv` — limited-history exploratory cohort

The key design rule remains: **100% universe coverage, 0% fake statistical confidence.**
