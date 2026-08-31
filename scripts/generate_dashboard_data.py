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


def build_stock(stock) -> dict:
    market = {}
    try:
        market = fetch_market_snapshot(stock.yahoo_symbol)
    except Exception as exc:
        print(f"market warning for {stock.yahoo_symbol}: {exc}")

    news = []
    try:
        news = fetch_latest_news(stock.name, limit=5)
    except Exception as exc:
        print(f"news warning for {stock.name}: {exc}")

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
        "price_history": compact_history(stock.yahoo_symbol),
        "thesis": list(stock.thesis),
        "risks": list(stock.risks),
        "kill_switches": list(stock.kill_switches),
        "official_links": [list(x) for x in stock.official_links],
        "live_flags": live_risk_flags(market),
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
