"""Upstox V3 historical 5-minute candle adapter with bounded date windows."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timedelta
from decimal import Decimal, InvalidOperation
from typing import Any, Mapping
from urllib.parse import quote
from zoneinfo import ZoneInfo
import os
import time

import requests

from intraday.domain import CompletedBar, Instrument


IST = ZoneInfo("Asia/Kolkata")
BASE_URL = "https://api.upstox.com/v3/historical-candle"


class HistoricalDataError(RuntimeError):
    """Market-history retrieval or validation failed without exposing secrets."""


@dataclass(frozen=True, slots=True)
class HistoryFetchResult:
    symbol: str
    bars: tuple[CompletedBar, ...]
    request_count: int
    invalid_rows: int
    duplicate_rows: int
    requested_from: date
    requested_to: date


def _parse_candle(raw: Any, symbol: str) -> CompletedBar:
    if not isinstance(raw, (list, tuple)) or len(raw) < 6:
        raise ValueError("historical candle must contain timestamp and OHLCV")
    timestamp = datetime.fromisoformat(str(raw[0]))
    if timestamp.tzinfo is None or timestamp.utcoffset() is None:
        raise ValueError("historical candle timestamp must include a timezone")
    values = [float(raw[i]) for i in range(1, 5)]
    volume = int(raw[5])
    return CompletedBar(
        symbol=symbol,
        start_time=timestamp.astimezone(IST),
        end_time=timestamp.astimezone(IST) + timedelta(minutes=5),
        open=values[0],
        high=values[1],
        low=values[2],
        close=values[3],
        volume=volume,
    )


class UpstoxHistoricalCandleClient:
    """Fetch historical 5-minute candles with strict one-month query windows.

    Uses the official V3 historical candle endpoint. No token is logged or
    persisted. The caller owns the access token lifecycle.
    """

    def __init__(
        self,
        access_token: str | None = None,
        session: requests.Session | None = None,
        request_delay_seconds: float = 0.25,
        max_retries: int = 3,
    ) -> None:
        self.access_token = access_token or os.getenv("UPSTOX_ACCESS_TOKEN", "")
        if not self.access_token.strip():
            raise HistoricalDataError("UPSTOX_ACCESS_TOKEN is not configured")
        if request_delay_seconds < 0:
            raise ValueError("request_delay_seconds cannot be negative")
        if max_retries < 0 or max_retries > 5:
            raise ValueError("max_retries must be between 0 and 5")
        self.session = session or requests.Session()
        self.request_delay_seconds = request_delay_seconds
        self.max_retries = max_retries

    def _fetch_window(
        self, instrument: Instrument, start: date, end: date
    ) -> tuple[list[Any], int]:
        if end < start:
            raise ValueError("window end must be on or after start")
        if end - start > timedelta(days=31):
            raise ValueError("V3 1-15 minute history requests are limited to one month")
        encoded_key = quote(instrument.instrument_key, safe="")
        url = (
            f"{BASE_URL}/{encoded_key}/minutes/5/"
            f"{end.isoformat()}/{start.isoformat()}"
        )
        headers = {
            "Accept": "application/json",
            "Authorization": f"Bearer {self.access_token}",
        }
        for attempt in range(self.max_retries + 1):
            try:
                response = self.session.get(url, headers=headers, timeout=(5, 30))
            except requests.RequestException as exc:
                if attempt >= self.max_retries:
                    raise HistoricalDataError("historical candle network request failed") from exc
                time.sleep(min(2 ** attempt, 4))
                continue

            if response.status_code in {429, 500, 502, 503, 504} and attempt < self.max_retries:
                retry_after = response.headers.get("Retry-After")
                try:
                    delay = float(retry_after) if retry_after is not None else min(2 ** attempt, 4)
                except ValueError:
                    delay = min(2 ** attempt, 4)
                time.sleep(max(0.0, min(delay, 8.0)))
                continue
            if response.status_code != 200:
                raise HistoricalDataError(
                    f"historical candle API returned HTTP {response.status_code}"
                )
            try:
                payload: Mapping[str, Any] = response.json()
            except ValueError as exc:
                raise HistoricalDataError("historical candle API returned invalid JSON") from exc
            if payload.get("status") != "success":
                raise HistoricalDataError("historical candle API did not return success")
            data = payload.get("data")
            if not isinstance(data, Mapping) or not isinstance(data.get("candles"), list):
                raise HistoricalDataError("historical candle response had an unexpected structure")
            return data["candles"], attempt + 1
        raise HistoricalDataError("historical candle request exhausted retry attempts")

    def fetch_5m_bars(
        self,
        instrument: Instrument,
        start: date,
        end: date,
    ) -> HistoryFetchResult:
        if end < start:
            raise ValueError("end date must be on or after start date")
        cursor = start
        all_rows: list[Any] = []
        request_count = 0
        while cursor <= end:
            chunk_end = min(cursor + timedelta(days=27), end)
            rows, attempts = self._fetch_window(instrument, cursor, chunk_end)
            all_rows.extend(rows)
            request_count += attempts
            cursor = chunk_end + timedelta(days=1)
            if cursor <= end and self.request_delay_seconds:
                time.sleep(self.request_delay_seconds)

        parsed: dict[datetime, CompletedBar] = {}
        invalid_rows = 0
        duplicate_rows = 0
        for raw in all_rows:
            try:
                bar = _parse_candle(raw, instrument.symbol)
            except (ValueError, TypeError, InvalidOperation, OverflowError):
                invalid_rows += 1
                continue
            if bar.start_time.date() < start or bar.start_time.date() > end:
                invalid_rows += 1
                continue
            if bar.start_time in parsed:
                duplicate_rows += 1
                continue
            parsed[bar.start_time] = bar

        bars = tuple(parsed[key] for key in sorted(parsed))
        return HistoryFetchResult(
            symbol=instrument.symbol,
            bars=bars,
            request_count=request_count,
            invalid_rows=invalid_rows,
            duplicate_rows=duplicate_rows,
            requested_from=start,
            requested_to=end,
        )
