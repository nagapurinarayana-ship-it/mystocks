"""Chronological intraday OHLCV backtest with explicit fill/cost assumptions."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import date, time
from decimal import Decimal
from statistics import fmean
from typing import Literal
from zoneinfo import ZoneInfo

from intraday.config import DEFAULT_CAPITAL_POLICY, CapitalPolicy
from intraday.domain import CompletedBar, Instrument
from intraday.execution.paper import FeeSchedule, PaperExecutionEngine
from intraday.strategies import (
    opening_range_breakout_signal,
    vwap_momentum_signal,
)

IST = ZoneInfo("Asia/Kolkata")
StrategyName = Literal["vwap_momentum", "opening_range_breakout"]


@dataclass(frozen=True, slots=True)
class BacktestSummary:
    symbol: str
    strategy_id: str
    from_date: str
    to_date: str
    trading_days: int
    bars: int
    trades: int
    wins: int
    losses: int
    win_rate: float
    gross_pnl: float
    charges: float
    net_pnl: float
    net_return_pct: float
    profit_factor: float | None
    max_drawdown_pct: float
    average_net_pnl_per_trade: float
    starting_capital: float
    ending_cash: float
    vwap_method: str
    execution_assumptions: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class BacktestResult:
    summary: BacktestSummary
    trades: tuple[dict, ...]


def _session_vwap_proxy(bars: tuple[CompletedBar, ...]) -> float | None:
    """Typical-price x volume proxy; OHLCV data does not contain trade-level VWAP."""
    total_volume = sum(bar.volume for bar in bars)
    if total_volume <= 0:
        return None
    value = sum(
        ((bar.high + bar.low + bar.close) / 3.0) * bar.volume
        for bar in bars
    )
    return value / total_volume


def _select_signal(
    strategy: StrategyName,
    instrument: Instrument,
    bars: tuple[CompletedBar, ...],
    vwap: float | None,
):
    if strategy == "vwap_momentum":
        return vwap_momentum_signal(instrument, bars, vwap)
    if strategy == "opening_range_breakout":
        return opening_range_breakout_signal(instrument, bars, vwap)
    raise ValueError(f"unsupported strategy: {strategy}")


def _drawdown_pct(trades, starting_capital: Decimal) -> float:
    equity = starting_capital
    peak = starting_capital
    max_drawdown = Decimal("0")
    for trade in trades:
        equity += trade.net_pnl
        peak = max(peak, equity)
        if peak > 0:
            drawdown = (peak - equity) / peak
            max_drawdown = max(max_drawdown, drawdown)
    return float(max_drawdown * Decimal("100"))


def run_intraday_backtest(
    instrument: Instrument,
    bars: tuple[CompletedBar, ...] | list[CompletedBar],
    strategy: StrategyName,
    cost_schedule: FeeSchedule,
    policy: CapitalPolicy = DEFAULT_CAPITAL_POLICY,
) -> BacktestResult:
    """Run one symbol chronologically, with no fabricated missing candles.

    Entry is at the next available 5-minute candle open. If the next candle is
    missing by more than five minutes, the signal expires. OHLC cannot reveal
    whether the stop or target happened first, so a same-candle collision is
    conservatively recorded as a stop. Target fills at the target price are
    optimistic with respect to queue position; live-market paper validation is
    separately required.
    """
    source = tuple(bars)
    if not source:
        raise ValueError("at least one historical bar is required")
    if any(bar.symbol != instrument.symbol for bar in source):
        raise ValueError("all historical bars must match the selected instrument")
    ordered = tuple(sorted(source, key=lambda bar: bar.start_time))
    starts = [bar.start_time for bar in ordered]
    if len(set(starts)) != len(starts):
        raise ValueError("historical bars contain duplicate start times")

    for bar in ordered:
        local_start = bar.start_time.astimezone(IST)
        if local_start.weekday() >= 5 or not (time(9, 15) <= local_start.time() < time(15, 30)):
            raise ValueError("historical bars include timestamps outside regular NSE weekday session")

    engine = PaperExecutionEngine(cost_schedule=cost_schedule, policy=policy)
    trade_day: date | None = None
    session_bars: list[CompletedBar] = []
    trading_days: set[date] = set()

    for bar in ordered:
        local_day = bar.start_time.astimezone(IST).date()
        if trade_day is None or local_day != trade_day:
            if session_bars:
                engine.force_session_close(session_bars[-1])
            trade_day = local_day
            session_bars = []
            trading_days.add(local_day)

        previous_trade_count = len(engine.trades)
        engine.on_bar(bar)
        session_bars.append(bar)

        # Avoid creating entries too near the close; the paper engine still
        # closes any open position using the final observed bar of the session.
        local_end = bar.end_time.astimezone(IST).time()
        if local_end >= time(15, 15):
            continue
        if engine.position is not None or engine.pending is not None:
            continue

        history = tuple(session_bars)
        vwap_proxy = _session_vwap_proxy(history)
        signal = _select_signal(strategy, instrument, history, vwap_proxy)
        if signal is not None:
            engine.submit_signal(signal, instrument)

    if session_bars:
        engine.force_session_close(session_bars[-1])

    trades = tuple(asdict(trade) for trade in engine.trades)
    gross = sum((trade.gross_pnl for trade in engine.trades), Decimal("0"))
    charges = sum((trade.charges for trade in engine.trades), Decimal("0"))
    net = sum((trade.net_pnl for trade in engine.trades), Decimal("0"))
    wins = sum(1 for trade in engine.trades if trade.net_pnl > 0)
    losses = sum(1 for trade in engine.trades if trade.net_pnl < 0)
    gross_wins = sum((trade.net_pnl for trade in engine.trades if trade.net_pnl > 0), Decimal("0"))
    gross_losses = abs(sum((trade.net_pnl for trade in engine.trades if trade.net_pnl < 0), Decimal("0")))
    profit_factor = float(gross_wins / gross_losses) if gross_losses > 0 else (None if gross_wins == 0 else float("inf"))
    count = len(engine.trades)
    initial = policy.starting_capital
    ending_cash = engine.cash

    summary = BacktestSummary(
        symbol=instrument.symbol,
        strategy_id=strategy,
        from_date=min(trading_days).isoformat() if trading_days else ordered[0].start_time.date().isoformat(),
        to_date=max(trading_days).isoformat() if trading_days else ordered[-1].end_time.date().isoformat(),
        trading_days=len(trading_days),
        bars=len(ordered),
        trades=count,
        wins=wins,
        losses=losses,
        win_rate=(wins / count) if count else 0.0,
        gross_pnl=float(gross),
        charges=float(charges),
        net_pnl=float(net),
        net_return_pct=float(net / initial * Decimal("100")),
        profit_factor=profit_factor,
        max_drawdown_pct=_drawdown_pct(engine.trades, initial),
        average_net_pnl_per_trade=float(net / count) if count else 0.0,
        starting_capital=float(initial),
        ending_cash=float(ending_cash),
        vwap_method="typical_price_times_volume_proxy_not_trade_level_vwap",
        execution_assumptions=(
            "one symbol, long-only, one open position",
            "whole-share cash-only size with configured risk budgets",
            "next available 5-minute bar open; candidate expires after 5 minutes",
            "broker-specific explicit fees plus configured adverse slippage",
            "same-bar stop and target collision resolves to stop first",
            "session close at last observed candle; no overnight carry",
            "no market impact, queue position or partial-fill model in OHLCV backtest",
            "not a point-in-time all-NSE universe backtest",
        ),
    )
    return BacktestResult(summary=summary, trades=trades)
