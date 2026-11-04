from datetime import datetime, timedelta
from decimal import Decimal
from zoneinfo import ZoneInfo

import pytest

from intraday.domain import Instrument
from intraday.market_data.quotes_v3 import (
    MarketQuoteError,
    UpstoxFullMarketQuotesV3Client,
)

IST = ZoneInfo("Asia/Kolkata")


class FakeResponse:
    def __init__(self, status_code=200, payload=None, headers=None):
        self.status_code = status_code
        self._payload = payload or {"status": "success", "data": {}}
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


def test_full_quote_v3_parses_ltp_depth_circuits_and_volume():
    instrument = Instrument(
        "RELIANCE", "NSE_EQ|INE002A01018", "Reliance Industries",
        Decimal("0.05"), 1,
    )
    at = datetime(2026, 11, 4, 10, 0, tzinfo=IST)
    payload = {
        "status": "success",
        "data": {
            "NSE_EQ:RELIANCE": {
                "instrument_token": instrument.instrument_key,
                "symbol": "RELIANCE",
                "timestamp": at.isoformat(),
                "last_trade_time": str(int(at.timestamp() * 1000)),
                "last_price": 100.0,
                "volume": 123456,
                "depth": {
                    "buy": [{"price": 99.95, "quantity": 120, "orders": 3}],
                    "sell": [{"price": 100.05, "quantity": 80, "orders": 2}],
                },
                "lower_circuit_limit": 90.0,
                "upper_circuit_limit": 110.0,
            }
        },
    }
    session = FakeSession([FakeResponse(payload=payload)])
    client = UpstoxFullMarketQuotesV3Client(
        "test-token", session=session, max_retries=0
    )
    received = at + timedelta(seconds=1)
    quotes = client.fetch_quotes((instrument,), now=received)

    tick = quotes[instrument.instrument_key]
    assert tick.symbol == "RELIANCE"
    assert tick.price == 100.0
    assert tick.cumulative_volume == 123456
    assert tick.best_bid == 99.95
    assert tick.best_ask == 100.05
    assert tick.best_bid_quantity == 120
    assert tick.best_ask_quantity == 80
    assert tick.upper_circuit_limit == 110.0
    assert tick.lower_circuit_limit == 90.0
    assert tick.received_at == received
    assert "%7C" in session.calls[0][0]
    assert "Bearer test-token" == session.calls[0][1]["Authorization"]


def test_full_quote_v3_ignores_unknown_instruments_and_invalid_depth():
    instrument = Instrument(
        "RELIANCE", "NSE_EQ|INE002A01018", "Reliance Industries",
        Decimal("0.05"), 1,
    )
    at = datetime(2026, 11, 4, 10, 0, tzinfo=IST)
    payload = {
        "status": "success",
        "data": {
            "NSE_EQ:UNKNOWN": {
                "instrument_token": "NSE_EQ|UNKNOWN",
                "timestamp": at.isoformat(),
                "last_price": 100,
            },
            "NSE_EQ:RELIANCE": {
                "instrument_token": instrument.instrument_key,
                "timestamp": at.isoformat(),
                "last_trade_time": str(int(at.timestamp() * 1000)),
                "last_price": 100,
                "depth": {"buy": [{"price": 0, "quantity": 0}], "sell": []},
            },
        },
    }
    client = UpstoxFullMarketQuotesV3Client(
        "test-token", session=FakeSession([FakeResponse(payload=payload)]),
        max_retries=0,
    )
    quotes = client.fetch_quotes((instrument,), now=at + timedelta(seconds=1))
    assert len(quotes) == 1
    tick = quotes[instrument.instrument_key]
    assert tick.best_bid is None
    assert tick.best_ask is None
    assert tick.best_bid_quantity == 0


def test_full_quote_v3_rejects_over_500_instruments_without_request():
    items = tuple(
        Instrument(
            f"SYM{i}", f"NSE_EQ|KEY{i}", f"Company {i}", Decimal("0.05"), 1
        )
        for i in range(501)
    )
    session = FakeSession([])
    client = UpstoxFullMarketQuotesV3Client(
        "test-token", session=session, max_retries=0
    )
    with pytest.raises(ValueError, match="500"):
        client.fetch_quotes(items)
    assert session.calls == []


def test_full_quote_v3_does_not_echo_access_token_on_http_error():
    instrument = Instrument(
        "RELIANCE", "NSE_EQ|INE002A01018", "Reliance Industries",
        Decimal("0.05"), 1,
    )
    secret = "must-not-leak"
    client = UpstoxFullMarketQuotesV3Client(
        secret,
        session=FakeSession([FakeResponse(status_code=401)]),
        max_retries=0,
    )
    with pytest.raises(MarketQuoteError) as exc:
        client.fetch_quotes((instrument,))
    assert secret not in str(exc.value)



def test_full_quote_v3_rejects_fresh_snapshot_with_stale_last_trade():
    instrument = Instrument(
        "RELIANCE", "NSE_EQ|INE002A01018", "Reliance Industries",
        Decimal("0.05"), 1,
    )
    now = datetime(2026, 11, 4, 10, 0, 10, tzinfo=IST)
    last_trade = now - timedelta(seconds=10)
    payload = {
        "status": "success",
        "data": {
            "NSE_EQ:RELIANCE": {
                "instrument_token": instrument.instrument_key,
                "symbol": "RELIANCE",
                "timestamp": now.isoformat(),
                "last_trade_time": str(int(last_trade.timestamp() * 1000)),
                "last_price": 100,
                "volume": 123456,
                "depth": {
                    "buy": [{"price": 99.95, "quantity": 120}],
                    "sell": [{"price": 100.05, "quantity": 80}],
                },
            }
        },
    }
    client = UpstoxFullMarketQuotesV3Client(
        "test-token",
        session=FakeSession([FakeResponse(payload=payload)]),
        max_retries=0,
    )
    assert client.fetch_quotes((instrument,), now=now) == {}


def test_full_quote_v3_requires_last_trade_timestamp_even_when_snapshot_is_fresh():
    instrument = Instrument(
        "RELIANCE", "NSE_EQ|INE002A01018", "Reliance Industries",
        Decimal("0.05"), 1,
    )
    now = datetime(2026, 11, 4, 10, 0, tzinfo=IST)
    payload = {
        "status": "success",
        "data": {
            "NSE_EQ:RELIANCE": {
                "instrument_token": instrument.instrument_key,
                "timestamp": now.isoformat(),
                "last_price": 100,
                "depth": {
                    "buy": [{"price": 99.95, "quantity": 120}],
                    "sell": [{"price": 100.05, "quantity": 80}],
                },
            }
        },
    }
    client = UpstoxFullMarketQuotesV3Client(
        "test-token",
        session=FakeSession([FakeResponse(payload=payload)]),
        max_retries=0,
    )
    assert client.fetch_quotes((instrument,), now=now) == {}
