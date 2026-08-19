from __future__ import annotations

import streamlit as st

from config import DEFAULT_UNIVERSE, StrategyConfig
from data import download_universe
from engine import rank_universe

st.set_page_config(page_title="MyStocks — Research Radar", page_icon="📈", layout="wide")
st.title("📈 MyStocks — India Research Radar")
st.caption("Local research tool. A ~2% target is a testable objective, not a guaranteed return.")

with st.sidebar:
    st.header("Research settings")
    years = st.slider("Historical years", 5, 15, 10)
    target = st.number_input("Target %", 0.5, 5.0, 2.0, 0.1) / 100
    stop = st.number_input("Stop %", 0.5, 5.0, 1.0, 0.1) / 100
    hold = st.slider("Maximum holding days", 1, 10, 3)
    min_prob_lower95 = st.slider("Minimum 95% lower-bound probability", 0.40, 0.90, 0.50, 0.01)
    min_samples = st.number_input("Minimum comparable setups", 20, 500, 80, 10)
    refresh = st.button("Refresh market data")

cfg = StrategyConfig(
    target_pct=target,
    stop_pct=stop,
    max_hold_days=hold,
    min_probability_lower95=min_prob_lower95,
    min_samples=min_samples,
)

st.info(f"Universe: {len(DEFAULT_UNIVERSE)} liquid large-cap candidates · {years} years requested · target {target:.1%} · stop {stop:.1%}")

if st.button("Run daily scan", type="primary"):
    with st.spinner("Downloading / loading historical data and running the research engine..."):
        data = download_universe(DEFAULT_UNIVERSE, years=years, refresh=refresh)
        ranked = rank_universe(data, cfg)

    if ranked.empty:
        st.warning("No candidates passed every research threshold today. This is intentional: the engine does not manufacture three picks.")
    else:
        st.subheader("Top research candidates")
        cols = ["symbol", "close", "win_probability", "win_probability_lower95", "expected_value", "samples", "rsi", "vol_ratio", "ret_5", "ret_20"]
        display = ranked[cols].copy()
        display["win_probability"] = display["win_probability"].map(lambda x: f"{x:.1%}")
        display["win_probability_lower95"] = display["win_probability_lower95"].map(lambda x: f"{x:.1%}")
        display["expected_value"] = display["expected_value"].map(lambda x: f"{x:.2%}")
        display["rsi"] = display["rsi"].map(lambda x: f"{x:.1f}")
        display["vol_ratio"] = display["vol_ratio"].map(lambda x: f"{x:.2f}×")
        display["ret_5"] = display["ret_5"].map(lambda x: f"{x:.2%}")
        display["ret_20"] = display["ret_20"].map(lambda x: f"{x:.2%}")
        st.dataframe(display, use_container_width=True, hide_index=True)
        st.caption("Probability is the historical target-before-stop rate for the exact signal, with a conservative 95% lower bound shown separately. It is not a forecast guarantee.")
else:
    st.write("Set the research assumptions and run the daily scan. The first run downloads historical data and caches it locally.")

st.divider()
st.subheader("Validation before real-money use")
st.markdown("""
- Run rolling walk-forward tests across multiple market regimes.
- Add a survivorship-bias-free NSE universe and corporate-action-aware data.
- Add transaction costs, taxes and realistic slippage.
- Keep a completely untouched final out-of-sample period.
- Paper-trade every daily signal and measure live calibration.
""")
