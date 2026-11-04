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
        self.mode_changes = []
        self.connected = False
        self.disconnected = False

    def auto_reconnect(self, enabled, interval, retries):
        self.reconnect = (enabled, interval, retries)

    def on(self, name, callback):
        self.handlers[name] = callback

    def connect(self):
        self.connected = True
        self.handlers["open"]()

    def change_mode(self, keys, mode):
        self.mode_changes.append((keys, mode))

    def disconnect(self):
        self.disconnected = True


def test_upstox_client_promotes_and_demotes_only_known_symbols(monkeypatch):
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

    client.promote_to_full(["NSE_EQ|INE002A01018"])
    client.demote_to_ltpc(["NSE_EQ|INE002A01018"])
    assert client._streamer.mode_changes == [
        (["NSE_EQ|INE002A01018"], "full"),
        (["NSE_EQ|INE002A01018"], "ltpc"),
    ]

    with pytest.raises(ValueError):
        client.promote_to_full(["NSE_EQ|UNKNOWN"])
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
