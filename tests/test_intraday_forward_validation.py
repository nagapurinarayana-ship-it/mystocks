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



def test_session_tracker_rejects_samples_after_its_market_date():
    tracker = ForwardSessionTracker(at_ist(9, 15), paper_engine_enabled=True)
    next_day = datetime(2026, 11, 5, 9, 15, tzinfo=IST)
    with pytest.raises(ValueError, match="session date"):
        tracker.sample(next_day, "healthy")



def test_feed_health_time_is_attributed_to_the_state_at_interval_start():
    tracker = ForwardSessionTracker(at_ist(9, 15), paper_engine_enabled=True)
    tracker.sample(at_ist(9, 15), "healthy")
    tracker.sample(at_ist(9, 15, 2), "stale")
    tracker.sample(at_ist(9, 15, 4), "stale")

    snapshot = tracker.snapshot()
    assert snapshot["healthy_seconds"] == 2.0
    assert snapshot["stale_seconds"] == 2.0


def test_last_feed_state_is_preserved_when_tracker_snapshot_is_restored():
    tracker = ForwardSessionTracker(at_ist(9, 15), paper_engine_enabled=True)
    tracker.sample(at_ist(9, 15), "healthy")
    tracker.sample(at_ist(9, 15, 2), "stale")
    snapshot = tracker.snapshot()
    restored = ForwardSessionTracker.from_snapshot(snapshot)

    restored.sample(at_ist(9, 15, 4), "disconnected")
    result = restored.snapshot()
    assert result["stale_seconds"] == 2.0
    assert result["last_sample_state"] == "disconnected"



@pytest.mark.parametrize(
    "mutation, message",
    [
        (lambda snapshot: snapshot.update(session_date="2026-11-05"), "date does not match"),
        (lambda snapshot: snapshot.update(last_sample_at="2026-11-04T09:16:00"), "timezone-aware"),
        (lambda snapshot: snapshot.update(paper_engine_enabled="false"), "boolean"),
        (lambda snapshot: snapshot.update(observed_seconds=float("nan")), "finite and nonnegative"),
        (lambda snapshot: snapshot.update(accepted_ticks=-1), "nonnegative integer"),
    ],
)
def test_corrupt_forward_session_snapshots_fail_closed(mutation, message):
    tracker = ForwardSessionTracker(at_ist(9, 15), paper_engine_enabled=True)
    tracker.record_tick()
    tracker.sample(at_ist(9, 15, 2), "healthy")
    snapshot = tracker.snapshot()
    invalid = dict(snapshot)
    mutation(invalid)

    with pytest.raises(ValueError, match=message):
        ForwardSessionTracker.from_snapshot(invalid)


def test_forward_tracker_requires_boolean_paper_engine_flag():
    with pytest.raises(ValueError, match="boolean"):
        ForwardSessionTracker(at_ist(9, 15), paper_engine_enabled="yes")



def test_first_feed_state_sample_does_not_claim_unobserved_prior_time():
    tracker = ForwardSessionTracker(at_ist(9, 15), paper_engine_enabled=True)
    tracker.sample(at_ist(9, 15, 1), "healthy")
    tracker.sample(at_ist(9, 15, 2), "stale")

    result = tracker.snapshot()
    assert result["observed_seconds"] == 1.0
    assert result["healthy_seconds"] == 1.0
    assert result["stale_seconds"] == 0.0
