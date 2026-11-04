"""Autonomous paper execution with cash-only sizing and broker-specific costs.

This module cannot call a broker. A concrete fee schedule must be supplied from
the chosen broker's current published tariff; no default fee assumptions exist.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal, ROUND_CEILING, ROUND_FLOOR
from typing import Literal

from intraday.config import DEFAULT_CAPITAL_POLICY, CapitalPolicy
from intraday.domain import CompletedBar, Instrument, TradeSignal


ZERO = Decimal("0")
TEN_THOUSAND = Decimal("10000")


def _floor_tick(price: Decimal, tick_size: Decimal) -> Decimal:
    return (price / tick_size).to_integral_value(rounding=ROUND_FLOOR) * tick_size


def _ceil_tick(price: Decimal, tick_size: Decimal) -> Decimal:
    return (price / tick_size).to_integral_value(rounding=ROUND_CEILING) * tick_size


def _dec(value: Decimal | int | float | str, field: str) -> Decimal:
    try:
        result = value if isinstance(value, Decimal) else Decimal(str(value))
    except Exception as exc:
        raise ValueError(f"{field} must be a valid decimal") from exc
    if not result.is_finite():
        raise ValueError(f"{field} must be finite")
    return result


@dataclass(frozen=True, slots=True)
class FeeSchedule:
    """Explicit broker tariff parameters; all rates are proportions, not % points."""

    brokerage_rate: Decimal
    brokerage_cap_per_order: Decimal
    exchange_transaction_rate: Decimal
    sebi_turnover_rate: Decimal
    gst_rate: Decimal
    stt_sell_rate: Decimal
    stamp_buy_rate: Decimal
    slippage_bps: Decimal

    def __post_init__(self) -> None:
        for name in (
            "brokerage_rate", "brokerage_cap_per_order",
            "exchange_transaction_rate", "sebi_turnover_rate", "gst_rate",
            "stt_sell_rate", "stamp_buy_rate", "slippage_bps",
        ):
            value = _dec(getattr(self, name), name)
            object.__setattr__(self, name, value)
            if value < ZERO:
                raise ValueError(f"{name} cannot be negative")
        if self.brokerage_cap_per_order <= ZERO:
            raise ValueError("brokerage_cap_per_order must be positive")
        if self.slippage_bps > Decimal("1000"):
            raise ValueError("slippage_bps cannot exceed 10%")

    @property
    def slippage_rate(self) -> Decimal:
        return self.slippage_bps / TEN_THOUSAND

    def _common_charges(self, turnover: Decimal) -> tuple[Decimal, Decimal]:
        brokerage = min(turnover * self.brokerage_rate, self.brokerage_cap_per_order)
        exchange = turnover * self.exchange_transaction_rate
        sebi = turnover * self.sebi_turnover_rate
        gst = (brokerage + exchange + sebi) * self.gst_rate
        return brokerage, exchange + sebi + gst

    def buy_charges(self, price: Decimal, quantity: int) -> Decimal:
        value = price * quantity
        brokerage, other = self._common_charges(value)
        return brokerage + other + value * self.stamp_buy_rate

    def sell_charges(self, price: Decimal, quantity: int) -> Decimal:
        value = price * quantity
        brokerage, other = self._common_charges(value)
        return brokerage + other + value * self.stt_sell_rate

    def round_trip_charges(
        self, entry_price: Decimal, exit_price: Decimal, quantity: int
    ) -> Decimal:
        return self.buy_charges(entry_price, quantity) + self.sell_charges(exit_price, quantity)


@dataclass(frozen=True, slots=True)
class PaperEvent:
    event_type: Literal[
        "entry_filled", "exit_filled", "entry_and_exit_same_bar",
        "entry_rejected", "signal_expired", "risk_halt"
    ]
    symbol: str
    message: str
    quantity: int = 0
    price: Decimal | None = None


@dataclass(slots=True)
class PaperPosition:
    symbol: str
    quantity: int
    entry_price: Decimal
    stop_price: Decimal
    target_price: Decimal
    entry_fee: Decimal
    tick_size: Decimal
    opened_at: datetime
    strategy_id: str
    bars_held: int = 0


@dataclass(frozen=True, slots=True)
class PaperTrade:
    symbol: str
    quantity: int
    entry_price: Decimal
    exit_price: Decimal
    entry_time: datetime
    exit_time: datetime
    gross_pnl: Decimal
    charges: Decimal
    net_pnl: Decimal
    exit_reason: str
    strategy_id: str


class PaperExecutionEngine:
    """Single-position, long-only paper engine.

    It accepts signals generated from completed bars and fills at the next
    matching bar's open with adverse entry slippage. If stop and target are both
    touched in a bar, the stop is assumed to execute first. Real orders are not
    supported by this class.
    """

    def __init__(
        self,
        cost_schedule: FeeSchedule,
        policy: CapitalPolicy = DEFAULT_CAPITAL_POLICY,
        max_entry_drift_fraction: Decimal = Decimal("0.005"),
        max_hold_bars: int = 12,
    ) -> None:
        self.cost_schedule = cost_schedule
        self.policy = policy
        self.cash = policy.starting_capital
        self.position: PaperPosition | None = None
        self.pending: tuple[TradeSignal, Instrument] | None = None
        self.trades: list[PaperTrade] = []
        self.rejected_entries: list[str] = []
        self._day: object | None = None
        self._day_start_cash = self.cash
        self._daily_net_pnl = ZERO
        self._realised_net_pnl = ZERO
        self._overnight_exit_pending = False
        self.max_entry_drift_fraction = _dec(max_entry_drift_fraction, "max_entry_drift_fraction")
        self.max_hold_bars = max_hold_bars
        if not ZERO < self.max_entry_drift_fraction <= Decimal("0.02"):
            raise ValueError("max_entry_drift_fraction must be in (0, 2%]")
        if max_hold_bars < 1:
            raise ValueError("max_hold_bars must be positive")

    @property
    def daily_loss_limit(self) -> Decimal:
        return self._day_start_cash * self.policy.max_daily_loss_fraction

    @property
    def daily_net_pnl(self) -> Decimal:
        return self._daily_net_pnl

    @property
    def realised_net_pnl(self) -> Decimal:
        return self._realised_net_pnl

    def export_state(self) -> dict:
        """Export resumable simulation state without credentials or API tokens."""
        position = None
        if self.position is not None:
            item = self.position
            position = {
                "symbol": item.symbol,
                "quantity": item.quantity,
                "entry_price": str(item.entry_price),
                "stop_price": str(item.stop_price),
                "target_price": str(item.target_price),
                "entry_fee": str(item.entry_fee),
                "tick_size": str(item.tick_size),
                "opened_at": item.opened_at.isoformat(),
                "strategy_id": item.strategy_id,
                "bars_held": item.bars_held,
            }

        pending = None
        if self.pending is not None:
            signal, instrument = self.pending
            pending = {
                "signal": {
                    "strategy_id": signal.strategy_id,
                    "symbol": signal.symbol,
                    "generated_at": signal.generated_at.isoformat(),
                    "entry_reference": signal.entry_reference,
                    "stop_price": signal.stop_price,
                    "target_price": signal.target_price,
                    "volume_ratio": signal.volume_ratio,
                    "score": signal.score,
                    "explanation": signal.explanation,
                },
                "instrument": {
                    "symbol": instrument.symbol,
                    "instrument_key": instrument.instrument_key,
                    "name": instrument.name,
                    "tick_size": str(instrument.tick_size),
                    "lot_size": instrument.lot_size,
                    "security_type": instrument.security_type,
                },
            }

        return {
            "version": 2,
            "fee_schedule": {
                "brokerage_rate": str(self.cost_schedule.brokerage_rate),
                "brokerage_cap_per_order": str(self.cost_schedule.brokerage_cap_per_order),
                "exchange_transaction_rate": str(self.cost_schedule.exchange_transaction_rate),
                "sebi_turnover_rate": str(self.cost_schedule.sebi_turnover_rate),
                "gst_rate": str(self.cost_schedule.gst_rate),
                "stt_sell_rate": str(self.cost_schedule.stt_sell_rate),
                "stamp_buy_rate": str(self.cost_schedule.stamp_buy_rate),
                "slippage_bps": str(self.cost_schedule.slippage_bps),
            },
            "cash": str(self.cash),
            "day": self._day.isoformat() if isinstance(self._day, date) else None,
            "day_start_cash": str(self._day_start_cash),
            "daily_net_pnl": str(self._daily_net_pnl),
            "realised_net_pnl": str(self._realised_net_pnl),
            "overnight_exit_pending": bool(self._overnight_exit_pending),
            "position": position,
            "pending": pending,
        }

    def restore_state(self, state: dict) -> None:
        """Restore validated state. Any corruption raises instead of resetting equity."""
        if not isinstance(state, dict) or state.get("version") != 2:
            raise ValueError("unsupported or invalid paper-state version")

        def parse_aware(value: str, field: str) -> datetime:
            if not isinstance(value, str):
                raise ValueError(f"{field} must be an ISO timestamp")
            result = datetime.fromisoformat(value)
            if result.tzinfo is None or result.utcoffset() is None:
                raise ValueError(f"{field} must be timezone-aware")
            return result

        fee_data = state.get("fee_schedule")
        if not isinstance(fee_data, dict):
            raise ValueError("saved paper state has no fee schedule")
        try:
            saved_fees = FeeSchedule(**fee_data)
        except (TypeError, ValueError) as exc:
            raise ValueError("saved paper fee schedule is invalid") from exc
        if saved_fees != self.cost_schedule:
            raise ValueError("configured broker fee schedule differs from saved paper account state")

        cash = _dec(state.get("cash"), "cash")
        day_start_cash = _dec(state.get("day_start_cash"), "day_start_cash")
        daily_net_pnl = _dec(state.get("daily_net_pnl"), "daily_net_pnl")
        realised_net_pnl = _dec(state.get("realised_net_pnl"), "realised_net_pnl")
        if cash < ZERO or day_start_cash <= ZERO:
            raise ValueError("saved paper cash values are invalid")

        position_data = state.get("position")
        position = None
        if position_data is not None:
            if not isinstance(position_data, dict):
                raise ValueError("saved position is invalid")
            position = PaperPosition(
                symbol=str(position_data["symbol"]),
                quantity=int(position_data["quantity"]),
                entry_price=_dec(position_data["entry_price"], "position.entry_price"),
                stop_price=_dec(position_data["stop_price"], "position.stop_price"),
                target_price=_dec(position_data["target_price"], "position.target_price"),
                entry_fee=_dec(position_data["entry_fee"], "position.entry_fee"),
                tick_size=_dec(position_data["tick_size"], "position.tick_size"),
                opened_at=parse_aware(position_data["opened_at"], "position.opened_at"),
                strategy_id=str(position_data["strategy_id"]),
                bars_held=int(position_data.get("bars_held", 0)),
            )
            if (
                position.quantity < 1 or position.entry_price <= ZERO
                or position.tick_size <= ZERO or position.entry_fee < ZERO
                or not position.stop_price < position.entry_price < position.target_price
                or position.bars_held < 0
            ):
                raise ValueError("saved paper position failed validation")

        pending_data = state.get("pending")
        pending = None
        if pending_data is not None:
            if not isinstance(pending_data, dict):
                raise ValueError("saved pending entry is invalid")
            signal_data = pending_data["signal"]
            instrument_data = pending_data["instrument"]
            pending_signal = TradeSignal(
                strategy_id=str(signal_data["strategy_id"]),
                symbol=str(signal_data["symbol"]),
                generated_at=parse_aware(signal_data["generated_at"], "pending.generated_at"),
                entry_reference=float(signal_data["entry_reference"]),
                stop_price=float(signal_data["stop_price"]),
                target_price=float(signal_data["target_price"]),
                volume_ratio=float(signal_data["volume_ratio"]),
                score=float(signal_data["score"]),
                explanation=str(signal_data["explanation"]),
            )
            pending_instrument = Instrument(
                symbol=str(instrument_data["symbol"]),
                instrument_key=str(instrument_data["instrument_key"]),
                name=str(instrument_data["name"]),
                tick_size=_dec(instrument_data["tick_size"], "pending.instrument.tick_size"),
                lot_size=int(instrument_data["lot_size"]),
                security_type=str(instrument_data["security_type"]),
            )
            if pending_signal.symbol != pending_instrument.symbol:
                raise ValueError("saved pending signal and instrument do not match")
            pending = (pending_signal, pending_instrument)

        if position is not None and pending is not None:
            raise ValueError("saved state cannot contain both an open position and pending entry")

        day_value = state.get("day")
        restored_day = date.fromisoformat(day_value) if day_value else None
        if state.get("overnight_exit_pending") and position is None:
            raise ValueError("overnight exit flag requires an open position")

        # Assign only after all fields have passed validation.
        self.cash = cash
        self.position = position
        self.pending = pending
        self._day = restored_day
        self._day_start_cash = day_start_cash
        self._daily_net_pnl = daily_net_pnl
        self._realised_net_pnl = realised_net_pnl
        self._overnight_exit_pending = bool(state.get("overnight_exit_pending", False))
        self.trades.clear()
        self.rejected_entries.clear()

    def submit_signal(self, signal: TradeSignal, instrument: Instrument) -> bool:
        if self.position is not None or self.pending is not None:
            return False
        if signal.symbol != instrument.symbol or instrument.lot_size != 1:
            return False
        if self._daily_net_pnl <= -self.daily_loss_limit:
            return False
        self.pending = (signal, instrument)
        return True

    def on_bar(self, bar: CompletedBar) -> PaperEvent | None:
        day = bar.end_time.date()
        if self._day is None:
            self._day = day
            self._day_start_cash = self.cash
        elif day != self._day:
            self.pending = None
            self._day = day
            self._day_start_cash = self.cash
            self._daily_net_pnl = ZERO
            self._overnight_exit_pending = self.position is not None

        if self.position is not None:
            if self._overnight_exit_pending and bar.symbol == self.position.symbol:
                self._overnight_exit_pending = False
                return self._close_position(
                    bar, _dec(bar.open, "bar.open"),
                    "overnight_safety_exit", apply_slippage=True
                )
            return self._manage_position(bar)
        if self.pending is not None:
            return self._try_entry(bar)
        return None

    def _try_entry(self, bar: CompletedBar) -> PaperEvent | None:
        assert self.pending is not None
        signal, instrument = self.pending
        if bar.symbol != signal.symbol:
            return None
        # With only completed 5-minute OHLC bars, never fill at the open of
        # the bar that began at the signal timestamp: that open happened
        # before the completed-bar signal was available to the strategy.
        if bar.start_time <= signal.generated_at:
            return None
        self.pending = None
        if (
            bar.start_time.date() != signal.generated_at.date()
            or (bar.start_time - signal.generated_at).total_seconds() > 300
        ):
            self.rejected_entries.append(f"{signal.symbol}:signal_expired_before_next_bar")
            return PaperEvent("signal_expired", signal.symbol, "Candidate did not receive a next five-minute bar")

        reference = _dec(signal.entry_reference, "entry_reference")
        open_price = _dec(bar.open, "bar.open")
        stop = _floor_tick(_dec(signal.stop_price, "stop_price"), instrument.tick_size)
        target = _ceil_tick(_dec(signal.target_price, "target_price"), instrument.tick_size)
        drift = abs(open_price - reference) / reference
        if drift > self.max_entry_drift_fraction or open_price <= stop or open_price >= target:
            self.rejected_entries.append(f"{signal.symbol}:entry_gap_or_signal_expired")
            return PaperEvent("signal_expired", signal.symbol, "Next-bar open moved outside the entry rule")

        slip = self.cost_schedule.slippage_rate
        entry_fill = _ceil_tick(open_price * (Decimal("1") + slip), instrument.tick_size)
        stop_fill = _floor_tick(stop * (Decimal("1") - slip), instrument.tick_size)
        if entry_fill <= stop_fill:
            self.rejected_entries.append(f"{signal.symbol}:invalid_stop_after_slippage")
            return PaperEvent("entry_rejected", signal.symbol, "Stop distance is invalid after slippage")

        max_cash_qty = int((self.cash / entry_fill).to_integral_value(rounding=ROUND_FLOOR))
        risk_budget = self.cash * self.policy.max_risk_per_trade_fraction
        low, high, best = 1, max_cash_qty, 0
        while low <= high:
            quantity = (low + high) // 2
            buy_fee = self.cost_schedule.buy_charges(entry_fill, quantity)
            estimated_sell_fee = self.cost_schedule.sell_charges(stop_fill, quantity)
            planned_loss = (entry_fill - stop_fill) * quantity + buy_fee + estimated_sell_fee
            cash_required = entry_fill * quantity + buy_fee
            if planned_loss <= risk_budget and cash_required <= self.cash:
                best = quantity
                low = quantity + 1
            else:
                high = quantity - 1

        if best < 1:
            message = "No whole-share quantity fits cash, costs and planned-risk budget"
            self.rejected_entries.append(f"{signal.symbol}:{message}")
            return PaperEvent("entry_rejected", signal.symbol, message)

        entry_fee = self.cost_schedule.buy_charges(entry_fill, best)
        self.cash -= entry_fill * best + entry_fee
        self.position = PaperPosition(
            symbol=signal.symbol,
            quantity=best,
            entry_price=entry_fill,
            stop_price=stop,
            target_price=target,
            entry_fee=entry_fee,
            tick_size=instrument.tick_size,
            opened_at=bar.start_time,
            strategy_id=signal.strategy_id,
        )

        # The eligible entry bar is only processed once it is complete. Its
        # high/low therefore must be checked; otherwise a stop/target hit in
        # the entry bar would be silently ignored and the backtest would bias
        # results upward.
        hit_stop = _dec(bar.low, "bar.low") <= stop
        hit_target = _dec(bar.high, "bar.high") >= target
        if hit_stop or hit_target:
            if hit_stop:
                reason = "entry_bar_stop_first" if hit_target else "entry_bar_stop"
                raw_exit = stop
                adverse = True
            else:
                reason = "entry_bar_profit_target"
                raw_exit = target
                adverse = False
            exit_event = self._close_position(
                bar, raw_exit, reason, apply_slippage=adverse
            )
            return PaperEvent(
                "entry_and_exit_same_bar",
                signal.symbol,
                f"Paper entry and exit occurred within the same 5-minute bar: {reason}; "
                f"net P&L ₹{self.trades[-1].net_pnl:.2f}",
                quantity=best,
                price=exit_event.price,
            )

        return PaperEvent(
            "entry_filled", signal.symbol, "Paper entry filled at eligible next-bar open with adverse slippage",
            quantity=best, price=entry_fill,
        )

    def cancel_pending_entry(self, reason: str = "entry window closed") -> PaperEvent | None:
        if self.pending is None:
            return None
        signal, _instrument = self.pending
        self.pending = None
        return PaperEvent("signal_expired", signal.symbol, reason)

    def force_session_close(self, bar: CompletedBar) -> PaperEvent | None:
        """Close any paper position and cancel a pending entry before session end."""
        self.pending = None
        if self.position is None:
            return None
        if bar.symbol != self.position.symbol:
            return None
        return self._close_position(
            bar, _dec(bar.close, "bar.close"), "session_close", apply_slippage=True
        )

    def _manage_position(self, bar: CompletedBar) -> PaperEvent | None:
        position = self.position
        assert position is not None
        if bar.symbol != position.symbol or bar.start_time <= position.opened_at:
            return None
        position.bars_held += 1

        open_price = _dec(bar.open, "bar.open")
        low = _dec(bar.low, "bar.low")
        high = _dec(bar.high, "bar.high")

        # Gap through stop is filled at the worse opening price.
        if open_price <= position.stop_price:
            return self._close_position(bar, open_price, "gap_stop", apply_slippage=True)
        if open_price >= position.target_price:
            return self._close_position(bar, open_price, "gap_target", apply_slippage=False)

        hit_stop = low <= position.stop_price
        hit_target = high >= position.target_price
        if hit_stop and hit_target:
            return self._close_position(bar, position.stop_price, "same_bar_stop_first", apply_slippage=True)
        if hit_stop:
            return self._close_position(bar, position.stop_price, "stop_loss", apply_slippage=True)
        if hit_target:
            return self._close_position(bar, position.target_price, "profit_target", apply_slippage=False)
        if position.bars_held >= self.max_hold_bars:
            return self._close_position(bar, _dec(bar.close, "bar.close"), "time_exit", apply_slippage=True)
        return None

    def _close_position(
        self,
        bar: CompletedBar,
        raw_exit_price: Decimal,
        reason: str,
        apply_slippage: bool,
    ) -> PaperEvent:
        position = self.position
        assert position is not None
        exit_price = raw_exit_price
        if apply_slippage:
            exit_price = _floor_tick(
                exit_price * (Decimal("1") - self.cost_schedule.slippage_rate),
                position.tick_size,
            )
        sell_fee = self.cost_schedule.sell_charges(exit_price, position.quantity)
        proceeds = exit_price * position.quantity - sell_fee
        self.cash += proceeds
        gross = (exit_price - position.entry_price) * position.quantity
        charges = position.entry_fee + sell_fee
        net = gross - charges
        trade = PaperTrade(
            symbol=position.symbol,
            quantity=position.quantity,
            entry_price=position.entry_price,
            exit_price=exit_price,
            entry_time=position.opened_at,
            exit_time=bar.end_time,
            gross_pnl=gross,
            charges=charges,
            net_pnl=net,
            exit_reason=reason,
            strategy_id=position.strategy_id,
        )
        self.trades.append(trade)
        self._daily_net_pnl += net
        self._realised_net_pnl += net
        self.position = None
        return PaperEvent(
            "exit_filled", position.symbol,
            f"Paper exit: {reason}; net P&L ₹{net:.2f}",
            quantity=position.quantity, price=exit_price,
        )
