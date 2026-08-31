from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

from long_term_watchlist import (
    WATCHLIST,
    fetch_latest_news,
    fetch_market_snapshot,
    fetch_price_history,
    live_risk_flags,
)

OUTPUT = Path("dashboard-data.json")
QUOTE_MISMATCH_THRESHOLD = 0.12


def compact_history(symbol: str) -> list[float]:
    try:
        frame = fetch_price_history(symbol, period="6mo")
        if frame.empty or "Close" not in frame:
            return []
        closes = frame["Close"].dropna().astype(float)
        if len(closes) > 90:
            step = max(1, len(closes) // 90)
            closes = closes.iloc[::step].tail(90)
        return [round(float(v), 4) for v in closes]
    except Exception as exc:
        print(f"history warning for {symbol}: {exc}")
        return []


def reconcile_market_with_history(market: dict, history: list[float]) -> dict:
    """Prefer actual adjusted trading history over potentially stale quote metadata.

    Some thinly traded Indian micro-caps can have stale/corporate-action-inconsistent
    values in Yahoo's quote-info endpoint. The adjusted daily history is used for
    displayed price/change. If quote metadata disagrees materially, price-derived
    fundamentals are suppressed rather than showing a confidently wrong number.
    """
    reconciled = dict(market or {})
    if not history:
        reconciled.setdefault("price_source", "Yahoo Finance quote metadata")
        return reconciled

    history_price = float(history[-1])
    history_previous = float(history[-2]) if len(history) >= 2 else None
    info_price = reconciled.get("price")

    mismatch = None
    try:
        info_price_num = float(info_price) if info_price is not None else None
        if info_price_num and history_price:
            mismatch = abs(info_price_num / history_price - 1.0)
    except (TypeError, ValueError, ZeroDivisionError):
        info_price_num = None

    reconciled["price"] = history_price
    reconciled["previous_close"] = history_previous
    reconciled["price_source"] = "Yahoo Finance adjusted trading history"

    if history_previous not in (None, 0):
        reconciled["change_pct"] = (history_price / history_previous - 1.0) * 100.0
    else:
        reconciled["change_pct"] = None

    if mismatch is not None and mismatch > QUOTE_MISMATCH_THRESHOLD:
        reconciled["data_quality_warning"] = (
            f"Quote metadata differed {mismatch:.0%} from adjusted trading history. "
            "The dashboard uses trading-history price/change and suppresses affected price-derived ratios."
        )
        for field in (
            "market_cap",
            "trailing_pe",
            "price_to_book",
            "fifty_two_week_low",
            "fifty_two_week_high",
        ):
            reconciled[field] = None
    else:
        reconciled["data_quality_warning"] = None

    return reconciled


def build_stock(stock) -> dict:
    market = {}
    try:
        market = fetch_market_snapshot(stock.yahoo_symbol)
    except Exception as exc:
        print(f"market warning for {stock.yahoo_symbol}: {exc}")

    history = compact_history(stock.yahoo_symbol)
    market = reconcile_market_with_history(market, history)

    news = []
    try:
        news = fetch_latest_news(stock.name, limit=5)
    except Exception as exc:
        print(f"news warning for {stock.name}: {exc}")

    flags = live_risk_flags(market)
    if market.get("data_quality_warning"):
        flags.insert(0, f"Market-data quality: {market['data_quality_warning']}")

    return {
        "key": stock.key,
        "name": stock.name,
        "exchange": stock.exchange,
        "exchange_symbol": stock.exchange_symbol,
        "yahoo_symbol": stock.yahoo_symbol,
        "research_rank": stock.research_rank,
        "research_score": stock.research_score,
        "review_as_of": stock.review_as_of,
        "market": market,
        "price_history": history,
        "thesis": list(stock.thesis),
        "risks": list(stock.risks),
        "kill_switches": list(stock.kill_switches),
        "official_links": [list(x) for x in stock.official_links],
        "live_flags": flags,
        "news": news,
    }


def main() -> None:
    payload = {
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "market_data_status": "live-refresh",
        "note": "Secondary market/news fields are automatically refreshed. Material facts must still be verified in official filings.",
        "stocks": [build_stock(stock) for stock in WATCHLIST],
    }
    OUTPUT.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"Wrote {OUTPUT} with {len(payload['stocks'])} stocks")


if __name__ == "__main__":
    main()
