"""TLS-verified Upstox Market Data Feed V3 client.

The upstream Python SDK V3 WebSocket feeder currently disables TLS peer and
hostname verification in its transport. This adapter therefore uses the
upstream SDK's official Protobuf schema with websocket-client directly and an
explicit verified SSLContext. It is market-data-only and exposes no order API.
"""

from __future__ import annotations

import json
import os
import ssl
import threading
import time
import uuid
from datetime import datetime, timezone
from typing import Any, Callable, Mapping
from zoneinfo import ZoneInfo

from intraday.domain import MarketTick


WEBSOCKET_URL = "wss://api.upstox.com/v3/feed/market-data-feed"
MAX_LTPC_INSTRUMENTS = 5000
MAX_RECONNECT_ATTEMPTS = 20
RECONNECT_INTERVAL_SECONDS = 5
PING_INTERVAL_SECONDS = 20
PING_TIMEOUT_SECONDS = 10


class UpstoxFeedError(RuntimeError):
    pass


def _mapping(value: Any) -> Mapping[str, Any]:
    return value if isinstance(value, Mapping) else {}


def _first(mapping: Mapping[str, Any], *keys: str) -> Any:
    for key in keys:
        value = mapping.get(key)
        if value is not None:
            return value
    return None


def _timestamp_ms(value: Any) -> datetime | None:
    try:
        return datetime.fromtimestamp(int(value) / 1000.0, tz=ZoneInfo("Asia/Kolkata"))
    except (TypeError, ValueError, OverflowError, OSError):
        return None


def _as_int(value: Any, default: int = 0) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def parse_upstox_v3_message(
    message: Any,
    received_at: datetime | None = None,
    symbol_by_key: Mapping[str, str] | None = None,
) -> tuple[MarketTick, ...]:
    """Convert decoded Upstox V3 Protobuf dictionaries to internal ticks."""
    if isinstance(message, (bytes, bytearray, memoryview)):
        raise UpstoxFeedError("binary feed frame must be decoded from the Upstox V3 Protobuf schema")
    if isinstance(message, str):
        try:
            message = json.loads(message)
        except json.JSONDecodeError as exc:
            raise UpstoxFeedError("feed message was not valid JSON") from exc
    root = _mapping(message)
    feeds = _mapping(root.get("feeds"))
    if not feeds:
        return ()

    received_at = received_at or datetime.now(timezone.utc)
    if received_at.tzinfo is None or received_at.utcoffset() is None:
        raise ValueError("received_at must be timezone-aware")
    result: list[MarketTick] = []

    for instrument_key, raw_feed in feeds.items():
        feed = _mapping(raw_feed)
        full_feed = _mapping(feed.get("fullFeed"))
        market_ff = _mapping(full_feed.get("marketFF"))
        ltpc = _mapping(feed.get("ltpc")) or _mapping(market_ff.get("ltpc"))
        if not ltpc:
            ltpc = _mapping(_mapping(feed.get("firstLevelWithGreeks")).get("ltpc"))

        price = _first(ltpc, "ltp")
        trade_time = _timestamp_ms(_first(ltpc, "ltt"))
        if price is None or trade_time is None:
            continue

        depth = _mapping(market_ff.get("marketLevel"))
        quotes = depth.get("bidAskQuote")
        if not isinstance(quotes, list) or not quotes:
            depth = _mapping(feed.get("firstDepth"))
            quotes = [depth] if depth else []
        best = _mapping(quotes[0]) if quotes else {}
        bid = _first(best, "bidP", "bp")
        ask = _first(best, "askP", "ap")
        bid_quantity = _first(best, "bidQ", "bq")
        ask_quantity = _first(best, "askQ", "aq")
        details = _mapping(market_ff.get("eFeedDetails"))
        # In the official V3 Protobuf schema, vtt is a direct MarketFullFeed
        # field (not nested under eFeedDetails). Retain aliases for documented
        # JSON variants, but prefer the actual Protobuf field.
        volume = _first(market_ff, "vtt", "volumeTradedToday")
        if volume is None:
            volume = _first(details, "vtt", "volumeTradedToday")
        if volume is None:
            volume = _first(
                _mapping(feed.get("firstLevelWithGreeks")), "vtt"
            )
        upper_circuit = _first(market_ff, "uc", "upperCircuitLimit")
        if upper_circuit is None:
            upper_circuit = details.get("uc")
        lower_circuit = _first(market_ff, "lc", "lowerCircuitLimit")
        if lower_circuit is None:
            lower_circuit = details.get("lc")

        try:
            result.append(MarketTick(
                symbol=(symbol_by_key or {}).get(str(instrument_key), str(instrument_key).split("|")[-1]),
                instrument_key=str(instrument_key),
                price=float(price),
                exchange_time=trade_time,
                received_at=received_at,
                last_trade_quantity=max(0, _as_int(_first(ltpc, "ltq"))),
                cumulative_volume=max(0, _as_int(volume)) if volume is not None else None,
                best_bid=float(bid) if bid is not None else None,
                best_ask=float(ask) if ask is not None else None,
                best_bid_quantity=max(0, _as_int(bid_quantity)) if bid_quantity is not None else None,
                best_ask_quantity=max(0, _as_int(ask_quantity)) if ask_quantity is not None else None,
                upper_circuit_limit=float(upper_circuit) if upper_circuit is not None else None,
                lower_circuit_limit=float(lower_circuit) if lower_circuit is not None else None,
            ))
        except (TypeError, ValueError):
            continue
    return tuple(result)


class UpstoxV3MarketDataClient:
    """LTPC-only feed client with verified TLS and bounded reconnects."""

    def __init__(
        self,
        instrument_keys: list[str],
        on_tick: Callable[[MarketTick], None],
        access_token: str | None = None,
        symbol_by_key: Mapping[str, str] | None = None,
        max_reconnect_attempts: int = MAX_RECONNECT_ATTEMPTS,
        reconnect_interval_seconds: float = RECONNECT_INTERVAL_SECONDS,
    ) -> None:
        if not instrument_keys:
            raise ValueError("at least one instrument key is required")
        if len(instrument_keys) > MAX_LTPC_INSTRUMENTS:
            raise ValueError("LTPC-only Upstox subscription limit is 5,000 keys")
        if len(set(instrument_keys)) != len(instrument_keys):
            raise ValueError("instrument keys must be unique")
        if max_reconnect_attempts < 0 or max_reconnect_attempts > 100:
            raise ValueError("max_reconnect_attempts must be between 0 and 100")
        if reconnect_interval_seconds <= 0:
            raise ValueError("reconnect_interval_seconds must be positive")

        self.instrument_keys = list(instrument_keys)
        self.on_tick = on_tick
        self.symbol_by_key = dict(symbol_by_key or {})
        missing = set(instrument_keys) - set(self.symbol_by_key)
        if missing:
            raise ValueError(f"symbol mapping missing for {len(missing)} instrument keys")
        self.access_token = access_token or os.getenv("UPSTOX_ACCESS_TOKEN", "")
        if not self.access_token.strip():
            raise UpstoxFeedError("UPSTOX_ACCESS_TOKEN is not configured")

        self.max_reconnect_attempts = max_reconnect_attempts
        self.reconnect_interval_seconds = reconnect_interval_seconds
        self._stop_event = threading.Event()
        self._thread: threading.Thread | None = None
        self._websocket_app = None
        self._lock = threading.RLock()
        self.connected = False
        self.last_error: str | None = None
        self._fatal_auth_error = False
        self._connected_since: float | None = None

    @staticmethod
    def verified_tls_context():
        """Build a CA-verified, hostname-verified TLS context."""
        import certifi

        context = ssl.create_default_context(cafile=certifi.where())
        if context.verify_mode != ssl.CERT_REQUIRED or not context.check_hostname:
            raise UpstoxFeedError("TLS verification could not be enabled")
        return context

    @staticmethod
    def build_subscription_frame(instrument_keys: list[str]) -> bytes:
        """Build the V3 binary subscription message for LTPC-only mode."""
        if not instrument_keys:
            raise ValueError("at least one instrument key is required")
        payload = {
            "guid": str(uuid.uuid4()),
            "method": "sub",
            "data": {
                "mode": "ltpc",
                "instrumentKeys": instrument_keys,
            },
        }
        return json.dumps(payload, separators=(",", ":")).encode("utf-8")

    @staticmethod
    def decode_protobuf_frame(frame: bytes) -> Mapping[str, Any]:
        """Decode the exact FeedResponse Protobuf type distributed in the SDK."""
        try:
            from google.protobuf.json_format import MessageToDict
            from upstox_client.feeder.proto import MarketDataFeedV3_pb2
            decoded = MarketDataFeedV3_pb2.FeedResponse.FromString(bytes(frame))
            return MessageToDict(decoded)
        except Exception as exc:
            raise UpstoxFeedError(
                f"Upstox V3 Protobuf frame could not be decoded: {type(exc).__name__}"
            ) from exc

    def connect(self) -> None:
        """Start the verified WebSocket loop in a dedicated foreground-owned thread."""
        if self._thread is not None and self._thread.is_alive():
            return
        try:
            import websocket
            # Resolve schema import before opening a socket so missing SDK files
            # fail immediately rather than looking like a feed outage.
            from upstox_client.feeder.proto import MarketDataFeedV3_pb2  # noqa: F401
        except ImportError as exc:
            raise UpstoxFeedError(
                "Upstox SDK or websocket-client missing. Install requirements-intraday.txt first."
            ) from exc

        self._stop_event.clear()
        self._fatal_auth_error = False
        self._thread = threading.Thread(
            target=self._run_connection_loop,
            args=(websocket,),
            name="mystocks-upstox-v3-feed",
            daemon=True,
        )
        self._thread.start()

    def _run_connection_loop(self, websocket_module: Any) -> None:
        attempt = 0
        while not self._stop_event.is_set():
            try:
                app = websocket_module.WebSocketApp(
                    WEBSOCKET_URL,
                    header={
                        "Authorization": f"Bearer {self.access_token}",
                        "Accept": "*/*",
                    },
                    on_open=self._on_open,
                    on_message=self._on_message,
                    on_error=self._on_error,
                    on_close=self._on_close,
                )
                with self._lock:
                    self._websocket_app = app
                app.run_forever(
                    sslopt={"context": self.verified_tls_context()},
                    ping_interval=PING_INTERVAL_SECONDS,
                    ping_timeout=PING_TIMEOUT_SECONDS,
                )
            except Exception as exc:
                with self._lock:
                    self.connected = False
                    self.last_error = f"Upstox WebSocket loop failed: {type(exc).__name__}"

            if self._stop_event.is_set() or self._fatal_auth_error:
                break

            with self._lock:
                connected_since = self._connected_since
                self.connected = False
                self._websocket_app = None
                self._connected_since = None
            if connected_since is not None and time.monotonic() - connected_since >= 60:
                attempt = 0

            attempt += 1
            if attempt > self.max_reconnect_attempts:
                with self._lock:
                    self.last_error = "Upstox WebSocket reconnect attempts exhausted"
                break

            with self._lock:
                self.last_error = f"Upstox WebSocket reconnecting ({attempt}/{self.max_reconnect_attempts})"
            self._stop_event.wait(self.reconnect_interval_seconds)

        with self._lock:
            self.connected = False
            self._websocket_app = None

    def _on_open(self, ws: Any, *_: Any) -> None:
        try:
            frame = self.build_subscription_frame(self.instrument_keys)
            import websocket

            ws.send(frame, opcode=websocket.ABNF.OPCODE_BINARY)
            with self._lock:
                self.connected = True
                self.last_error = None
                self._connected_since = time.monotonic()
        except Exception as exc:
            with self._lock:
                self.connected = False
                self.last_error = f"Upstox LTPC subscription failed: {type(exc).__name__}"
            try:
                ws.close()
            except Exception:
                pass

    def _on_close(self, *_: Any) -> None:
        with self._lock:
            self.connected = False

    def _on_error(self, _ws: Any, error: Any = None) -> None:
        error_text = str(error).lower() if error is not None else ""
        with self._lock:
            self.connected = False
            if "401" in error_text or "unauthorized" in error_text:
                self._fatal_auth_error = True
                self.last_error = "Upstox rejected market-data authentication (HTTP 401)"
                self._stop_event.set()
            else:
                self.last_error = (
                    f"Upstox market-data transport error: {type(error).__name__}"
                    if error is not None else "Upstox market-data transport error"
                )

    def _decode_message(self, message: Any) -> Mapping[str, Any] | str:
        if isinstance(message, (bytes, bytearray, memoryview)):
            return self.decode_protobuf_frame(bytes(message))
        if isinstance(message, (Mapping, str)):
            return message
        raise UpstoxFeedError("unexpected Upstox WebSocket message type")

    def _on_message(self, _ws: Any, message: Any) -> None:
        try:
            decoded = self._decode_message(message)
            ticks = parse_upstox_v3_message(
                decoded, symbol_by_key=self.symbol_by_key
            )
        except (UpstoxFeedError, TypeError, ValueError) as exc:
            with self._lock:
                self.last_error = f"Upstox market-data frame rejected: {type(exc).__name__}"
            return

        if ticks:
            with self._lock:
                self.last_error = None
        for tick in ticks:
            try:
                self.on_tick(tick)
            except Exception as exc:
                with self._lock:
                    self.last_error = f"Market-data consumer callback failed: {type(exc).__name__}"
                return

    def disconnect(self) -> None:
        """Stop reconnects and close the current socket."""
        self._stop_event.set()
        with self._lock:
            app = self._websocket_app
            self.connected = False
        if app is not None:
            try:
                app.close()
            except Exception:
                pass
        thread = self._thread
        if thread is not None and thread.is_alive() and thread is not threading.current_thread():
            thread.join(timeout=10)
        with self._lock:
            self.connected = False
            self._websocket_app = None
