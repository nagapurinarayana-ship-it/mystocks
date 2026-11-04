from datetime import date, datetime, timedelta
from decimal import Decimal
from zoneinfo import ZoneInfo
import json

import pytest

from intraday.domain import Instrument
from intraday.execution.paper import FeeSchedule
from intraday.market_data.history import (
    HistoricalDataError,
    UpstoxHistoricalCandleClient,
)
from intraday.backtesting.simulation import run_intraday_backtest

IST = ZoneInfo("Asia/Kolkata")


class FakeResponse:
    def __init__(self, status_code=200, payload=None, headers=None):
        self.status_code = status_code
        self._payload = payload or {"status": "success", "data": {"candles": []}}
        self.headers = headers or {}

    def json(self):
        return self._payload


class FakeSession:
    def __init__(self, responses):
        self.responses = list(responses)
        self.calls = []

    def get(self, url, headers, timeout):
        self.calls.append((url, headers, timeout))
        return self.responses.pop(0)


def test_historical_adapter_parses_candles_and_accounts_invalid_duplicate_rows():
    rows = [
        ["2026-11-04T09:15:00+05:30", 100, 101, 99, 100.5, 1000, 0],
        ["2026-11-04T09:15:00+05:30", 100, 101, 99, 100.5, 1000, 0],
        ["bad", 100, 101, 99, 100.5, 1000, 0],
        ["2026-11-04T09:20:00+05:30", 100.5, 102, 100, 101.5, 1200, 0],
    ]
    session = FakeSession([FakeResponse(payload={"status": "success", "data": {"candles": rows}})])
    client = UpstoxHistoricalCandleClient("fake-token", session=session, request_delay_seconds=0)
    result = client.fetch_5m_bars(
        Instrument("RELIANCE", "NSE_EQ|INE002A01018", "Reliance", Decimal("0.05")),
        date(2026, 11, 4),
        date(2026, 11, 4),
    )
    assert len(result.bars) == 2
    assert result.request_count == 1
    assert result.duplicate_rows == 1
    assert result.invalid_rows == 1
    assert result.bars[0].start_time.hour == 9
    assert result.bars[0].start_time.minute == 15
    assert result.bars[0].volume == 1000
    assert "%7C" in session.calls[0][0]
    assert session.calls[0][1]["Authorization"] == "Bearer fake-token"


def test_historical_adapter_chunks_query_dates_to_one_month_windows():
    empty = FakeResponse()
    session = FakeSession([empty, empty])
    client = UpstoxHistoricalCandleClient("fake-token", session=session, request_delay_seconds=0)
    result = client.fetch_5m_bars(
        Instrument("RELIANCE", "NSE_EQ|INE002A01018", "Reliance", Decimal("0.05")),
        date(2026, 1, 1),
        date(2026, 2, 15),
    )
    assert result.request_count == 2
    assert len(session.calls) == 2
    assert "/minutes/5/2026-01-28/2026-01-01" in session.calls[0][0]
    assert "/minutes/5/2026-02-15/2026-01-29" in session.calls[1][0]


def test_historical_adapter_rejects_unauthorised_response_without_echoing_token():
    session = FakeSession([FakeResponse(status_code=401)])
    token = "should-never-appear-in-error"
    client = UpstoxHistoricalCandleClient(token, session=session, request_delay_seconds=0, max_retries=0)
    with pytest.raises(HistoricalDataError) as exc:
        client.fetch_5m_bars(
            Instrument("RELIANCE", "NSE_EQ|INE002A01018", "Reliance", Decimal("0.05")),
            date(2026, 11, 4),
            date(2026, 11, 4),
        )
    assert token not in str(exc.value)


def make_fees():
    return FeeSchedule(
        brokerage_rate=Decimal("0"),
        brokerage_cap_per_order=Decimal("20"),
        exchange_transaction_rate=Decimal("0"),
        sebi_turnover_rate=Decimal("0"),
        gst_rate=Decimal("0"),
        stt_sell_rate=Decimal("0"),
        stamp_buy_rate=Decimal("0"),
        slippage_bps=Decimal("0"),
    )


def make_backtest_bars():
    start = datetime(2026, 11, 4, 9, 15, tzinfo=IST)
    bars = []
    for i in range(21):
        close = 100 + i * 0.1
        bars.append({
            "open": close - 0.05,
            "high": close + 0.1,
            "low": close - 0.1,
            "close": close,
            "volume": 1000,
        })
    bars.append({
        "open": 104.0,
        "high": 104.6,
        "low": 103.9,
        "close": 104.5,
        "volume": 2500,
    })
    bars.append({
        "open": 104.5,
        "high": 106.0,
        "low": 104.4,
        "close": 105.5,
        "volume": 1500,
    })
    from intraday.domain import CompletedBar
    return tuple(
        CompletedBar(
            "RELIANCE",
            start + timedelta(minutes=5 * i),
            start + timedelta(minutes=5 * (i + 1)),
            item["open"], item["high"], item["low"], item["close"], item["volume"],
        )
        for i, item in enumerate(bars)
    )


def test_backtester_runs_completed_bar_strategy_and_reports_after_cost_results():
    instrument = Instrument(
        "RELIANCE", "NSE_EQ|INE002A01018", "Reliance Industries",
        Decimal("0.05"), 1,
    )
    result = run_intraday_backtest(
        instrument, make_backtest_bars(), "vwap_momentum", make_fees()
    )
    report = result.summary
    assert report.symbol == "RELIANCE"
    assert report.strategy_id == "vwap_momentum"
    assert report.bars == 23
    assert report.trades == 1
    assert report.wins == 1
    assert report.net_pnl > 0
    assert report.charges == 0
    assert report.max_drawdown_pct == 0
    assert report.vwap_method == "typical_price_times_volume_proxy_not_trade_level_vwap"
    # Report is JSON-safe and records each fill's inputs/results.
    json.dumps({"summary": report.__dict__, "trades": result.trades})


def test_backtester_reports_no_trades_when_history_is_insufficient():
    instrument = Instrument(
        "RELIANCE", "NSE_EQ|INE002A01018", "Reliance Industries",
        Decimal("0.05"), 1,
    )
    bars = make_backtest_bars()[:10]
    result = run_intraday_backtest(instrument, bars, "vwap_momentum", make_fees())
    assert result.summary.trades == 0
    assert result.summary.net_pnl == 0
    assert result.summary.profit_factor is None


def test_backtester_rejects_duplicate_and_out_of_session_bars():
    instrument = Instrument(
        "RELIANCE", "NSE_EQ|INE002A01018", "Reliance Industries",
        Decimal("0.05"), 1,
    )
    bars = make_backtest_bars()
    with pytest.raises(ValueError, match="duplicate"):
        run_intraday_backtest(instrument, [bars[0], bars[0]], "vwap_momentum", make_fees())

    from intraday.domain import CompletedBar
    outside = CompletedBar(
        "RELIANCE",
        datetime(2026, 11, 4, 8, 0, tzinfo=IST),
        datetime(2026, 11, 4, 8, 5, tzinfo=IST),
        100, 101, 99, 100.5, 1000,
    )
    with pytest.raises(ValueError, match="outside regular"):
        run_intraday_backtest(instrument, [outside], "vwap_momentum", make_fees())
