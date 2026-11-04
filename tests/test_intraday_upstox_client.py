import json
import ssl
import sys
import threading
import time
from types import SimpleNamespace

import pytest

from intraday.market_data.upstox_v3 import (
    UpstoxFeedError,
    UpstoxV3MarketDataClient,
)


KEY = "NSE_EQ|INE002A01018"


def make_client(**overrides):
    args = {
        "instrument_keys": [KEY],
        "on_tick": lambda tick: None,
        "access_token": "unit-test-token",
        "symbol_by_key": {KEY: "RELIANCE"},
    }
    args.update(overrides)
    return UpstoxV3MarketDataClient(**args)


def test_tls_context_requires_ca_and_hostname_verification():
    context = UpstoxV3MarketDataClient.verified_tls_context()
    assert context.verify_mode == ssl.CERT_REQUIRED
    assert context.check_hostname is True


def test_subscription_frame_is_binary_ltpc_request():
    frame = UpstoxV3MarketDataClient.build_subscription_frame([KEY])
    assert isinstance(frame, bytes)
    payload = json.loads(frame)
    assert payload["method"] == "sub"
    assert payload["data"]["mode"] == "ltpc"
    assert payload["data"]["instrumentKeys"] == [KEY]
    assert payload["guid"]


def test_client_rejects_unbounded_or_duplicate_instrument_subscriptions():
    with pytest.raises(ValueError, match="5,000"):
        make_client(instrument_keys=[f"NSE_EQ|K{i}" for i in range(5001)],
                    symbol_by_key={f"NSE_EQ|K{i}": f"S{i}" for i in range(5001)})
    with pytest.raises(ValueError, match="unique"):
        make_client(instrument_keys=[KEY, KEY])


def test_client_requires_all_instrument_symbol_mappings():
    with pytest.raises(ValueError, match="mapping missing"):
        make_client(symbol_by_key={})


class FakeWebSocketApp:
    def __init__(self, url, header, on_open, on_message, on_error, on_close):
        self.url = url
        self.header = header
        self.on_open = on_open
        self.on_message = on_message
        self.on_error = on_error
        self.on_close = on_close
        self.sent = []
        self.closed = threading.Event()
        self.ssl_context = None

    def send(self, payload, opcode):
        self.sent.append((payload, opcode))

    def run_forever(self, sslopt, ping_interval, ping_timeout):
        self.ssl_context = sslopt["context"]
        self.on_open(self)
        self.closed.wait(timeout=2)
        if self.closed.is_set():
            self.on_close(self, 1000, "closed")

    def close(self):
        self.closed.set()


def test_connect_sends_ltpc_frame_over_certificate_verified_websocket(monkeypatch):
    apps = []

    def make_app(*args, **kwargs):
        app = FakeWebSocketApp(*args, **kwargs)
        apps.append(app)
        return app

    fake_websocket = SimpleNamespace(
        WebSocketApp=make_app,
        ABNF=SimpleNamespace(OPCODE_BINARY=2),
    )
    monkeypatch.setitem(sys.modules, "websocket", fake_websocket)

    client = make_client(max_reconnect_attempts=0)
    client.connect()
    deadline = time.monotonic() + 1
    while not client.connected and time.monotonic() < deadline:
        time.sleep(0.01)

    assert client.connected is True
    assert len(apps) == 1
    app = apps[0]
    assert app.url == "wss://api.upstox.com/v3/feed/market-data-feed"
    assert app.header == {
        "Authorization": "Bearer unit-test-token",
        "Accept": "*/*",
    }
    assert app.ssl_context.verify_mode == ssl.CERT_REQUIRED
    assert app.ssl_context.check_hostname is True
    assert len(app.sent) == 1
    assert app.sent[0][1] == 2
    assert json.loads(app.sent[0][0])["data"]["mode"] == "ltpc"

    client.disconnect()
    assert client.connected is False
    assert app.closed.is_set()


def test_authentication_401_stops_reconnects_without_echoing_server_message():
    client = make_client()
    client._on_error(None, RuntimeError("401 Unauthorized; token details not for logs"))
    assert client.connected is False
    assert client._fatal_auth_error is True
    assert client._stop_event.is_set()
    assert client.last_error == "Upstox rejected market-data authentication (HTTP 401)"
    assert "token details" not in client.last_error


def test_transport_error_never_echoes_private_error_text():
    client = make_client()
    client._on_error(None, RuntimeError("private error text"))
    assert client.connected is False
    assert "RuntimeError" in client.last_error
    assert "private error text" not in client.last_error


def test_malformed_message_does_not_crash_transport_callback():
    client = make_client()
    client.connected = True
    client._on_message(None, b"not a protobuf frame")
    assert client.connected is True
    assert "UpstoxFeedError" in client.last_error


def test_valid_decoded_message_is_sent_to_scanner_callback():
    from datetime import datetime, timezone

    delivered = []
    client = make_client(on_tick=delivered.append)
    now = datetime(2026, 11, 4, 4, 30, tzinfo=timezone.utc)
    payload = {
        "feeds": {
            KEY: {
                "ltpc": {
                    "ltp": 100,
                    "ltt": str(int(now.timestamp() * 1000)),
                    "ltq": "10",
                }
            }
        }
    }
    client._on_message(None, payload)
    assert len(delivered) == 1
    assert delivered[0].symbol == "RELIANCE"
    assert client.last_error is None


def test_consumer_callback_failure_is_contained_and_sanitized():
    def broken(_tick):
        raise RuntimeError("private error text")

    client = make_client(on_tick=broken)
    from datetime import datetime, timezone
    now = datetime(2026, 11, 4, 4, 30, tzinfo=timezone.utc)
    payload = {
        "feeds": {
            KEY: {
                "ltpc": {
                    "ltp": 100,
                    "ltt": str(int(now.timestamp() * 1000)),
                    "ltq": "10",
                }
            }
        }
    }
    client._on_message(None, payload)
    assert "RuntimeError" in client.last_error
    assert "private error text" not in client.last_error
