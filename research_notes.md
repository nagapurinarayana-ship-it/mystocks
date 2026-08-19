# MyStocks research protocol

## Objective
Test whether liquid Indian equities contain repeatable setups whose probability of reaching a +2% target before a defined stop is attractive after realistic costs.

## Rules
- Use only information available at the signal timestamp.
- Signal is evaluated on the completed session; entry is next-session open.
- Never shuffle time-series observations.
- Use chronological walk-forward/out-of-sample windows.
- Treat same-day target+stop ambiguity conservatively as a loss.
- Include transaction costs and slippage assumptions.
- Report sample count, win/loss/timeout counts and expected value.
- Do not force three recommendations.
- Keep a paper-trading ledger before any real-money use.

## Required future upgrades
1. Survivorship-bias-free historical NSE universe.
2. Corporate-action-aware adjusted and raw data.
3. NIFTY, sector and volatility regime features.
4. Earnings/corporate-event filters.
5. Multiple strategy families and model selection only inside training windows.
6. Final untouched out-of-sample period.
7. Confidence intervals and calibration.
8. Realistic Indian trading costs, taxes and slippage.
9. Live paper-trading evaluation.
