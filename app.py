from __future__ import annotations

from pathlib import Path

import pandas as pd
import streamlit as st

from config import StrategyConfig
from engine import rank_universe
from nse_universe import discover_current_nse_symbols, load_saved_universe, save_universe
from research_data import ResearchDataConfig, load_universe
from research_policy import history_tier

st.set_page_config(
    page_title="MyStocks — India Research Radar",
    page_icon="📈",
    layout="wide",
    initial_sidebar_state="expanded",
)

st.title("📈 MyStocks — India Research Radar")
st.caption(
    "Full NSE-universe research. Evidence first — no guaranteed returns and no forced picks."
)

with st.sidebar:
    st.header("Research settings")
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

# The research workflow discovers the official NSE universe. The UI uses the
# same source and falls back to the last saved universe if NSE is temporarily
# unavailable.
try:
    symbols = discover_current_nse_symbols()
    save_universe(symbols)
    universe_source = "official NSE equity CSV"
except Exception as exc:
    symbols = load_saved_universe()
    universe_source = "last saved NSE universe"
    if not symbols:
        st.error(f"Could not discover the NSE universe: {exc}")
        st.stop()

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
