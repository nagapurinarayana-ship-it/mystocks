"""Optional Upstox Market Data Feed V3 adapter.

Install requirements-intraday.txt to use this module. The SDK access token must
be supplied by the runtime environment; it is never persisted or logged here.
This adapter provides market data only and has no order-placement methods.
"""

from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from zoneinfo import ZoneInfo
from typing import Any, Callable, Mapping

from intraday.domain import MarketTick


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
    """Convert decoded SDK V3 feed messages to internal ticks."""
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
        volume = _first(details, "vtt", "volumeTradedToday")

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
            ))
        except (TypeError, ValueError):
            continue
    return tuple(result)


class UpstoxV3MarketDataClient:
    """Small event adapter around the official Upstox Python SDK."""

    def __init__(
        self,
        instrument_keys: list[str],
        on_tick: Callable[[MarketTick], None],
        access_token: str | None = None,
        symbol_by_key: Mapping[str, str] | None = None,
    ) -> None:
        if not instrument_keys:
            raise ValueError("at least one instrument key is required")
        if len(instrument_keys) > 5000:
            raise ValueError("LTPC-only Upstox subscription limit is 5,000 keys")
        if len(set(instrument_keys)) != len(instrument_keys):
            raise ValueError("instrument keys must be unique")
        self.instrument_keys = instrument_keys
        self.on_tick = on_tick
        self.symbol_by_key = dict(symbol_by_key or {})
        missing = set(instrument_keys) - set(self.symbol_by_key)
        if missing:
            raise ValueError(f"symbol mapping missing for {len(missing)} instrument keys")
        self.access_token = access_token or os.getenv("UPSTOX_ACCESS_TOKEN", "")
        if not self.access_token.strip():
            raise UpstoxFeedError("UPSTOX_ACCESS_TOKEN is not configured")
        self._streamer = None
        self.last_error: str | None = None
        self.connected = False

    def connect(self) -> None:
        try:
            import upstox_client
        except ImportError as exc:
            raise UpstoxFeedError(
                "Upstox SDK missing. Install requirements-intraday.txt first."
            ) from exc

        configuration = upstox_client.Configuration()
        configuration.access_token = self.access_token
        api_client = upstox_client.ApiClient(configuration)
        self._streamer = upstox_client.MarketDataStreamerV3(
            api_client, self.instrument_keys, "ltpc"
        )
        self._streamer.auto_reconnect(True, 5, 20)
        self._streamer.on("open", self._on_open)
        self._streamer.on("close", self._on_close)
        self._streamer.on("error", self._on_error)
        self._streamer.on("autoReconnectStopped", self._on_error)
        self._streamer.on("message", self._on_message)
        self._streamer.connect()

    def _on_open(self, *_: Any) -> None:
        self.connected = True
        self.last_error = None

    def _on_close(self, *_: Any) -> None:
        self.connected = False

    def _on_error(self, error: Any = None, *_: Any) -> None:
        self.connected = False
        self.last_error = "Upstox market-data stream reported an error"
        if error is not None:
            self.last_error = f"{self.last_error}: {type(error).__name__}"

    def _on_message(self, message: Any) -> None:
        for tick in parse_upstox_v3_message(message, symbol_by_key=self.symbol_by_key):
            self.on_tick(tick)

    def promote_to_full(self, instrument_keys: list[str]) -> None:
        """Promote a bounded candidate shortlist to full bid/ask depth mode."""
        if self._streamer is None or not self.connected:
            raise UpstoxFeedError("cannot promote instruments while WebSocket is disconnected")
        keys = sorted(set(instrument_keys))
        if not keys:
            return
        if len(keys) > 2000:
            raise ValueError("full feed shortlist exceeds Upstox 2,000-instrument limit")
        unknown = set(keys) - set(self.instrument_keys)
        if unknown:
            raise ValueError("cannot promote instrument keys outside the base subscription")
        self._streamer.change_mode(keys, "full")

    def demote_to_ltpc(self, instrument_keys: list[str]) -> None:
        """Demote held/expired candidates back to broad LTPC mode."""
        if self._streamer is None or not self.connected:
            raise UpstoxFeedError("cannot demote instruments while WebSocket is disconnected")
        keys = sorted(set(instrument_keys))
        if keys:
            self._streamer.change_mode(keys, "ltpc")

    def disconnect(self) -> None:
        self.connected = False
        if self._streamer is not None:
            self._streamer.disconnect()
