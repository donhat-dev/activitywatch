from datetime import datetime, timedelta, timezone

from aw_core.models import Event

from aw_odoo_sync.sync import (
    _normalize_screenshot_cycle_secs,
    _screenshot_target_key,
    _screenshot_target_times,
    _stable_event_id,
    _wall_clock_cycle_starts,
)


def test_stable_event_id_ignores_activitywatch_numeric_id():
    timestamp = datetime(2026, 5, 15, 3, 0, tzinfo=timezone.utc)
    data = {"bucket": "aw-watcher-input_host", "clicks": 0, "presses": 0}
    first = Event(id=81, timestamp=timestamp, duration=timedelta(seconds=3.12), data=data)
    second = Event(id=123, timestamp=timestamp, duration=timedelta(seconds=3.12), data=data)

    assert _stable_event_id("aw-watcher-input_host", first, data) == _stable_event_id(
        "aw-watcher-input_host",
        second,
        data,
    )


def test_screenshot_targets_are_deterministic_per_wall_clock_cycle():
    context = {
        "timer_session_id": 42,
        "started_at": "2026-05-15T03:00:00+00:00",
        "screenshot_per_cycle": 3,
        "cycle_time_secs": 600,
    }
    changed_context = {
        **context,
        "timer_session_id": 99,
        "started_at": "2026-05-15T03:04:00+00:00",
        "task_id": 123,
    }
    cycle_start = datetime(2026, 5, 15, 10, 0, tzinfo=timezone(timedelta(hours=7)))

    first = _screenshot_target_times(context, cycle_start, bucket_id="bucket", device_id="device")
    second = _screenshot_target_times(context, cycle_start, bucket_id="bucket", device_id="device")
    changed_task = _screenshot_target_times(changed_context, cycle_start, bucket_id="bucket", device_id="device")
    next_cycle = _screenshot_target_times(
        context,
        cycle_start + timedelta(minutes=10),
        bucket_id="bucket",
        device_id="device",
    )

    assert first == second
    assert first == changed_task
    assert len(first) == 3
    assert all(target.second == 0 and target.microsecond == 0 for target in first)
    assert first != next_cycle


def test_wall_clock_cycle_start_uses_local_midnight():
    local_tz = timezone(timedelta(hours=7))
    now = datetime(2026, 5, 15, 3, 4, tzinfo=timezone.utc)

    previous_cycle, current_cycle = _wall_clock_cycle_starts(now, 600, local_tz)

    assert previous_cycle == datetime(2026, 5, 15, 9, 50, tzinfo=local_tz)
    assert current_cycle == datetime(2026, 5, 15, 10, 0, tzinfo=local_tz)


def test_wall_clock_cycle_start_for_thirty_minute_cycle():
    local_tz = timezone(timedelta(hours=7))
    now = datetime(2026, 5, 15, 3, 48, tzinfo=timezone.utc)

    previous_cycle, current_cycle = _wall_clock_cycle_starts(now, 1800, local_tz)

    assert previous_cycle == datetime(2026, 5, 15, 10, 0, tzinfo=local_tz)
    assert current_cycle == datetime(2026, 5, 15, 10, 30, tzinfo=local_tz)


def test_screenshot_targets_return_utc_from_local_cycle():
    local_tz = timezone(timedelta(hours=7))
    context = {"screenshot_per_cycle": 3, "cycle_time_secs": 600}
    cycle_start = datetime(2026, 5, 15, 10, 0, tzinfo=local_tz)

    targets = _screenshot_target_times(context, cycle_start, bucket_id="bucket", device_id="device")

    assert len(targets) == 3
    assert all(target.tzinfo == timezone.utc for target in targets)
    assert all(
        datetime(2026, 5, 15, 3, 0, tzinfo=timezone.utc)
        <= target
        < datetime(2026, 5, 15, 3, 10, tzinfo=timezone.utc)
        for target in targets
    )


def test_screenshot_cycle_seconds_are_rounded_and_clamped():
    assert _normalize_screenshot_cycle_secs(650, warn=False) == 660
    assert _normalize_screenshot_cycle_secs(30, warn=False) == 60
    assert _normalize_screenshot_cycle_secs(3600, warn=False) == 3540
    assert _normalize_screenshot_cycle_secs("bad", default=600, warn=False) == 600


def test_screenshot_target_key_uses_wall_clock_target():
    local_tz = timezone(timedelta(hours=7))
    cycle_start = datetime(2026, 5, 15, 10, 0, tzinfo=local_tz)
    target = datetime(2026, 5, 15, 3, 5, tzinfo=timezone.utc)

    first = _screenshot_target_key("bucket", "device", cycle_start, target)
    second = _screenshot_target_key("bucket", "device", cycle_start, target)
    next_cycle = _screenshot_target_key("bucket", "device", cycle_start + timedelta(minutes=10), target)

    assert first == second
    assert first.endswith("|5")
    assert first != next_cycle
