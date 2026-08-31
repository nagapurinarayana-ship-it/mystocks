from __future__ import annotations

from pathlib import Path
from typing import Any

import pandas as pd
import streamlit as st

from config import StrategyConfig
from engine import rank_universe
from long_term_watchlist import (
    WATCHLIST,
    fetch_latest_news,
    fetch_market_snapshot,
    fetch_price_history,
    live_risk_flags,
)
from nse_universe import discover_current_nse_symbols, load_saved_universe, save_universe
from research_data import ResearchDataConfig, load_universe
from research_policy import history_tier

st.set_page_config(
    page_title="MyStocks — India Research Radar",
    page_icon="📈",
    layout="wide",
    initial_sidebar_state="expanded",
)


@st.cache_data(ttl=900, show_spinner=False)
def cached_market_snapshot(symbol: str) -> dict[str, Any]:
    return fetch_market_snapshot(symbol)


@st.cache_data(ttl=3600, show_spinner=False)
def cached_price_history(symbol: str, period: str) -> pd.DataFrame:
    return fetch_price_history(symbol, period=period)


@st.cache_data(ttl=1800, show_spinner=False)
def cached_news(company_name: str) -> list[dict[str, str]]:
    return fetch_latest_news(company_name, limit=8)


def _fmt_price(value: Any) -> str:
    try:
        if value is None or pd.isna(value):
            return "—"
        return f"₹{float(value):,.2f}"
    except (TypeError, ValueError):
        return "—"


def _fmt_number(value: Any, suffix: str = "") -> str:
    try:
        if value is None or pd.isna(value):
            return "—"
        return f"{float(value):,.2f}{suffix}"
    except (TypeError, ValueError):
        return "—"


def _fmt_market_cap(value: Any) -> str:
    try:
        if value is None or pd.isna(value):
            return "—"
        return f"₹{float(value) / 10_000_000:,.0f} Cr"
    except (TypeError, ValueError):
        return "—"


def render_long_term_watchlist() -> None:
    st.title("🧭 Long-Term Micro-cap Watchlist")
    st.caption(
        "A filing-first research workspace for the three selected sub-₹10 ideas. "
        "This public repo stores research/watchlist metadata only — no private purchase price, quantity or portfolio value."
    )

    st.warning(
        "Micro-caps can lose most or all of their value. Live price/fundamental fields below come from Yahoo Finance and "
        "may be delayed or incomplete. Material decisions should be verified against NSE/BSE/company filings linked below."
    )

    summary_cols = st.columns(len(WATCHLIST))
    for col, stock in zip(summary_cols, WATCHLIST):
        with col:
            try:
                snap = cached_market_snapshot(stock.yahoo_symbol)
            except Exception:
                snap = {}
            delta = snap.get("change_pct")
            delta_text = f"{delta:+.2f}%" if isinstance(delta, (int, float)) else None
            st.metric(
                f"#{stock.research_rank} {stock.name}",
                _fmt_price(snap.get("price")),
                delta=delta_text,
            )
            st.caption(
                f"{stock.exchange}:{stock.exchange_symbol} · manual research score "
                f"{stock.research_score:.1f}/10 · reviewed {stock.review_as_of}"
            )

    selected_name = st.selectbox(
        "Deep-dive company",
        [stock.name for stock in WATCHLIST],
        index=0,
    )
    stock = next(item for item in WATCHLIST if item.name == selected_name)

    try:
        snapshot = cached_market_snapshot(stock.yahoo_symbol)
    except Exception as exc:
        snapshot = {}
        st.info(f"Live market snapshot is temporarily unavailable: {exc}")

    st.subheader(f"#{stock.research_rank} · {stock.name}")
    m1, m2, m3, m4, m5, m6 = st.columns(6)
    m1.metric("Price", _fmt_price(snapshot.get("price")))
    m2.metric("Market cap", _fmt_market_cap(snapshot.get("market_cap")))
    m3.metric("P/E", _fmt_number(snapshot.get("trailing_pe")))
    m4.metric("P/B", _fmt_number(snapshot.get("price_to_book")))
    roe = snapshot.get("return_on_equity")
    m5.metric("ROE", _fmt_number(roe * 100 if isinstance(roe, (int, float)) else None, "%"))
    m6.metric("Debt / equity", _fmt_number(snapshot.get("debt_to_equity_pct"), "%"))

    low = snapshot.get("fifty_two_week_low")
    high = snapshot.get("fifty_two_week_high")
    if low is not None or high is not None:
        st.caption(f"52-week range from secondary market feed: {_fmt_price(low)} — {_fmt_price(high)}")

    chart_period = st.radio(
        "Price history",
        ["6mo", "1y", "5y", "max"],
        index=2,
        horizontal=True,
        key=f"history-{stock.key}",
    )
    try:
        history = cached_price_history(stock.yahoo_symbol, chart_period)
        if history.empty or "Close" not in history:
            st.info("Price history is not available from the secondary feed right now.")
        else:
            st.line_chart(history[["Close"]], height=280)
    except Exception as exc:
        st.info(f"Price history is temporarily unavailable: {exc}")

    left, right = st.columns(2)
    with left:
        st.markdown("#### Why it remains on the watchlist")
        for item in stock.thesis:
            st.markdown(f"- {item}")
        st.markdown("#### Known risks")
        for item in stock.risks:
            st.markdown(f"- {item}")

    with right:
        st.markdown("#### Thesis-breaking kill switches")
        for item in stock.kill_switches:
            st.markdown(f"- {item}")
        mechanical = live_risk_flags(snapshot)
        st.markdown("#### Live-feed mechanical warnings")
        if mechanical:
            for item in mechanical:
                st.warning(item)
        else:
            st.success("No mechanical warning was triggered by the currently available live-feed fields.")
        st.caption("This does not mean the company has no risks; filings remain the source of truth.")

    st.markdown("### Source-of-truth links")
    st.markdown(
        " · ".join(f"[{label}]({url})" for label, url in stock.official_links)
    )
    st.caption(
        "Use exchange/company/rating-agency disclosures for material facts. News aggregators are discovery tools, not proof."
    )

    st.markdown("### Latest headlines")
    st.caption("Secondary-source headline feed. Verify any material claim in the official links above before acting.")
    try:
        news = cached_news(stock.name)
    except Exception as exc:
        news = []
        st.info(f"Latest-headline feed is temporarily unavailable: {exc}")
    if not news:
        st.write("No recent headlines were returned by the feed.")
    else:
        for item in news:
            source = item.get("source") or "News source"
            published = item.get("published") or "date unavailable"
            st.markdown(f"- [{item['title']}]({item['url']}) — **{source}** · {published}")

    with st.expander("Long-term review discipline"):
        st.markdown(
            """
- Ignore daily price noise; review the business after material filings and at least annually.
- Never average down solely because the share price falls.
- Re-check promoter holding/pledge, auditor opinion, dilution, cash-flow conversion, debt and credit ratings.
- Treat a business-model change, insolvency/restructuring event or repeated unexplained dilution as a fresh investment thesis.
- A low share price is not the same thing as a low valuation.
            """
        )


def render_short_term_research() -> None:
    st.title("📈 MyStocks — India Research Radar")
    st.caption(
        "Full NSE-universe short-term research. Evidence first — no guaranteed returns and no forced picks."
    )

    with st.sidebar:
        st.header("Short-term research settings")
        years = st.slider("Historical years", 5, 15, 10)
        target = st.number_input("Target %", 0.5, 5.0, 2.0, 0.1) / 100
        stop = st.number_input("Stop %", 0.5, 5.0, 1.0, 0.1) / 100
        hold = st.slider("Maximum holding days", 1, 10, 3)
        min_prob_lower95 = st.slider("Minimum 95% lower-bound probability", 0.40, 0.90, 0.50, 0.01)
        min_samples = st.number_input("Minimum comparable setups", 20, 500, 80, 10)
        refresh = st.checkbox("Refresh market data", value=False)

    cfg = StrategyConfig(
        target_pct=target,
        stop_pct=stop,
        max_hold_days=hold,
        min_probability_lower95=min_prob_lower95,
        min_samples=min_samples,
    )

    try:
        symbols = discover_current_nse_symbols()
        save_universe(symbols)
        universe_source = "official NSE equity CSV"
    except Exception as exc:
        symbols = load_saved_universe()
        universe_source = "last saved NSE universe"
        if not symbols:
            st.error(f"Could not discover the NSE universe: {exc}")
            return

    st.info(
        f"**Universe:** {len(symbols):,} NSE equities · **History:** {years} years · "
        f"**Target/stop:** +{target:.1%} / -{stop:.1%} · **Source:** {universe_source}"
    )

    run_scan = st.button("🔎 Run full-universe research scan", type="primary", use_container_width=True)

    if run_scan:
        with st.spinner(
            f"Loading up to {len(symbols):,} NSE symbols in controlled batches and running the research engine..."
        ):
            data = load_universe(
                symbols,
                ResearchDataConfig(years=max(years, 10), refresh=refresh, min_rows=1),
            )

            coverage_rows = []
            for symbol in symbols:
                df = data.get(symbol)
                if df is None or df.empty:
                    coverage_rows.append(
                        {"symbol": symbol, "observations": 0, "history_years": 0.0, "status": "no_data"}
                    )
                    continue
                history_years = max(0.0, (df.index.max() - df.index.min()).days / 365.25)
                tier = history_tier(history_years)
                coverage_rows.append(
                    {
                        "symbol": symbol,
                        "observations": len(df),
                        "history_years": round(history_years, 2),
                        "status": "research_eligible" if len(df) >= 252 else tier.name,
                    }
                )

            coverage = pd.DataFrame(coverage_rows)
            ranked = rank_universe(data, cfg)

        tab1, tab2, tab3 = st.tabs(["🏆 Candidates", "🌐 Universe coverage", "📚 Methodology"])

        with tab1:
            if ranked.empty:
                st.warning(
                    "No candidates passed every research threshold today. This is intentional: "
                    "the engine never manufactures picks when evidence is weak."
                )
            else:
                st.subheader("Top research candidates")
                cols = [
                    "symbol", "close", "win_probability", "win_probability_lower95",
                    "expected_value", "samples", "rsi", "vol_ratio", "ret_5", "ret_20",
                ]
                display = ranked[[c for c in cols if c in ranked.columns]].copy()
                if "win_probability" in display:
                    display["win_probability"] = display["win_probability"].map(lambda x: f"{x:.1%}")
                if "win_probability_lower95" in display:
                    display["win_probability_lower95"] = display["win_probability_lower95"].map(lambda x: f"{x:.1%}")
                if "expected_value" in display:
                    display["expected_value"] = display["expected_value"].map(lambda x: f"{x:.2%}")
                if "rsi" in display:
                    display["rsi"] = display["rsi"].map(lambda x: f"{x:.1f}")
                if "vol_ratio" in display:
                    display["vol_ratio"] = display["vol_ratio"].map(lambda x: f"{x:.2f}×")
                if "ret_5" in display:
                    display["ret_5"] = display["ret_5"].map(lambda x: f"{x:.2%}")
                if "ret_20" in display:
                    display["ret_20"] = display["ret_20"].map(lambda x: f"{x:.2%}")
                st.dataframe(display, use_container_width=True, hide_index=True)
                st.caption(
                    "Probability is the historical target-before-stop rate for the exact signal. "
                    "The 95% lower bound is shown separately as a conservative confidence measure."
                )

        with tab2:
            st.subheader("100% discovered-universe accounting")
            counts = coverage["status"].value_counts().rename_axis("status").reset_index(name="stocks")
            c1, c2, c3 = st.columns(3)
            c1.metric("Discovered", f"{len(coverage):,}")
            c2.metric("With usable data", f"{(coverage.observations > 0).sum():,}")
            c3.metric("Research eligible", f"{(coverage.status == 'research_eligible').sum():,}")
            st.dataframe(counts, use_container_width=True, hide_index=True)
            st.download_button(
                "Download complete universe status CSV",
                coverage.to_csv(index=False).encode("utf-8"),
                "mystocks_nse_universe_status.csv",
                "text/csv",
            )
            st.caption(
                "Limited-history and no-data symbols remain visible. They are not promoted into statistical rankings "
                "until enough evidence exists."
            )

        with tab3:
            st.subheader("Research guardrails")
            st.markdown(
                """
- Entry is the next-session open after the signal.
- Default target is +2% and stop is -1% with a maximum 3-session hold.
- If target and stop occur in the same candle, the result is conservatively treated as a loss.
- Rankings require enough comparable historical setups and a conservative 95% lower probability bound.
- Chronological / walk-forward validation is preferred over random train/test splits.
- Limited-history stocks remain in the universe but are excluded from mature statistical rankings.
- Costs and slippage are included in expected-value calculations.
- A research result is evidence, not a promise of future returns.
                """
            )
    else:
        st.subheader("Ready for the full NSE universe")
        st.write(
            "The dashboard is configured to account for every currently discovered NSE equity. "
            "Run the scan to download data in controlled batches, classify every symbol, and rank only the stocks "
            "with sufficient evidence."
        )
        if Path("data/research_summary.csv").exists():
            st.success("Existing research output detected in the local data directory.")


with st.sidebar:
    st.title("MyStocks")
    workspace = st.radio(
        "Workspace",
        ["Long-term watchlist", "Short-term research radar"],
        index=0,
    )
    st.caption("Research tooling only — not a guarantee of returns.")

if workspace == "Long-term watchlist":
    render_long_term_watchlist()
else:
    render_short_term_research()
