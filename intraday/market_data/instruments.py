"""Instrument-master parsing with full include/exclude accounting."""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from typing import Iterable, Mapping, Any

from intraday.domain import Instrument


@dataclass(frozen=True, slots=True)
class InstrumentReconciliation:
    eligible: tuple[Instrument, ...]
    excluded: tuple[dict[str, str], ...]
    source_rows: int

    @property
    def accounted_rows(self) -> int:
        return len(self.eligible) + len(self.excluded)


def reconcile_nse_cash_equities(
    rows: Iterable[Mapping[str, Any]],
    suspended_keys: set[str] | None = None,
) -> InstrumentReconciliation:
    """Select broker-supported NSE cash EQ instruments and account for every row.

    This intentionally uses the broker's BOD instrument master. It does not
    claim to include securities that the selected broker does not distribute.
    """
    suspended = suspended_keys or set()
    eligible: list[Instrument] = []
    excluded: list[dict[str, str]] = []
    seen_keys: set[str] = set()
    seen_symbols: set[str] = set()
    count = 0

    for index, raw in enumerate(rows):
        count += 1
        symbol = str(raw.get("trading_symbol") or raw.get("tradingsymbol") or "").strip().upper()
        key = str(raw.get("instrument_key") or "").strip()
        reason = ""

        if str(raw.get("segment") or raw.get("exchange") or "").upper() not in {"NSE_EQ", "NSE"}:
            reason = "not_nse_equity_segment"
        elif str(raw.get("exchange") or "").upper() not in {"NSE", ""}:
            reason = "not_nse_exchange"
        elif str(raw.get("instrument_type") or "").upper() != "EQ":
            reason = "not_cash_equity"
        elif not symbol or not key:
            reason = "missing_symbol_or_instrument_key"
        elif key in suspended:
            reason = "broker_suspended_instrument"
        elif key in seen_keys or symbol in seen_symbols:
            reason = "duplicate_instrument"
        else:
            try:
                tick_size = Decimal(str(raw.get("tick_size")))
                lot_size = int(raw.get("lot_size", 1))
                if tick_size <= 0:
                    raise ValueError("non-positive tick size")
                if lot_size != 1:
                    reason = "non_single_share_lot"
            except (InvalidOperation, TypeError, ValueError):
                reason = "invalid_tick_or_lot_size"

        if reason:
            excluded.append({
                "row": str(index),
                "symbol": symbol or "UNKNOWN",
                "instrument_key": key or "UNKNOWN",
                "reason": reason,
            })
            continue

        security_type = str(raw.get("security_type") or "NORMAL").upper()
        if security_type != "NORMAL":
            excluded.append({
                "row": str(index),
                "symbol": symbol,
                "instrument_key": key,
                "reason": f"security_type_{security_type.lower()}",
            })
            continue

        try:
            item = Instrument(
                symbol=symbol,
                instrument_key=key,
                name=str(raw.get("name") or symbol),
                tick_size=tick_size,
                lot_size=lot_size,
                security_type=security_type,
            )
        except ValueError as exc:
            excluded.append({
                "row": str(index),
                "symbol": symbol,
                "instrument_key": key,
                "reason": f"validation_error:{exc}",
            })
            continue

        eligible.append(item)
        seen_keys.add(key)
        seen_symbols.add(symbol)

    result = InstrumentReconciliation(tuple(eligible), tuple(excluded), count)
    if result.accounted_rows != result.source_rows:
        raise AssertionError("instrument reconciliation lost source rows")
    return result


def parse_upstox_instrument_payload(payload: Any) -> list[Mapping[str, Any]]:
    """Accept either the provider's JSON array or a wrapped data array."""
    if isinstance(payload, list):
        return payload
    if isinstance(payload, dict):
        for key in ("data", "instruments"):
            candidate = payload.get(key)
            if isinstance(candidate, list):
                return candidate
    raise ValueError("unexpected instrument-master payload structure")
