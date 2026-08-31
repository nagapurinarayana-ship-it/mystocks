from long_term_watchlist import WATCHLIST, live_risk_flags, parse_google_news_rss


def test_watchlist_is_ranked_and_unique():
    assert [s.research_rank for s in WATCHLIST] == [1, 2, 3]
    assert len({s.yahoo_symbol for s in WATCHLIST}) == 3
    assert {s.exchange for s in WATCHLIST} == {"NSE", "BSE"}


def test_news_parser_keeps_valid_items_and_limit():
    xml = """<?xml version='1.0'?>
    <rss><channel>
      <item><title>One</title><link>https://example.com/1</link><source>A</source><pubDate>Mon, 31 Aug 2026 08:30:00 GMT</pubDate></item>
      <item><title>Two</title><link>https://example.com/2</link><source>B</source></item>
      <item><title>Missing link</title></item>
    </channel></rss>"""
    rows = parse_google_news_rss(xml, limit=2)
    assert len(rows) == 2
    assert rows[0]["title"] == "One"
    assert rows[0]["published"].startswith("2026-08-31")
    assert rows[1]["source"] == "B"


def test_live_risk_flags_are_conservative():
    flags = live_risk_flags(
        {
            "debt_to_equity_pct": 130,
            "operating_cash_flow": -10,
            "free_cash_flow": -2,
            "return_on_equity": -0.01,
        }
    )
    assert len(flags) == 4
    assert live_risk_flags({"debt_to_equity_pct": 20, "operating_cash_flow": 10}) == []
