# MyStocks Intraday Radar and Automated Trading — Implementation Plan

## Product decision

Build MyStocks toward **fully automated NSE cash-equity trading**: live market-data ingestion, strategy selection, cash/risk sizing, automatic entries, broker-side protective exits, position monitoring, reconciliation and automatic exits. The intended end state requires no manual trade-by-trade order entry. However, live execution must remain disabled until the strategy demonstrates a durable after-cost edge in robust out-of-sample tests and forward paper operation, and until the user selects a broker and all broker/exchange, static-IP, authentication, security and compliance requirements are verified. Until then, the production service may run live-market scans and autonomous paper trading only. Preserve the existing long-term watchlist and short-term daily research engine; this is a separate capability.

## Current implementation status — feature branch

The following code has been added to `feature/intraday-automated-trading-foundation`. It is not merged to `main`.

**Implemented in code**
- Upstox V3 Protobuf WebSocket adapter using `websocket-client` with CA and hostname verification explicitly enabled, bounded reconnects, 401 fail-stop, LTPC-only subscription, NSE symbol mapping and IST timestamps. It first obtains a one-time socket URL from Upstox's HTTPS market-data authorization endpoint; the bearer token is not sent on the WebSocket handshake. The pinned Upstox SDK supplies its official V3 Protobuf schema; its built-in V3 feeder transport is not used because its source disables certificate and hostname verification. Full Market Quotes V3 REST snapshots supply shortlist depth.
- BOD instrument-master parser and reconciliation that retains an include/exclude reason for every broker-distributed NSE instrument row.
- Tick validation for timestamps, price, spread, quote depth and circuit bands; five-minute completed-bar construction; session VWAP from completed trade ticks only. A quote is rejected if its own snapshot is recent but its last trade time is stale or missing. Multi-bucket stream gaps discard the partial candle and reset that symbol's history/VWAP context instead of fabricating a completed candle.
- Two explainable long-only strategies: VWAP momentum and opening-range breakout. The live scanner returns at most three fresh candidates and suppresses duplicates and stale data.
- Top-of-book depth validation for up to three shortlisted candidates, including minimum bid/ask quantity, spread, price drift and circuit-proximity checks. REST snapshots refresh every five seconds while candidates remain active; the WebSocket trade timestamp must also remain fresh per symbol.
- ₹1,000 cash-only capital policy, Decimal whole-share sizing, explicit broker fee configuration, automatic paper entry/exit simulation, same-bar stop-first handling, next-bar entry expiry, end-of-session entry cutoff and paper square-off.
- SQLite paper audit ledger for signals, closed trades and feed/system events, plus a versioned paper-account checkpoint preserving cash, daily and cumulative realised P&L, position, stop/target, pending state, fee schedule and halt state across process restarts. Corrupt state or fee-schedule changes fail closed; pending entries are cancelled on restart because missed five-minute bars cannot safely be reconstructed. A one-second watchdog monitors the held symbol even when the WebSocket is silent; stale held-symbol data or a multi-bucket gap halts paper execution, preserves the open position as unresolved and prevents synthetic exits or new entries. The dashboard displays the halt and unresolved position.
- Upstox V3 historical five-minute candle adapter, chunked historical retrieval, one-symbol OHLCV backtest, after-cost metrics and JSON report output.
- A separate Intraday Radar dashboard workspace showing local feed status, signals, paper trades and the latest backtest report.
- Tests and a feature-branch CI workflow; existing stock research engines remain separate.

**Not yet implemented or verified**
- No broker has been selected. Upstox is the current market-data adapter candidate only; it is not a commitment to open or move a brokerage account.
- No live Upstox session has been authenticated or tested in this environment because no access token was provided. The user must create/authorise their own developer app and set the token locally.
- No real account funds, positions, trades or fees have been read. Paper fills remain disabled unless the full selected-broker fee schedule is explicitly configured.
- Only two strategies are implemented; unusual-volume, reversal and sector-leadership strategies are future work.
- The historical backtest is a single-symbol five-minute OHLCV model. It estimates session VWAP using typical-price-times-volume; it is not trade-level VWAP, an all-NSE point-in-time test, or a full market-impact, queue-priority and partial-fill simulator.
- No 30-session forward paper validation has been completed. No live broker order API, auto-buy, broker-side stop, order reconciliation, fund transfer or withdrawal feature exists. The live execution gate remains hard-disabled. A halted paper position is intentionally not auto-resumed or auto-closed; it requires manual review. An operator-controlled, auditable recovery/reset workflow is still to be designed.
- The runner is a local foreground process; GitHub Actions is used for tests, not as a continuous market-data service. NSE holiday-calendar integration and always-on production hosting are still open items. Restored open paper positions do not receive full historical bar catch-up after downtime; the watchdog therefore preserves them as unresolved and halts paper activity until manual review.

**Run the local scanner**
1. Install the optional adapter: `pip install -r requirements-intraday.txt`.
2. Complete the official broker OAuth flow and set `UPSTOX_ACCESS_TOKEN` in the local process environment. Never place tokens in the repository, GitHub variables used for public workflows, logs, or chat.
3. Start the local feed process during market hours: `python scripts/run_intraday_radar.py`.
4. Keep the process running. The dashboard reads its local SQLite ledger; it cannot start or keep the feed process alive.

**Run a historical single-symbol backtest**
1. Configure all eight `MYSTOCKS_PAPER_FEE_*` environment variables using the selected broker's current tariff and an explicit slippage assumption. The code intentionally supplies no default broker fee schedule.
2. Run, for example: `python scripts/run_intraday_backtest.py --symbol RELIANCE --from-date 2026-09-01 --to-date 2026-10-31 --strategy vwap_momentum`.
3. Inspect the JSON report in `data/intraday-backtests`, including its data-quality counts and execution assumptions.

The latest completed market-data/safety CI run on commit `aa4e83b` passed **112 tests**, including Python compile checks and installation of the pinned Upstox SDK, Protobuf frame decoding, verified-TLS context, OAuth socket-URL validation and stale-position watchdog regressions. These use deterministic fixtures and local WebSocket fakes; no authenticated Upstox session or real-market execution path has been exercised in this workspace. SEO Quality passed on the same feature head.

---

## Non-negotiable safety boundary

- Default mode is `research`; paper mode is opt-in; live mode is unavailable unless a deliberate, authenticated, audited enablement process is completed.
- No broker order-placement call may be reachable in research or paper mode.
- No live order placement, modification, cancellation, square-off, fund transfer, or withdrawal is enabled by this plan.
- Never store broker passwords, TOTP seeds, API secrets, access tokens, or static-IP credentials in Git, Streamlit config committed to Git, logs, workflow artifacts, or public research outputs.
- Live enablement must require an explicit user action, fresh broker authentication, verified broker/account permissions, configured risk limits, and a visible confirmation showing symbol, side, quantity, order type, and maximum estimated exposure.
- Add a global kill switch and a fail-closed execution gate. If mode, credentials, market data, risk state, broker state, or compliance state is unknown/stale, reject execution.
- Do not promise returns or describe model scores as probabilities of profit unless calibrated and validated.

## Architecture

Create a dedicated `intraday/` package. Do not alter the existing `engine.py`, `backtest.py`, long-term watchlist, or current research workflows as part of this feature.

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
- The current first release uses timestamped live ticks and completed 5-minute bars; 1-minute candles may be added later after latency and data-quality validation. Require trades/volume and candidate bid/ask/depth. Live VWAP is calculated from completed trade ticks; historical OHLCV tests use an explicitly labelled typical-price proxy.
- Existing Yahoo daily data is not an intraday execution feed. Select a broker/market-data provider only after checking API access, historical minute data, retention, latency, licensing, static-IP requirements, rate limits, support and total cost.
- Keep a vendor-neutral market-data contract so a broker can be selected later. Do not use fixture or synthetic data to claim real-market performance.

### Strategy and opportunity selection

Planned strategy family: opening-range breakout, VWAP momentum, unusual volume with price confirmation, momentum reversal, and sector leadership. The current first implementation contains only VWAP momentum and opening-range breakout. Add other strategies only as independent modules with separate after-cost out-of-sample evidence. Keep all signals explainable and persist input timestamps and feature values.

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
- No algorithm, backtest or live execution setting may promise or imply guaranteed profits, fixed daily income or assured capital preservation. 'Sustainable' means only that the measured net expectancy and operational controls continue to hold over sufficiently varied unseen market periods; it is never certain.

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
- Execution ambition: fully automatic entries, protective exits and position management as the end state; live order placement currently hard-disabled pending evidence, broker selection and compliance approval.
- Broker: undecided.
- Market-data provider: undecided.
- Initial strategy direction: long-only; no leverage/F&O.
- Starting external capital: ₹1,000 only; retained realised net profits may compound, but no external top-ups are assumed.
- Paper guardrails: 0.5% planned risk per trade, 1% daily loss limit including estimated costs, and one open position maximum; these must be tested and may result in no-trade outcomes.
- Recurring data/hosting spend target: ₹0 from the initial capital; any required paid compliance infrastructure blocks live activation until separately authorised.


## Recommended design: fully automatic target with a gated live rollout

### Decision

The intended end state is an autonomous, long-only NSE cash-equity system that can:
1. Receive live NSE cash-market updates during market hours and maintain a healthy/stale-feed state.
2. Scan the eligible universe and select up to three explainable opportunities, or none.
3. Calculate conditional entry, stop, targets, whole-share quantity, estimated costs and rupee risk before every order.
4. Automatically submit eligible entries through the selected broker adapter when live mode is separately authorised.
5. Immediately place/verify broker-supported protective exits and manage partial fills, rejected orders, gaps, price bands and uncertain order states.
6. Monitor positions and automatically exit when the strategy invalidates, the stop/target condition occurs, risk limits trigger, or the session cutoff is reached.
7. Reconcile orders, trades, positions and funds against broker records; maintain a durable audit ledger and P&L after all charges.
8. Stop opening new positions and invoke the configured safe-state procedure on stale data, lost connection, broker mismatch, failed protective-order confirmation, daily loss limit or global kill switch.

The rollout is deliberately staged: live-market autonomous paper trading first; then read-only broker reconciliation; then a separate live execution release only after evidence and regulatory readiness. The initial implementation must not silently fall back from live to paper or claim an order was placed unless the broker confirms it.

### Initial market-data provider candidate

Evaluate **Upstox Market Data Feed V3 plus Full Market Quotes V3 as the first adapter candidate**, not as a mandatory broker switch:
- Upstox currently states that its trading and data APIs are free of API subscription charges.
- Its V3 WebSocket feed provides real-time LTPC updates. The normal individual limit is 5,000 LTPC keys when that mode is used alone; mixed subscription categories have lower combined limits. The implementation therefore stays LTPC-only on the WebSocket and uses the Full Market Quotes V3 REST endpoint for top-five bid/ask depth and circuit limits on the maximum-three shortlist. The REST endpoint supports up to 500 instrument keys per request, so the three-candidate request remains comfortably within the documented batch size.
- Its V3 historical candles support minute intervals from 1 through 300; minute history is available from January 2022 with a maximum one-month retrieval window for 1–15 minute intervals.
- A free API is not an SLA and does not remove brokerage, statutory charges, connectivity, or infrastructure costs. Measure feed gaps, latency and reconnect behaviour in paper operation.
- Do not open or switch a broker account solely because of this document. First check whether the user's existing broker already provides an adequate free live-data API.

Zerodha's currently published retail Kite Connect pricing is ₹500 per month for real-time WebSocket and historical data; its free personal tier does not include either. That is unsuitable for a ₹1,000 starting account unless the user already has a separately justified subscription.

### Reliable ingestion and scan design

- At market open, load the latest broker instrument master; reconcile NSE equity series, status, symbol/token mapping, tick size, price bands and corporate actions. Preserve a row and exclusion reason for every discovered symbol.
- Broad scan: subscribe to LTPC for eligible instruments; do not poll individual quote endpoints repeatedly.
- Candidate scan: compute 1-minute and 5-minute bars with timestamped tick data, and reconcile bars with the provider's candle endpoint. Use 15-minute confirmation and daily trend context to avoid reacting to every tick.
- Candidate enrichment: query Full Market Quotes V3 REST snapshots for best bid/ask depth and circuit limits only for the shortlist and any held position. Keep the broad WebSocket LTPC-only so the 5,000-key single-category limit remains available.
- Filters: exclude stale or halted data, surveillance/price-band risks, weak turnover, wide spreads, thin depth, and symbols whose one-share notional exceeds available cash. Never select penny stocks merely because the share price is low.
- First strategies: keep it deliberately simple—(1) daily/15-minute trend plus relative-strength pullback, and (2) opening-range/VWAP continuation with liquidity and volume confirmation. Keep them independently measured; do not blend them into an opaque model.
- Rank at most three. "No trade" is a valid daily outcome.
- Recompute signals only on completed candles; show live LTP separately. Do not treat an unfinished candle as a confirmed signal.
- On disconnect, stale timestamps, market-status mismatch, instrument-master mismatch, or candle reconciliation failure, show feed degraded and suppress new opportunities. Reconnect with bounded backoff, resubscribe, obtain a fresh snapshot, reconcile candle gaps, then mark healthy.
- Do not rely on GitHub Actions as a live feed process. Run one persistent market-hours worker on an available always-on device. With a zero-recurring-cost target, start on a user's own PC; the dashboard must clearly show offline whenever that process is not running. A cloud worker/VPS/static egress IP is a separate cost decision.

### ₹1,000 capital economics

- Do not allocate any of the ₹1,000 to monthly market-data subscriptions, VPS or static-IP infrastructure.
- Upstox's published equity intraday brokerage is ₹20 per executed order or 0.1% of order value, whichever is lower, with statutory charges added. At ₹1,000 notional, brokerage alone is about ₹1 per side; taxes/fees also apply. Actual charges must be recalculated from the broker's current tariff and actual fills.
- Frequent delivery trading is particularly uneconomic on a small account where the broker charges per order and DP charges on delivery sells. Compare the selected broker's exact charges before enabling any trade workflow.
- Spread and slippage are additional real costs. A candidate whose expected move cannot clear all-in costs is rejected.
- Cash-only whole shares; one open position maximum. No leverage, MTF, F&O, short selling, averaging down, or low-liquidity price chasing.
- The existing conservative paper limits (0.5% planned risk per trade; 1% daily loss limit; one open position) are hard research guardrails, not a claim that every ₹1,000 portfolio can place a valid trade. If one share cannot fit the risk budget after estimated costs, show no trade.
- Net P&L is only recognised after actual charges; unrealised gain is not withdrawable profit. No automated cash movement.

### Live auto-ordering gate

The intended product is fully automatic, but this is a separate activation milestone—not an automatic consequence of passing unit tests. First confirm the chosen broker and exact account/API terms. NSE/SEBI retail-algo requirements and broker procedures apply. Current exchange guidance requires broker documentation/registration for Client Direct API retail algo access. Static-IP and hosting requirements must be confirmed with the selected broker for the chosen client API architecture; WebSocket market-data access can have different requirements from order placement.

Before any live order endpoint is enabled, require:
- Broker-confirmed Client Direct API/algo eligibility and exchange registration/tagging requirements.
- Registered static IP and reliable always-on execution host, with a documented cost that is not funded out of the ₹1,000 trading capital.
- Fresh broker authentication/session lifecycle, secret isolation and audit trail.
- Verified order-state reconciliation, idempotency, partial fills, rejects, circuit/price-band handling and broker-side protective order behaviour.
- At least 30 market sessions of paper operation and independent review of net outcomes, drawdown and operational failure tests.
- A separate explicit authorisation step by the user. The execution gate must remain closed until this separate change is approved.

