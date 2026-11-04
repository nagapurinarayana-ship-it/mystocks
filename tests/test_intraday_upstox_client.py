from types import SimpleNamespace

import pytest

from intraday.market_data.upstox_v3 import (
    UpstoxFeedError,
    UpstoxV3MarketDataClient,
)


class FakeStreamer:
    def __init__(self, api_client, instrument_keys, mode):
        self.api_client = api_client
        self.instrument_keys = instrument_keys
        self.mode = mode
        self.handlers = {}
        self.connected = False
        self.disconnected = False

    def auto_reconnect(self, enabled, interval, retries):
        self.reconnect = (enabled, interval, retries)

    def on(self, name, callback):
        self.handlers[name] = callback

    def connect(self):
        self.connected = True
        self.handlers["open"]()

    def disconnect(self):
        self.disconnected = True


def test_upstox_client_uses_ltpc_only_and_tracks_sdk_connection_events(monkeypatch):
    fake = SimpleNamespace(
        Configuration=lambda: SimpleNamespace(access_token=None),
        ApiClient=lambda config: ("api-client", config.access_token),
        MarketDataStreamerV3=FakeStreamer,
    )
    monkeypatch.setitem(__import__("sys").modules, "upstox_client", fake)

    ticks = []
    client = UpstoxV3MarketDataClient(
        ["NSE_EQ|INE002A01018"],
        ticks.append,
        access_token="test-token-not-a-real-secret",
        symbol_by_key={"NSE_EQ|INE002A01018": "RELIANCE"},
    )
    client.connect()
    assert client.connected is True
    assert client._streamer.reconnect == (True, 5, 20)

    assert client._streamer.mode == "ltpc"
    assert {
        "open", "close", "error", "reconnecting",
        "autoReconnectStopped", "message",
    } <= set(client._streamer.handlers)
    assert not hasattr(client, "promote_to_full")
    assert not hasattr(client, "demote_to_ltpc")

    client._streamer.handlers["reconnecting"]()
    assert client.connected is False
    assert client.last_error == "Upstox market-data stream is reconnecting"
    client._streamer.handlers["open"]()
    assert client.connected is True
    assert client.last_error is None
    client.disconnect()
    assert client.connected is False
    assert client._streamer.disconnected is True


def test_upstox_client_rejects_incomplete_symbol_mapping():
    with pytest.raises(ValueError):
        UpstoxV3MarketDataClient(
            ["NSE_EQ|INE002A01018"],
            lambda tick: None,
            access_token="test-token",
            symbol_by_key={},
        )


def test_upstox_client_stops_health_state_on_error():
    client = UpstoxV3MarketDataClient.__new__(UpstoxV3MarketDataClient)
    client.connected = True
    client.last_error = None
    client._on_error(RuntimeError("private error text"))
    assert client.connected is False
    assert "RuntimeError" in client.last_error
    assert "private error text" not in client.last_error



def test_upstox_client_rejects_malformed_payload_without_crashing_stream_callback():
    client = UpstoxV3MarketDataClient.__new__(UpstoxV3MarketDataClient)
    client.connected = True
    client.last_error = None
    client.symbol_by_key = {"NSE_EQ|INE002A01018": "RELIANCE"}
    delivered = []
    client.on_tick = delivered.append

    client._on_message("{not-json")
    assert client.connected is True
    assert delivered == []
    assert "UpstoxFeedError" in client.last_error


def test_upstox_client_decodes_message_and_delivers_only_valid_ticks():
    from datetime import datetime, timezone

    client = UpstoxV3MarketDataClient.__new__(UpstoxV3MarketDataClient)
    client.connected = True
    client.last_error = "previous recoverable parsing warning"
    client.symbol_by_key = {"NSE_EQ|INE002A01018": "RELIANCE"}
    delivered = []
    client.on_tick = delivered.append
    now = datetime(2026, 11, 4, 4, 30, tzinfo=timezone.utc)

    client._on_message({
        "feeds": {
            "NSE_EQ|INE002A01018": {
                "ltpc": {
                    "ltp": 100,
                    "ltt": str(int(now.timestamp() * 1000)),
                    "ltq": "10",
                }
            }
        }
    })
    assert len(delivered) == 1
    assert delivered[0].symbol == "RELIANCE"
    assert client.last_error is None


def test_upstox_client_contains_consumer_exceptions_and_marks_callback_fault():
    client = UpstoxV3MarketDataClient.__new__(UpstoxV3MarketDataClient)
    client.connected = True
    client.last_error = None
    client.symbol_by_key = {"NSE_EQ|INE002A01018": "RELIANCE"}
    client.on_tick = lambda tick: (_ for _ in ()).throw(RuntimeError("private details"))
    from datetime import datetime, timezone
    now = datetime(2026, 11, 4, 4, 30, tzinfo=timezone.utc)

    client._on_message({
        "feeds": {
            "NSE_EQ|INE002A01018": {
                "ltpc": {
                    "ltp": 100,
                    "ltt": str(int(now.timestamp() * 1000)),
                    "ltq": "10",
                }
            }
        }
    })
    assert "RuntimeError" in client.last_error
    assert "private details" not in client.last_error
