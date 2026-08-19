# MyStocks — India 2% Stock Research Engine

Private/local-first research application for testing whether Indian equities can be ranked for a realistic ~2% upside target using 5+ years of historical data.

> **Research only. No guaranteed returns.** The app must never present a 2% gain as certain.

## Goals

- Use at least 5 years of daily OHLCV history.
- Evaluate target-before-stop outcomes rather than simple returns.
- Avoid look-ahead leakage with time-ordered walk-forward testing.
- Rank liquid NSE candidates and allow fewer than three picks when evidence is weak.
- Track every daily paper-trade recommendation so live performance can be audited.

## Local run

```bash
python -m venv .venv
# Windows: .venv\\Scripts\\activate
# macOS/Linux: source .venv/bin/activate
pip install -r requirements.txt
streamlit run app.py
```

The first data download can take time. By default the prototype uses Yahoo Finance through `yfinance` for personal/local research. Replace it with a licensed market-data feed before commercial/public use.

## Methodology

Default setup:

- Entry: next session open after the signal.
- Target: +2.0% from entry.
- Stop: -1.0% from entry.
- Holding period: 3 trading sessions.
- If target and stop are both touched in the same daily candle, the engine assumes **stop first** (conservative because daily OHLC cannot reveal intraday order).
- Costs/slippage are configurable.

The ranking combines historical target-before-stop probability, expected value, sample size, trend/momentum/volume features, and market regime filters.

## Important validation rules

1. Never randomly shuffle time series.
2. Do not use future information when creating a signal.
3. Keep an untouched final out-of-sample period.
4. Include transaction costs and slippage.
5. Track delisted/survivorship issues before trusting universe-level results.
6. Paper-trade before considering any real-money use.

## Planned production research layers

1. Licensed NSE/BSE historical and live data.
2. Corporate-action-aware adjusted data.
3. Survivorship-bias-free universe.
4. NIFTY, sector and volatility regime features.
5. Event/earnings filter.
6. Multiple strategy families and walk-forward model selection.
7. Probability calibration and confidence intervals.
8. Persistent paper-trading ledger and daily performance report.
