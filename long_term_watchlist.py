from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from typing import Any
from urllib.parse import quote_plus
import xml.etree.ElementTree as ET

import pandas as pd
import requests


@dataclass(frozen=True)
class WatchStock:
    key: str
    name: str
    yahoo_symbol: str
    exchange_symbol: str
    exchange: str
    research_rank: int
    research_score: float
    review_as_of: str
    thesis: tuple[str, ...]
    risks: tuple[str, ...]
    kill_switches: tuple[str, ...]
    official_links: tuple[tuple[str, str], ...]


WATCHLIST: tuple[WatchStock, ...] = (
    WatchStock(
        key="nila",
        name="Nila Infrastructures",
        yahoo_symbol="NILAINFRA.NS",
        exchange_symbol="NILAINFRA",
        exchange="NSE",
        research_rank=1,
        research_score=7.0,
        review_as_of="2026-08-31",
        thesis=(
            "Established infrastructure/EPC business with a long operating history.",
            "Promoter ownership has historically been comparatively stable with no pledge in the latest manual review.",
            "Leverage has reduced materially versus older balance-sheet periods.",
            "Small market capitalisation leaves room for upside if order execution and cash conversion improve.",
        ),
        risks=(
            "Government/project concentration can make revenue and order inflow lumpy.",
            "Operating cash flow and working-capital conversion need close annual review.",
            "Project cancellations or execution delays can quickly weaken a micro-cap thesis.",
        ),
        kill_switches=(
            "Promoter pledge appears or promoter ownership falls sharply without a clear explanation.",
            "Auditor issues a qualified/adverse/disclaimer opinion or raises going-concern concerns.",
            "Operating cash flow stays materially negative while reported profit remains positive for two annual periods.",
            "Debt rises sharply without corresponding executable order-book growth.",
        ),
        official_links=(
            ("NSE quote", "https://www.nseindia.com/get-quotes/equity?symbol=NILAINFRA"),
            ("NSE corporate filings", "https://www.nseindia.com/companies-listing/corporate-filings-announcements"),
            ("Company investor site", "https://www.nilainfra.com/"),
            ("CARE Ratings", "https://www.careratings.com/"),
        ),
    ),
    WatchStock(
        key="ashapuri",
        name="Ashapuri Gold Ornament",
        yahoo_symbol="542579.BO",
        exchange_symbol="542579",
        exchange="BSE",
        research_rank=2,
        research_score=6.9,
        review_as_of="2026-08-31",
        thesis=(
            "B2B gold-jewellery manufacturer with a real operating history and recent earnings momentum.",
            "Balance sheet was debt-light in the latest manual review.",
            "Small market capitalisation offers asymmetric upside if margins and cash flow remain durable.",
        ),
        risks=(
            "Jewellery manufacturing is inventory- and working-capital-intensive.",
            "Gold-price moves can distort inventory values and funding requirements.",
            "Historical equity issuance means future dilution must be watched carefully.",
        ),
        kill_switches=(
            "Large new dilution/warrants without a clearly value-accretive use of funds.",
            "Promoter pledge appears or promoter stake falls materially.",
            "Inventory/receivables rise much faster than sales for repeated periods.",
            "Accounting profit grows while operating cash flow remains persistently negative.",
        ),
        official_links=(
            ("BSE company page", "https://www.bseindia.com/stock-share-price/ashapuri-gold-ornament-ltd/agol/542579/"),
            ("BSE corporate announcements", "https://www.bseindia.com/corporates/ann.html"),
            ("Company investor site", "https://ashapurigold.com/"),
        ),
    ),
    WatchStock(
        key="madhav",
        name="Madhav Infra Projects",
        yahoo_symbol="MADHAVIPL.NS",
        exchange_symbol="MADHAVIPL",
        exchange="NSE",
        research_rank=3,
        research_score=6.2,
        review_as_of="2026-08-31",
        thesis=(
            "Infrastructure business with renewable/solar exposure.",
            "Promoter ownership has historically been high and stable in the latest manual review.",
            "A successful mix of EPC execution and contracted renewable assets can improve long-run earnings quality.",
        ),
        risks=(
            "More leverage and contingent-liability complexity than the other two watchlist names.",
            "Construction cash flows are lumpy and sensitive to collections and project execution.",
            "Accounting disclosures around deferred tax and group entities require continued attention.",
        ),
        kill_switches=(
            "Material credit-rating downgrade, default or sharp deterioration in debt coverage.",
            "Contingent liabilities crystallise into a material cash obligation.",
            "Auditor qualification or unresolved accounting issue becomes material.",
            "Promoter pledge appears or promoter ownership deteriorates sharply.",
        ),
        official_links=(
            ("NSE quote", "https://www.nseindia.com/get-quotes/equity?symbol=MADHAVIPL"),
            ("NSE corporate filings", "https://www.nseindia.com/companies-listing/corporate-filings-announcements"),
            ("CARE Ratings", "https://www.careratings.com/"),
        ),
    ),
)


def _number(value: Any) -> float | None:
    if value is None:
        return None
    try:
        value = float(value)
    except (TypeError, ValueError):
        return None
    if pd.isna(value):
        return None
    return value


def fetch_market_snapshot(symbol: str) -> dict[str, Any]:
    """Fetch a best-effort live snapshot from Yahoo Finance.

    Yahoo Finance is a convenience/secondary market-data source. The UI labels it
    accordingly and links users to exchange/company filings for material facts.
    """
    import yfinance as yf

    ticker = yf.Ticker(symbol)
    info: dict[str, Any] = {}
    try:
        info = ticker.info or {}
    except Exception:
        info = {}

    history = pd.DataFrame()
    try:
        history = ticker.history(period="5d", auto_adjust=False)
    except Exception:
        pass

    price = _number(info.get("currentPrice") or info.get("regularMarketPrice"))
    previous_close = _number(info.get("previousClose") or info.get("regularMarketPreviousClose"))
    if price is None and not history.empty and "Close" in history:
        price = _number(history["Close"].dropna().iloc[-1])
    if previous_close is None and len(history) >= 2 and "Close" in history:
        previous_close = _number(history["Close"].dropna().iloc[-2])

    change_pct = None
    if price is not None and previous_close not in (None, 0):
        change_pct = (price / previous_close - 1.0) * 100.0

    return {
        "price": price,
        "previous_close": previous_close,
        "change_pct": change_pct,
        "market_cap": _number(info.get("marketCap")),
        "trailing_pe": _number(info.get("trailingPE")),
        "price_to_book": _number(info.get("priceToBook")),
        "return_on_equity": _number(info.get("returnOnEquity")),
        "debt_to_equity_pct": _number(info.get("debtToEquity")),
        "operating_cash_flow": _number(info.get("operatingCashflow")),
        "free_cash_flow": _number(info.get("freeCashflow")),
        "fifty_two_week_low": _number(info.get("fiftyTwoWeekLow")),
        "fifty_two_week_high": _number(info.get("fiftyTwoWeekHigh")),
        "currency": info.get("currency") or "INR",
        "fetched_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
    }


def fetch_price_history(symbol: str, period: str = "5y") -> pd.DataFrame:
    import yfinance as yf

    frame = yf.Ticker(symbol).history(period=period, auto_adjust=True)
    if frame.empty:
        return pd.DataFrame(columns=["Close"])
    frame = frame.copy()
    frame.index = pd.to_datetime(frame.index).tz_localize(None)
    return frame


def google_news_rss_url(company_name: str) -> str:
    query = quote_plus(f'"{company_name}" stock India')
    return f"https://news.google.com/rss/search?q={query}&hl=en-IN&gl=IN&ceid=IN:en"


def parse_google_news_rss(xml_text: str, limit: int = 8) -> list[dict[str, str]]:
    root = ET.fromstring(xml_text)
    items: list[dict[str, str]] = []
    for item in root.findall("./channel/item"):
        title = (item.findtext("title") or "").strip()
        link = (item.findtext("link") or "").strip()
        source = (item.findtext("source") or "").strip()
        published_raw = (item.findtext("pubDate") or "").strip()
        if not title or not link:
            continue
        published = published_raw
        if published_raw:
            try:
                dt = parsedate_to_datetime(published_raw)
                published = dt.astimezone(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
            except (TypeError, ValueError, OverflowError):
                pass
        items.append({"title": title, "url": link, "source": source, "published": published})
        if len(items) >= limit:
            break
    return items


def fetch_latest_news(company_name: str, limit: int = 8, timeout: int = 12) -> list[dict[str, str]]:
    headers = {"User-Agent": "Mozilla/5.0 MyStocksResearch/1.0"}
    response = requests.get(google_news_rss_url(company_name), headers=headers, timeout=timeout)
    response.raise_for_status()
    return parse_google_news_rss(response.text, limit=limit)


def live_risk_flags(snapshot: dict[str, Any]) -> list[str]:
    """Return only mechanical warnings from fields available in the live feed.

    These do not replace the manual filing-based kill switches in WATCHLIST.
    """
    flags: list[str] = []
    debt_to_equity = _number(snapshot.get("debt_to_equity_pct"))
    operating_cf = _number(snapshot.get("operating_cash_flow"))
    free_cf = _number(snapshot.get("free_cash_flow"))
    roe = _number(snapshot.get("return_on_equity"))

    if debt_to_equity is not None and debt_to_equity > 100:
        flags.append("Live feed shows debt/equity above 100%; verify the latest balance sheet.")
    if operating_cf is not None and operating_cf < 0:
        flags.append("Live feed shows negative operating cash flow; verify the latest annual cash-flow statement.")
    if free_cf is not None and free_cf < 0:
        flags.append("Live feed shows negative free cash flow; check whether this is temporary working-capital/capex usage.")
    if roe is not None and roe < 0:
        flags.append("Live feed shows negative return on equity.")
    return flags
