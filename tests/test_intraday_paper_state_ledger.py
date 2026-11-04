from datetime import datetime, timedelta, timezone

import threading

import pytest

from intraday.ledger import PaperLedger, RuntimeLease


def test_paper_account_state_persists_across_ledger_reopen(tmp_path):
    database = tmp_path / "paper-state.sqlite3"
    snapshot = {
        "version": 3,
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
        "realised_net_pnl": "15.25",
        "overnight_exit_pending": False,
        "halted_reason": None,
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



def test_forward_validation_session_is_persisted_and_counted_by_status(tmp_path):
    database = tmp_path / "forward-validation.sqlite3"
    qualified = {
        "session_date": "2026-11-04",
        "status": "qualified",
        "started_at": "2026-11-04T03:45:00+00:00",
        "last_sample_at": "2026-11-04T10:00:00+00:00",
        "closed_at": "2026-11-04T10:00:00+00:00",
        "accepted_ticks": 1000,
        "coverage_ratio": 0.999,
        "healthy_ratio": 0.999,
    }
    incomplete = {
        "session_date": "2026-11-03",
        "status": "incomplete",
        "started_at": "2026-11-03T05:00:00+00:00",
        "accepted_ticks": 50,
        "coverage_ratio": 0.4,
        "healthy_ratio": 0.7,
    }

    with PaperLedger(database) as ledger:
        ledger.save_forward_session(qualified, "2026-11-04T10:00:00+00:00")
        ledger.save_forward_session(incomplete, "2026-11-03T10:00:00+00:00")
        assert ledger.load_forward_session("2026-11-04") == qualified
        assert ledger.forward_sessions(10) == [qualified, incomplete]
        assert ledger.forward_validation_summary() == {
            "total_sessions": 2,
            "qualified_sessions": 1,
            "incomplete_sessions": 1,
            "interrupted_sessions": 0,
            "in_progress_sessions": 0,
        }


def test_forward_validation_process_restart_marks_open_sessions_interrupted(tmp_path):
    database = tmp_path / "forward-validation-restart.sqlite3"
    snapshot = {
        "session_date": "2026-11-04",
        "status": "in_progress",
        "started_at": "2026-11-04T03:45:00+00:00",
        "last_sample_at": "2026-11-04T05:00:00+00:00",
        "accepted_ticks": 500,
    }
    with PaperLedger(database) as ledger:
        ledger.save_forward_session(snapshot, "2026-11-04T05:00:00+00:00")
        assert ledger.interrupt_open_forward_sessions(
            "2026-11-04T05:01:00+00:00"
        ) == 1
        saved = ledger.load_forward_session("2026-11-04")
        assert saved["status"] == "interrupted"
        assert "restarted" in saved["interruption_reason"]
        assert ledger.forward_validation_summary()["interrupted_sessions"] == 1
        assert ledger.interrupt_open_forward_sessions(
            "2026-11-04T05:02:00+00:00"
        ) == 0


def test_forward_validation_rejects_bad_snapshot_status_and_non_json_values(tmp_path):
    with PaperLedger(tmp_path / "forward-validation-invalid.sqlite3") as ledger:
        with pytest.raises(ValueError, match="status"):
            ledger.save_forward_session(
                {"session_date": "2026-11-04", "status": "ready"},
                "2026-11-04T10:00:00+00:00",
            )
        with pytest.raises(ValueError, match="valid JSON"):
            ledger.save_forward_session(
                {
                    "session_date": "2026-11-04",
                    "status": "in_progress",
                    "value": float("nan"),
                },
                "2026-11-04T10:00:00+00:00",
            )



def test_runtime_lease_allows_only_one_active_radar_and_releases_on_exit(tmp_path):
    database = tmp_path / "runtime-lease.sqlite3"
    with PaperLedger(database) as ledger, PaperLedger(database) as contender:
        with ledger.runtime_lease(
            "intraday_radar", "process-one", heartbeat_seconds=60
        ) as first:
            first.assert_held()
            with pytest.raises(RuntimeError, match="already owns"):
                with contender.runtime_lease(
                    "intraday_radar", "process-two", heartbeat_seconds=60
                ):
                    pytest.fail("second SQLite connection must not enter the lease")
        # The lease is released by the context manager, visible to a second connection.
        with contender.runtime_lease(
            "intraday_radar", "process-two", heartbeat_seconds=60
        ) as second:
            second.assert_held()


def test_runtime_lease_can_be_taken_over_after_expired_heartbeat(tmp_path):
    database = tmp_path / "runtime-lease-expired.sqlite3"
    first = datetime(2026, 11, 4, 10, 0, tzinfo=timezone.utc)
    with PaperLedger(database) as ledger:
        assert ledger.acquire_runtime_lease(
            "intraday_radar", "crashed-process", now=first,
            stale_after_seconds=30,
        )
        assert not ledger.acquire_runtime_lease(
            "intraday_radar", "second-process",
            now=first + timedelta(seconds=29),
            stale_after_seconds=30,
        )
        assert ledger.acquire_runtime_lease(
            "intraday_radar", "second-process",
            now=first + timedelta(seconds=31),
            stale_after_seconds=30,
        )
        assert not ledger.renew_runtime_lease(
            "intraday_radar", "crashed-process",
            now=first + timedelta(seconds=32),
        )
        assert ledger.renew_runtime_lease(
            "intraday_radar", "second-process",
            now=first + timedelta(seconds=32),
        )
        assert ledger.release_runtime_lease("intraday_radar", "second-process")


def test_runtime_lease_rejects_naive_heartbeat_timestamp(tmp_path):
    with PaperLedger(tmp_path / "runtime-lease-naive.sqlite3") as ledger:
        with pytest.raises(ValueError, match="timezone-aware"):
            ledger.acquire_runtime_lease(
                "intraday_radar", "process-one",
                now=datetime(2026, 11, 4, 10, 0),
            )



def test_runtime_lease_lost_heartbeat_marks_lease_unheld():
    class BrokenLedger:
        def renew_runtime_lease(self, *args, **kwargs):
            raise OSError("simulated database write failure")

        def release_runtime_lease(self, *args, **kwargs):
            return False

    lease = RuntimeLease(
        BrokenLedger(),
        "intraday_radar",
        "owner-one",
        heartbeat_seconds=0.01,
    )
    lease._entered = True
    lease._thread = threading.Thread(target=lease._heartbeat_loop, daemon=True)
    lease._thread.start()
    lease._thread.join(timeout=1)

    assert lease._lost.is_set()
    with pytest.raises(RuntimeError, match="lost its SQLite runtime lease"):
        lease.assert_held()
    lease.__exit__(None, None, None)
