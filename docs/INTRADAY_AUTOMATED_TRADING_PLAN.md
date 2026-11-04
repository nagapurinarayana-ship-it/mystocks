# MyStocks Intraday Radar and Automated Trading — Implementation Plan

## Product decision

Build toward eventual live automated trading for Indian equities, while keeping every live trading capability disabled until the account owner explicitly authorises it. Broker selection is intentionally deferred. Preserve the existing long-term watchlist and short-term daily research engine; this is a separate capability.

## Non-negotiable safety boundary

- Default mode is `research`; paper mode is opt-in; live mode is unavailable unless a deliberate, authenticated, audited enablement process is completed.
- No broker order-placement call may be reachable in research or paper mode.
- No live order placement, modification, cancellation, square-off, fund transfer, or withdrawal is enabled by this plan.
- Never store broker passwords, TOTP seeds, API secrets, access tokens, or static-IP credentials in Git, Streamlit config committed to Git, logs, workflow artifacts, or public research outputs.
- Live enablement must require an explicit user action, fresh broker authentication, verified broker/account permissions, configured risk limits, and a visible confirmation showing symbol, side, quantity, order type, and maximum estimated exposure.
- Add a global kill switch and a fail-closed execution gate. If mode, credentials, market data, risk state, broker state, or compliance state is unknown/stale, reject execution.
- Do not promise returns or describe model scores as probabilities of profit unless calibrated and validated.

## Architecture

Create a dedicated `intraday/` package. Do not alter the existing `engine.py`, `backtest.py`, long-term watchlist, or current research workflows as part of the initial foundation.

Proposed modules:

```text
intraday/
  config.py
  domain.py
  universe.py
  market_data/
    interface.py
    instruments.py
    quality.py
  strategies/
    opening_range.py
    vwap_momentum.py
    unusual_volume.py
    reversal.py
    sector_leadership.py
  ranking/
    scoring.py
    selector.py
  risk/
    limits.py
    sizing.py
    exits.py
  execution/
    interface.py
    disabled.py
    paper.py
    broker_adapters/
  portfolio/
    positions.py
    pnl.py
    reconciliation.py
  backtesting/
    simulator.py
    walk_forward.py
    metrics.py
  reporting/
    daily_radar.py
    trade_ledger.py
```

### Market universe and data

- Discover and reconcile the full eligible NSE cash-equity universe from exchange/broker instrument masters; preserve an accounting row for every discovered instrument, including excluded/unavailable symbols and reasons.
- Validate trading status, symbol/token mapping, series, price bands/circuit limits, tick size, lot/unit rules, corporate actions, and instrument-master freshness.
- Require timestamped intraday candles (1-minute and 5-minute minimum), trades/volume and preferably bid/ask/depth. Derive VWAP and same-time-of-day relative volume from source data.
- Existing Yahoo daily data is not an intraday execution feed. Select a broker/market-data provider only after checking API access, historical minute data, retention, latency, licensing, static-IP requirements, rate limits, support and total cost.
- Keep a vendor-neutral market-data contract so a broker can be selected later. Do not use fixture or synthetic data to claim real-market performance.

### Strategy and opportunity selection

Implement independent research strategies: opening-range breakout, VWAP momentum, unusual volume with price confirmation, momentum reversal, and sector leadership. Keep strategy signals explainable and persist the input timestamps and feature values.

Display at most three opportunities per session. It is valid to display fewer than three or none. Require fresh data, sufficient liquidity, acceptable spread/slippage, validated out-of-sample net expectancy, and configured risk checks before a candidate can be marked eligible.

### Risk and order lifecycle

- Position size is derived from risk budget and stop distance, then capped by per-trade, per-symbol, sector, gross-exposure and daily-loss limits.
- Include brokerage, taxes/levies, exchange charges, spread, slippage, partial fills, rejected orders, gaps, circuit limits and market impact in research/backtests.
- Use idempotent client order identifiers, durable order/position state, broker reconciliation and explicit handling of uncertain order status to prevent duplicate orders.
- Stops and exits must be exchange/broker-supported and monitored; never assume a local process running continuously guarantees a protective stop.
- Define maximum daily loss, maximum concurrent positions, maximum exposure, per-symbol cap, stale-data timeout, connectivity-loss behaviour, and end-of-day square-off policy before any live pilot.
- The first release should be long-only cash equities; do not add leverage, MTF, F&O, short selling, or overnight carry without a separate risk and compliance review.

### ₹1,000 starting-capital operating constraint

The initial capital provided for evaluation is **₹1,000 total**. Treat this as the only external funding: no automatic top-ups, borrowed funds, margin/leverage, MTF, F&O, or short selling. Profits may be retained and compounded only after they are realised net of all charges and reflected as available broker funds. A loss must never trigger an automatic request for more money.

- Do not promise that ₹1,000 can generate enough profit to pay for the system or become self-sustaining. The product must report actual net results, including losing days and periods with no trades.
- Target **zero recurring infrastructure/data spend** for the initial build. Do not subscribe to paid feeds, VPS/static-IP services, or paid algo services from this ₹1,000 budget. If the selected broker's compliant API setup requires additional recurring spend, keep live trading disabled and continue paper research until separately funded and explicitly approved.
- For paper evaluation, start with a maximum planned loss budget of 0.5% of current strategy equity per trade and 1% per day, inclusive of estimated charges and slippage; one open position maximum. These are conservative test guardrails, not promises or a claim that trades will be available.
- Size positions using whole shares and cash-only notional. If the minimum whole-share quantity, stop distance, estimated costs, or slippage breaches the risk budget, skip the trade. Never loosen the stop, increase quantity, or use leverage to force a trade.
- Estimate the complete round-trip cost before every candidate: brokerage on both executed sides, STT, exchange charges, GST, SEBI charges, stamp duty, spread and expected slippage. Reject candidates when net expected edge is not clearly positive after costs or the cost estimate is stale.
- Keep a separate strategy ledger that reports starting capital, peak/trough equity, realised net P&L, charges, drawdown, return on initial capital, number of trades, and how much profit is retained. Do not count unrealised gains as spendable profit.
- The system may correctly produce no trade for many sessions. It must never manufacture activity to meet a daily profit target.

A small-account cost illustration must be shown in the UI, using the chosen broker's live published tariff and a test order size. For context only, Zerodha currently publishes intraday brokerage at 0.03% or ₹20 per executed order (whichever is lower), plus statutory charges such as sell-side STT, exchange transaction charges, GST and buy-side stamp duty; the actual broker has not been selected, and the estimate must be recalculated for that broker before any use.

### Broker adapter boundary

Define a common interface for authentication status, instrument master, quotes/stream, historical candles, funds/margins, positions, orders, order status, trades and (eventually) order placement/modification/cancellation. Implement only read-only capability until a broker is chosen and reviewed. Broker adapters must advertise capabilities explicitly; unsupported operations fail closed.

### Profit, P&L and withdrawals

- Distinguish unrealised P&L, realised gross P&L, charges/taxes, realised net P&L, available cash and withdrawable balance.
- Use broker-reported funds/ledger as the source of truth; do not infer withdrawable funds from a winning trade or displayed P&L.
- Provide profit summaries and withdrawal eligibility information only. No automatic withdrawal, payout, bank transfer or fund movement. A user must initiate withdrawals through the broker's own authorised process.

## Regulatory and operational readiness

Before any live API trading, obtain broker confirmation of eligibility and required registration/approval for the intended client-direct API/algo use, static-IP mapping, API key classification, algo registration where applicable, daily session logout, audit/log retention and other current exchange/broker requirements. Obtain appropriate legal/compliance advice for any stock-specific recommendations distributed to others. Re-check current SEBI/NSE/BSE rules and broker implementation standards at launch; this document is an engineering plan, not legal advice.

## Delivery milestones

1. **Foundation and audit:** inspect repository structure, tests, deployment and secrets handling; add domain contracts, configuration defaults and execution safety gate.
2. **Market-data foundation:** provider-neutral interfaces, NSE instrument reconciliation, quality/coverage reporting, timestamp monitoring; select a provider after comparing current official docs and terms.
3. **Research strategies:** implement five isolated strategies and transparent candidate explanations.
4. **Risk and paper execution:** position sizing, costs, simulated fills, order lifecycle, P&L ledger, reconciliation and kill switch. No real broker order endpoints.
5. **Backtesting and validation:** point-in-time data where available, no lookahead, chronological walk-forward, adverse fills, confidence intervals, drawdown and at least 30 live-market paper sessions.
6. **Read-only broker connection:** after broker selection, connect account read-only for balances/positions/orders and reconcile paper ledger; keep trading endpoints disabled.
7. **Live-trading readiness review:** separate explicit approval gate after performance, security, operational, regulatory and broker checks. Only then propose a narrowly capped live pilot in a separate change.

## Acceptance criteria

- Existing dashboards, long-term watchlist, research engine and scheduled workflows remain unchanged and pass regression tests.
- 100% of discovered instruments are accounted for, with exclusion/data-quality reasons.
- No lookahead or survivorship assumptions are hidden; all data is timestamped and source-attributed.
- Research results are net of realistic costs and report sample size, out-of-sample periods, drawdown, profit factor, expectancy and uncertainty.
- Research and paper modes cannot call live order endpoints; automated tests prove this.
- Default configuration is safe even when environment variables are absent or malformed.
- Secrets never appear in logs, reports, Git history or artifacts.
- No withdrawal or fund-transfer functionality is implemented.
- No merge to `main` until all checks and human review pass.

## Current decisions / open items

- Target market: NSE cash equities.
- Opportunity cap: three per trading session.
- Execution ambition: eventual live automated trading; currently disabled.
- Broker: undecided.
- Market-data provider: undecided.
- Initial strategy direction: long-only; no leverage/F&O.
- Starting external capital: ₹1,000 only; retained realised net profits may compound, but no external top-ups are assumed.
- Paper guardrails: 0.5% planned risk per trade, 1% daily loss limit including estimated costs, and one open position maximum; these must be tested and may result in no-trade outcomes.
- Recurring data/hosting spend target: ₹0 from the initial capital; any required paid compliance infrastructure blocks live activation until separately authorised.
