"""Conservative, explainable long-only intraday research strategies."""

from __future__ import annotations

from datetime import datetime
from statistics import fmean

from intraday.domain import CompletedBar, Instrument, TradeSignal


def _atr(bars: tuple[CompletedBar, ...], period: int = 14) -> float:
    if len(bars) < period + 1:
        return 0.0
    ranges = []
    for previous, current in zip(bars[-period - 1:-1], bars[-period:]):
        ranges.append(max(
            current.high - current.low,
            abs(current.high - previous.close),
            abs(current.low - previous.close),
        ))
    return fmean(ranges)


def _build_signal(
    instrument: Instrument,
    strategy_id: str,
    bar: CompletedBar,
    atr: float,
    volume_ratio: float,
    explanation: str,
    score: float,
) -> TradeSignal | None:
    if atr <= 0:
        return None
    entry = bar.close
    stop = entry - (1.2 * atr)
    if stop <= 0 or stop >= entry:
        return None
    target = entry + (1.5 * (entry - stop))
    return TradeSignal(
        strategy_id=strategy_id,
        symbol=instrument.symbol,
        generated_at=bar.end_time,
        entry_reference=entry,
        stop_price=stop,
        target_price=target,
        volume_ratio=volume_ratio,
        score=score,
        explanation=explanation,
    )


def vwap_momentum_signal(
    instrument: Instrument,
    bars: tuple[CompletedBar, ...],
    session_vwap: float | None,
) -> TradeSignal | None:
    if len(bars) < 21 or session_vwap is None or session_vwap <= 0:
        return None
    last = bars[-1]
    prior = bars[-21:-1]
    closes_9 = [bar.close for bar in bars[-9:]]
    closes_20 = [bar.close for bar in bars[-20:]]
    avg_volume = fmean(bar.volume for bar in prior)
    if avg_volume <= 0:
        return None
    volume_ratio = last.volume / avg_volume
    fast = fmean(closes_9)
    slow = fmean(closes_20)

    conditions = (
        last.close > session_vwap
        and fast > slow
        and last.close > bars[-2].high
        and last.close > last.open
        and volume_ratio >= 1.3
    )
    if not conditions:
        return None
    return _build_signal(
        instrument, "vwap_momentum", last, _atr(bars), volume_ratio,
        "Completed 5-minute close above session VWAP; 9-bar mean above 20-bar "
        "mean; higher-high breakout with volume at least 1.3x prior 20-bar average.",
        score=min(100.0, 40.0 + volume_ratio * 10.0 + ((fast / slow) - 1.0) * 1000.0),
    )


def opening_range_breakout_signal(
    instrument: Instrument,
    bars: tuple[CompletedBar, ...],
    session_vwap: float | None,
) -> TradeSignal | None:
    if len(bars) < 4 or session_vwap is None or session_vwap <= 0:
        return None
    first = bars[:3]
    # Only use a genuine first 15-minute range beginning at 09:15 Asia/Kolkata.
    first_start = first[0].start_time
    if (first_start.hour, first_start.minute) != (9, 15):
        return None
    if any((bar.start_time.date() != first_start.date()) for bar in first):
        return None
    if any((bar.start_time - first_start).total_seconds() != i * 300 for i, bar in enumerate(first)):
        return None

    opening_high = max(bar.high for bar in first)
    last = bars[-1]
    prior = bars[-21:-1] if len(bars) >= 21 else bars[3:-1]
    if len(prior) < 1:
        return None
    avg_volume = fmean(bar.volume for bar in prior)
    if avg_volume <= 0:
        return None
    volume_ratio = last.volume / avg_volume
    if not (last.close > opening_high and last.close > session_vwap
            and last.close > last.open and volume_ratio >= 1.5):
        return None
    return _build_signal(
        instrument, "opening_range_breakout", last, _atr(bars), volume_ratio,
        "Completed 5-minute close above the first 15-minute high and session "
        "VWAP, with positive candle and at least 1.5x reference volume.",
        score=min(100.0, 45.0 + volume_ratio * 10.0),
    )
