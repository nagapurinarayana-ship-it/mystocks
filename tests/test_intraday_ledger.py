from datetime import datetime
from decimal import Decimal
from zoneinfo import ZoneInfo

from intraday.domain import TradeSignal
from intraday.execution.paper import PaperTrade
from intraday.ledger import PaperLedger

IST = ZoneInfo("Asia/Kolkata")


def test_ledger_persists_signals_trades_and_events_without_secrets(tmp_path):
    database = tmp_path / "intraday.sqlite3"
    signal = TradeSignal(
        strategy_id="vwap_momentum",
        symbol="RELIANCE",
        generated_at=datetime(2026, 11, 4, 10, 0, tzinfo=IST),
        entry_reference=100.0,
        stop_price=99.0,
        target_price=102.0,
        volume_ratio=1.5,
        score=75.0,
        explanation="confirmed completed-candle setup",
    )
    trade = PaperTrade(
        symbol="RELIANCE",
        quantity=1,
        entry_price=Decimal("100.05"),
        exit_price=Decimal("102.00"),
        entry_time=datetime(2026, 11, 4, 10, 0, tzinfo=IST),
        exit_time=datetime(2026, 11, 4, 10, 10, tzinfo=IST),
        gross_pnl=Decimal("1.95"),
        charges=Decimal("0.10"),
        net_pnl=Decimal("1.85"),
        exit_reason="profit_target",
        strategy_id="vwap_momentum",
    )

    with PaperLedger(database) as ledger:
        assert ledger.record_signal(signal) is True
        assert ledger.record_signal(signal) is False
        assert ledger.record_trade(trade) is True
        assert ledger.record_trade(trade) is False
        ledger.record_event(
            datetime(2026, 11, 4, 10, 0, tzinfo=IST).isoformat(),
            "INFO", "feed_connected", "WebSocket connected",
        )
        performance = ledger.paper_performance()
        assert performance["trades"] == 1
        assert performance["wins"] == 1
        assert performance["losses"] == 0
        assert performance["realised_net_pnl"] == 1.85
        assert performance["charges"] == 0.10
        assert ledger.latest_event()["code"] == "feed_connected"

    with PaperLedger(database) as reopened:
        assert len(reopened.recent_signals()) == 1
        assert len(reopened.recent_trades()) == 1
        assert reopened.recent_trades()[0]["exit_reason"] == "profit_target"


def test_ledger_validates_query_limits():
    import pytest
    with PaperLedger(":memory:") as ledger:
        with pytest.raises(ValueError):
            ledger.recent_signals(0)
        with pytest.raises(ValueError):
            ledger.recent_trades(501)
