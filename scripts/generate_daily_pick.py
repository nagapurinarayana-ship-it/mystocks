from __future__ import annotations

import json
from dataclasses import replace
from datetime import datetime, time, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

from config import DEFAULT_UNIVERSE, StrategyConfig
from data import download_history, download_universe
from engine import features, rank_universe

OUTPUT = Path("daily-pick.json")
IST = ZoneInfo("Asia/Kolkata")
MARKET_OPEN = time(9, 15)


def _next_weekday(day):
    candidate = day
    while candidate.weekday() >= 5:
        candidate += timedelta(days=1)
    return candidate


def target_trading_date(now: datetime):
    """Date this pick is intended for.

    Before 09:15 IST on a weekday, the pick is for the current session. After
    the market has opened, a regeneration is treated as a preview for the next
    weekday session. This keeps manual/push-triggered afternoon runs from being
    mislabeled as a same-day pre-market pick.

    Exchange-specific holidays are not inferred here; the scheduled 08:00 IST
    run will refresh again on the next weekday.
    """
    day = now.date()
    if day.weekday() < 5 and now.time() < MARKET_OPEN:
        return day
    return _next_weekday(day + timedelta(days=1))


def nifty_regime() -> dict:
    """Conservative market-regime gate using only completed daily candles."""
    try:
        df = download_history("^NSEI", years=3, refresh=True)
        x = features(df)
        if x.empty:
            raise ValueError("Nifty feature history is empty")
        row = x.iloc[-1]
        close = float(row["Close"])
        sma20 = float(row["sma20"])
        sma50 = float(row["sma50"])
        positive = close > sma20 and sma20 > sma50
        return {
            "available": True,
            "positive": positive,
            "close": round(close, 2),
            "sma20": round(sma20, 2),
            "sma50": round(sma50, 2),
            "label": "Positive" if positive else "Cautious",
        }
    except Exception as exc:
        return {
            "available": False,
            "positive": False,
            "label": "Unavailable",
            "error": str(exc),
        }


def build_pick() -> dict:
    now = datetime.now(IST)
    for_date = target_trading_date(now)
    cfg = replace(StrategyConfig(), top_n=1)
    regime = nifty_regime()

    base = {
        "generated_at": now.isoformat(timespec="seconds"),
        "for_date": for_date.isoformat(),
        "market": "NSE India",
        "strategy": "Daily-candle momentum/trend setup; intended holding window up to 3 sessions",
        "target_pct": cfg.target_pct,
        "stop_pct": cfg.stop_pct,
        "max_hold_days": cfg.max_hold_days,
        "universe_size": len(DEFAULT_UNIVERSE),
        "market_regime": regime,
        "disclaimer": "Research signal only, not a guaranteed return. Skip the trade when opening conditions invalidate the setup.",
    }

    if not regime.get("positive"):
        return {
            **base,
            "status": "NO_TRADE",
            "reason": "Nifty trend gate is not positive, so the system is not forcing a long trade for this session.",
            "pick": None,
        }

    universe = download_universe(DEFAULT_UNIVERSE, years=10, refresh=True)
    ranked = rank_universe(universe, cfg)
    if ranked.empty:
        return {
            **base,
            "status": "NO_TRADE",
            "reason": "No liquid stock passed all signal, history, confidence and expected-value filters.",
            "pick": None,
        }

    row = ranked.iloc[0]
    symbol = str(row["symbol"])
    ref = float(row["close"])
    open_band = 0.0075
    pick = {
        "symbol": symbol,
        "display_symbol": symbol.removesuffix(".NS"),
        "reference_close": round(ref, 2),
        "acceptable_open_low": round(ref * (1 - open_band), 2),
        "acceptable_open_high": round(ref * (1 + open_band), 2),
        "reference_target": round(ref * (1 + cfg.target_pct), 2),
        "reference_stop": round(ref * (1 - cfg.stop_pct), 2),
        "execution_rule": "Consider only if the opening price is within the displayed opening zone. If it gaps outside the zone, skip rather than chase.",
        "target_rule": f"Target = actual entry × {1 + cfg.target_pct:.2f}",
        "stop_rule": f"Stop = actual entry × {1 - cfg.stop_pct:.2f}",
        "historical_win_rate": round(float(row["win_probability"]) * 100, 1),
        "lower95_win_rate": round(float(row["win_probability_lower95"]) * 100, 1),
        "samples": int(row["samples"]),
        "expected_value_pct": round(float(row["expected_value"]) * 100, 2),
        "rsi14": round(float(row["rsi"]), 1),
        "volume_ratio": round(float(row["vol_ratio"]), 2),
        "return_5d_pct": round(float(row["ret_5"]) * 100, 2),
        "return_20d_pct": round(float(row["ret_20"]) * 100, 2),
        "breakout20": bool(row["breakout20"]),
        "avg_volume20": int(float(row["avg_volume20"])),
        "score": round(float(row["score"]), 2),
        "reasons": [
            "Price is above its short-term trend filters and momentum is positive.",
            f"Volume is {float(row['vol_ratio']):.2f}× its 20-day average on the latest completed session.",
            f"Historical win rate is {float(row['win_probability']) * 100:.1f}% across {int(row['samples'])} resolved samples; 95% lower bound is {float(row['win_probability_lower95']) * 100:.1f}%.",
            f"Backtested expected value after configured round-trip costs is {float(row['expected_value']) * 100:.2f}% per qualifying setup.",
        ],
    }
    if bool(row["breakout20"]):
        pick["reasons"].insert(1, "Latest completed candle also closed above the prior 20-session high.")

    return {**base, "status": "PICK", "reason": "Top qualifying setup from the liquid-stock research universe.", "pick": pick}


def main() -> None:
    payload = build_pick()
    OUTPUT.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"Wrote {OUTPUT}: {payload['status']} for {payload['for_date']}")
    if payload.get("pick"):
        print(f"Pick: {payload['pick']['display_symbol']}")


if __name__ == "__main__":
    main()
