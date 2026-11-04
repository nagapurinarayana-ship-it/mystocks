from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

import pytest

from intraday.forward_validation import ForwardSessionTracker


IST = ZoneInfo("Asia/Kolkata")
UTC = timezone.utc


def at_ist(hour, minute, second=0):
    return datetime(2026, 11, 4, hour, minute, second, tzinfo=IST)


def simulate_full_healthy_session(tracker):
    start = at_ist(9, 15)
    end = at_ist(15, 30)
    cursor = start
    while cursor < end:
        tracker.sample(cursor, "healthy")
        cursor += timedelta(seconds=2)
    tracker.sample(end, "market_closed")


def test_full_day_healthy_capture_qualifies_as_a_data_session_not_profitability():
    tracker = ForwardSessionTracker(at_ist(9, 15), paper_engine_enabled=True)
    tracker.record_tick()
    tracker.record_signal()
    tracker.record_closed_trade()

    simulate_full_healthy_session(tracker)
    result = tracker.finish(at_ist(15, 30))

    assert result["status"] == "qualified"
    assert result["accepted_ticks"] == 1
    assert result["discovered_signals"] == 1
    assert result["closed_paper_trades"] == 1
    assert result["coverage_ratio"] >= 0.98
    assert result["healthy_ratio"] >= 0.98
    assert all(result["qualification_criteria"].values())


def test_late_start_cannot_count_as_a_full_forward_validation_session():
    tracker = ForwardSessionTracker(at_ist(10, 0), paper_engine_enabled=True)
    tracker.record_tick()
    end = at_ist(15, 30)
    cursor = at_ist(10, 0)
    while cursor < end:
        tracker.sample(cursor, "healthy")
        cursor += timedelta(seconds=2)
    tracker.sample(end, "market_closed")

    result = tracker.finish(end)
    assert result["status"] == "incomplete"
    assert result["qualification_criteria"]["started_by_09_16_ist"] is False


def test_stale_or_disconnected_feed_time_prevents_session_qualification():
    tracker = ForwardSessionTracker(at_ist(9, 15), paper_engine_enabled=True)
    tracker.record_tick()
    start, end = at_ist(9, 15), at_ist(15, 30)
    cursor = start
    while cursor < end:
        state = "healthy" if cursor < at_ist(12, 0) else "stale"
        tracker.sample(cursor, state)
        cursor += timedelta(seconds=2)
    tracker.sample(end, "market_closed")

    result = tracker.finish(end)
    assert result["status"] == "incomplete"
    assert result["healthy_ratio"] < 0.98
    assert result["qualification_criteria"]["healthy_feed_at_least_98_percent"] is False


def test_monitoring_pauses_are_not_counted_as_healthy_coverage():
    tracker = ForwardSessionTracker(at_ist(9, 15), paper_engine_enabled=True)
    tracker.record_tick()
    start, end = at_ist(9, 15), at_ist(15, 30)
    cursor = start
    sample_number = 0
    while cursor < end:
        tracker.sample(cursor, "healthy")
        cursor += timedelta(seconds=2)
        sample_number += 1
        if sample_number % 100 == 0:
            cursor += timedelta(seconds=3)
    tracker.sample(end, "market_closed")

    result = tracker.finish(end)
    assert result["loop_gap_count"] > 5
    assert result["status"] == "incomplete"
    assert result["qualification_criteria"]["no_more_than_five_loop_gaps"] is False


def test_paper_engine_disabled_means_feed_capture_does_not_count_as_paper_validation():
    tracker = ForwardSessionTracker(at_ist(9, 15), paper_engine_enabled=False)
    tracker.record_tick()
    simulate_full_healthy_session(tracker)
    result = tracker.finish(at_ist(15, 30))

    assert result["status"] == "incomplete"
    assert result["qualification_criteria"]["paper_engine_enabled_with_explicit_fees"] is False


def test_paper_risk_halt_prevents_a_session_from_being_marked_qualified():
    tracker = ForwardSessionTracker(at_ist(9, 15), paper_engine_enabled=True)
    tracker.record_tick()
    tracker.record_risk_halt()
    simulate_full_healthy_session(tracker)
    result = tracker.finish(at_ist(15, 30))

    assert result["status"] == "incomplete"
    assert result["risk_halts"] == 1
    assert result["qualification_criteria"]["no_paper_risk_halt"] is False


def test_session_finish_requires_aware_datetime_and_after_close():
    tracker = ForwardSessionTracker(at_ist(9, 15), paper_engine_enabled=True)
    with pytest.raises(ValueError, match="timezone-aware"):
        tracker.sample(datetime(2026, 11, 4, 10, 0), "healthy")
    with pytest.raises(ValueError, match="before 15:30"):
        tracker.finish(at_ist(15, 29, 59))


def test_session_snapshot_can_be_restored_and_marked_interrupted():
    tracker = ForwardSessionTracker(at_ist(9, 15), paper_engine_enabled=True)
    tracker.record_tick()
    tracker.sample(at_ist(9, 15, 1), "healthy")
    snapshot = tracker.snapshot()

    restored = ForwardSessionTracker.from_snapshot(snapshot)
    interrupted = restored.interrupt("process restarted")
    assert interrupted["status"] == "interrupted"
    assert interrupted["interruption_reason"] == "process restarted"
    assert interrupted["accepted_ticks"] == 1


def test_weekend_and_after_close_session_start_are_rejected():
    with pytest.raises(ValueError, match="weekdays"):
        ForwardSessionTracker(datetime(2026, 11, 7, 9, 15, tzinfo=IST))
    with pytest.raises(ValueError, match="15:30"):
        ForwardSessionTracker(at_ist(15, 30))
