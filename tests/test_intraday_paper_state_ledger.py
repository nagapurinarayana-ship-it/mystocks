import pytest

from intraday.ledger import PaperLedger


def test_paper_account_state_persists_across_ledger_reopen(tmp_path):
    database = tmp_path / "paper-state.sqlite3"
    snapshot = {
        "version": 1,
        "fee_schedule": {
            "brokerage_rate": "0.0001",
            "brokerage_cap_per_order": "20",
            "exchange_transaction_rate": "0.00001",
            "sebi_turnover_rate": "0.000001",
            "gst_rate": "0.18",
            "stt_sell_rate": "0.00025",
            "stamp_buy_rate": "0.00003",
            "slippage_bps": "5",
        },
        "cash": "899.50",
        "day": "2026-11-04",
        "day_start_cash": "1000",
        "daily_net_pnl": "-3.50",
        "overnight_exit_pending": False,
        "position": None,
        "pending": None,
    }

    with PaperLedger(database) as ledger:
        assert ledger.load_paper_state() is None
        ledger.save_paper_state(snapshot, "2026-11-04T10:00:00+05:30")
        assert ledger.paper_state_updated_at() == "2026-11-04T10:00:00+05:30"

    with PaperLedger(database) as reopened:
        assert reopened.load_paper_state() == snapshot


def test_paper_state_rejects_non_json_and_nan_values(tmp_path):
    with PaperLedger(tmp_path / "bad-state.sqlite3") as ledger:
        with pytest.raises(ValueError, match="valid JSON"):
            ledger.save_paper_state({"value": float("nan")}, "2026-11-04T10:00:00+05:30")
        with pytest.raises(ValueError, match="valid JSON"):
            ledger.save_paper_state({"value": object()}, "2026-11-04T10:00:00+05:30")


def test_corrupt_persisted_paper_state_fails_closed(tmp_path):
    database = tmp_path / "corrupt-state.sqlite3"
    with PaperLedger(database) as ledger:
        ledger._connection.execute(
            "INSERT INTO intraday_paper_state (id, state_json, updated_at) VALUES (1, ?, ?)",
            ("{not-json", "2026-11-04T10:00:00+05:30"),
        )
        ledger._connection.commit()
        with pytest.raises(ValueError, match="corrupt"):
            ledger.load_paper_state()
