# MyStocks — India 2% Stock Research Engine

Private/local-first Indian equity research application for testing whether stocks can be ranked for a realistic ~2% upside target. **No guaranteed returns.**

## Research tracks

- **Established:** 5+ years of direct history.
- **Mid-history:** 3–5 years, reduced confidence.
- **Emerging:** 1–3 years, exploratory and supported by peer/sector evidence.
- **New:** 6–12 months, early-signal research only; under 6 months is normally insufficient.

New listings are not discarded just because they lack five years of data, but short histories can never receive the same statistical confidence as mature histories.

## Core methodology

- Entry: next-session open after the signal.
- Target: +2.0% from entry.
- Stop: -1.0% from entry.
- Maximum holding period: 3 sessions.
- Same-candle target/stop ambiguity is treated conservatively as stop first.
- Costs and slippage must be included.
- Chronological/walk-forward validation only.
- No future constituent membership or pre-listing prices.
- Compare against unconditional and buy-and-hold baselines.
- Up to three picks; **never force three** when evidence is weak.

## Evidence model

Candidate rankings can incorporate:

- direct historical target-before-stop probability
- lower confidence bound
- sample size
- history tier
- trend/momentum/volume
- market regime
- sector relative strength
- peer similarity
- liquidity/volatility
- expected value after costs

Every daily candidate should expose its evidence and invalidation conditions.

## Local run

```bash
python -m venv .venv
# Windows: .venv\\Scripts\\activate
# macOS/Linux: source .venv/bin/activate
pip install -r requirements.txt
python scripts/run_research.py --years 10 --refresh
streamlit run app.py
```

The prototype uses Yahoo Finance through `yfinance` for local/personal research. A licensed/authoritative feed with historical corporate actions and point-in-time universe data is required before commercial/public conclusions.

## Data integrity

Historical universe membership, sector membership, corporate actions, listing/delisting status and OHLCV quality must be point-in-time aware. The current starter universe is explicitly **prototype research with survivorship-bias risk** until those datasets are integrated.

## Status

The repository contains the research engine, data-source abstraction, quality validation, history tiers, peer/sector primitives, guardrails, baseline tests, paper-trading ledger, daily radar and scheduled research workflow. The next evidence milestone is the broad historical run using authoritative data.
