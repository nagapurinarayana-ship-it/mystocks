"""Upstox Full Market Quotes V3 adapter for candidate depth snapshots.

This REST adapter is used only for a small shortlist. The broad scanner remains
on the LTPC-only WebSocket subscription, avoiding mixed-category subscription
limits. It never places or modifies broker orders.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Mapping
from urllib.parse import quote
import os
import time

import requests

from intraday.domain import Instrument, MarketTick


BASE_URL = "https://api.upstox.com/v3/market-quote/quotes"


class MarketQuoteError(RuntimeError):
    """Full quote request failed without exposing access tokens or response data."""


def _mapping(value: Any) -> Mapping[str, Any]:
    return value if isinstance(value, Mapping) else {}


def _positive_float(value: Any) -> float | None:
    try:
        result = float(value)
    except (TypeError, ValueError):
        return None
    if not (result > 0 and result < float("inf")):
        return None
    return result


def _nonnegative_int(value: Any) -> int | None:
    try:
        result = int(value)
    except (TypeError, ValueError):
        return None
    return result if result >= 0 else None


def _parse_timestamp(value: Any) -> datetime | None:
    if not isinstance(value, str) or not value.strip():
        return None
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError:
        try:
            parsed = datetime.fromtimestamp(int(value) / 1000, tz=timezone.utc)
        except (TypeError, ValueError, OverflowError, OSError):
            return None
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        return None
    return parsed


class UpstoxFullMarketQuotesV3Client:
    """Fetch fresh top-of-book snapshots for up to 500 instruments per call."""

    def __init__(
        self,
        access_token: str | None = None,
        session: requests.Session | None = None,
        request_timeout: tuple[float, float] = (5, 15),
        max_retries: int = 2,
    ) -> None:
        self.access_token = access_token or os.getenv("UPSTOX_ACCESS_TOKEN", "")
        if not self.access_token.strip():
            raise MarketQuoteError("UPSTOX_ACCESS_TOKEN is not configured")
        if max_retries < 0 or max_retries > 5:
            raise ValueError("max_retries must be between 0 and 5")
        self.session = session or requests.Session()
        self.request_timeout = request_timeout
        self.max_retries = max_retries

    def fetch_quotes(
        self,
        instruments: tuple[Instrument, ...] | list[Instrument],
        now: datetime | None = None,
    ) -> dict[str, MarketTick]:
        selected = tuple(instruments)
        if not selected:
            return {}
        if len(selected) > 500:
            raise ValueError("Upstox Full Market Quotes V3 accepts at most 500 instruments per request")
        keys = [item.instrument_key for item in selected]
        if len(set(keys)) != len(keys):
            raise ValueError("instrument keys must be unique")
        symbol_by_key = {item.instrument_key: item.symbol for item in selected}

        encoded_keys = ",".join(quote(key, safe="") for key in keys)
        url = f"{BASE_URL}?instrument_key={encoded_keys}"
        headers = {
            "Accept": "application/json",
            "Content-Type": "application/json",
            "Authorization": f"Bearer {self.access_token}",
        }

        payload = None
        for attempt in range(self.max_retries + 1):
            try:
                response = self.session.get(
                    url, headers=headers, timeout=self.request_timeout
                )
            except requests.RequestException as exc:
                if attempt >= self.max_retries:
                    raise MarketQuoteError("full market quote network request failed") from exc
                time.sleep(min(2 ** attempt, 4))
                continue

            if response.status_code in {429, 500, 502, 503, 504} and attempt < self.max_retries:
                retry_after = response.headers.get("Retry-After")
                try:
                    delay = float(retry_after) if retry_after is not None else min(2 ** attempt, 4)
                except (TypeError, ValueError):
                    delay = min(2 ** attempt, 4)
                time.sleep(max(0.0, min(delay, 8.0)))
                continue
            if response.status_code != 200:
                raise MarketQuoteError(
                    f"full market quote API returned HTTP {response.status_code}"
                )
            try:
                payload = response.json()
            except ValueError as exc:
                raise MarketQuoteError("full market quote API returned invalid JSON") from exc
            break

        if not isinstance(payload, Mapping) or payload.get("status") != "success":
            raise MarketQuoteError("full market quote API did not return success")
        data = payload.get("data")
        if not isinstance(data, Mapping):
            raise MarketQuoteError("full market quote API returned an unexpected data structure")

        received_at = now or datetime.now(timezone.utc)
        if received_at.tzinfo is None or received_at.utcoffset() is None:
            raise ValueError("now must be timezone-aware")
        result: dict[str, MarketTick] = {}

        for raw_quote in data.values():
            row = _mapping(raw_quote)
            instrument_key = str(row.get("instrument_token") or "")
            symbol = symbol_by_key.get(instrument_key)
            if not symbol:
                continue
            snapshot_time = _parse_timestamp(row.get("timestamp"))
            price = _positive_float(row.get("last_price"))
            if snapshot_time is None or price is None:
                continue

            depth = _mapping(row.get("depth"))
            bids = depth.get("buy")
            asks = depth.get("sell")
            bid = _mapping(bids[0]) if isinstance(bids, list) and bids else {}
            ask = _mapping(asks[0]) if isinstance(asks, list) and asks else {}

            best_bid = _positive_float(bid.get("price"))
            best_ask = _positive_float(ask.get("price"))
            bid_quantity = _nonnegative_int(bid.get("quantity"))
            ask_quantity = _nonnegative_int(ask.get("quantity"))

            try:
                tick = MarketTick(
                    symbol=symbol,
                    instrument_key=instrument_key,
                    price=price,
                    exchange_time=snapshot_time,
                    received_at=received_at,
                    last_trade_quantity=0,
                    cumulative_volume=_nonnegative_int(row.get("volume")),
                    best_bid=best_bid,
                    best_ask=best_ask,
                    best_bid_quantity=bid_quantity,
                    best_ask_quantity=ask_quantity,
                    upper_circuit_limit=_positive_float(row.get("upper_circuit_limit")),
                    lower_circuit_limit=_positive_float(row.get("lower_circuit_limit")),
                )
            except ValueError:
                continue
            result[instrument_key] = tick

        return result
