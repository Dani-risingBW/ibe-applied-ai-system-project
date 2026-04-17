# Tests for google_calendar_integration.py — all Google API calls are mocked,
# no network connection or credentials file required to run these tests
import sys
from datetime import date, datetime, time, timedelta
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

from google_calendar_integration import (
    check_gcal_conflicts,
    fetch_gcal_events,
    gcal_event_to_task,
    push_task_to_gcal,
    task_to_gcal_event,
)
from pawpal_system import Owner, Priority, Scheduler, ScheduledTask, Task


# ── Helpers ───────────────────────────────────────────────────────────────────

# Builds a minimal event dict matching the structure returned by the Google Calendar API
def _make_gcal_event(summary, start_iso, end_iso, description=None):
    event = {
        "summary": summary,
        "start": {"dateTime": start_iso},
        "end": {"dateTime": end_iso},
    }
    if description:
        event["description"] = description
    return event


# Creates a Task with sensible defaults for use in tests
def _make_task(title, duration=30, priority=Priority.MEDIUM, scheduled_time=None, recurrence=None):
    return Task(
        id=None,
        title=title,
        duration_minutes=duration,
        priority=priority,
        scheduled_time=scheduled_time,
        recurrence=recurrence,
    )


# Wraps a task in a ScheduledTask using the task's own scheduled_time as the start
def _make_scheduled(task):
    return ScheduledTask(
        id=None,
        task=task,
        start_time=task.scheduled_time,
        end_time=task.estimate_end(task.scheduled_time),
    )


# ── gcal_event_to_task ────────────────────────────────────────────────────────

def test_gcal_event_to_task_returns_task_with_correct_title():
    event = _make_gcal_event("Vet visit", "2026-04-16T10:00:00+00:00", "2026-04-16T11:00:00+00:00")
    task = gcal_event_to_task(event)
    assert task is not None
    assert task.title == "Vet visit"


def test_gcal_event_to_task_calculates_duration_from_start_end():
    event = _make_gcal_event("Grooming", "2026-04-16T09:00:00+00:00", "2026-04-16T09:45:00+00:00")
    task = gcal_event_to_task(event)
    assert task is not None
    assert task.duration_minutes == 45


def test_gcal_event_to_task_sets_scheduled_time():
    event = _make_gcal_event("Walk", "2026-04-16T08:30:00+00:00", "2026-04-16T09:00:00+00:00")
    task = gcal_event_to_task(event)
    assert task is not None
    # Timezone info is stripped so the datetime stays naive, matching PawPal's format
    assert task.scheduled_time == datetime(2026, 4, 16, 8, 30, 0)


def test_gcal_event_to_task_all_day_event_uses_midnight():
    # All-day events use a date string (no time component) — anchored to midnight
    event = {"summary": "Pet day", "start": {"date": "2026-04-16"}, "end": {"date": "2026-04-17"}}
    task = gcal_event_to_task(event)
    assert task is not None
    assert task.scheduled_time == datetime(2026, 4, 16, 0, 0)


def test_gcal_event_to_task_returns_none_for_missing_start():
    task = gcal_event_to_task({"summary": "No time"})
    assert task is None


def test_gcal_event_to_task_uses_default_title_when_no_summary():
    event = _make_gcal_event("", "2026-04-16T10:00:00+00:00", "2026-04-16T10:30:00+00:00")
    event.pop("summary")
    task = gcal_event_to_task(event)
    assert task is not None
    assert "Untitled" in task.title


def test_gcal_event_to_task_maps_description_to_notes():
    event = _make_gcal_event(
        "Feeding",
        "2026-04-16T07:00:00+00:00",
        "2026-04-16T07:15:00+00:00",
        description="Give two scoops",
    )
    task = gcal_event_to_task(event)
    assert task is not None
    assert task.notes == "Give two scoops"


def test_gcal_event_to_task_defaults_duration_to_60_when_no_end():
    # Events with no end time fall back to 60 minutes
    event = {"summary": "Mystery event", "start": {"dateTime": "2026-04-16T10:00:00+00:00"}}
    task = gcal_event_to_task(event)
    assert task is not None
    assert task.duration_minutes == 60


# ── task_to_gcal_event ────────────────────────────────────────────────────────

def test_task_to_gcal_event_sets_summary():
    task = _make_task("Morning walk", scheduled_time=datetime(2026, 4, 16, 8, 0))
    event = task_to_gcal_event(task)
    assert event["summary"] == "Morning walk"


def test_task_to_gcal_event_start_and_end_are_rfc3339():
    # dateTime strings must include a UTC offset for Google Calendar to accept them
    task = _make_task("Feed cat", duration=15, scheduled_time=datetime(2026, 4, 16, 7, 0))
    event = task_to_gcal_event(task)
    assert "dateTime" in event["start"]
    assert "dateTime" in event["end"]
    assert "2026-04-16T07:00:00" in event["start"]["dateTime"]
    assert "2026-04-16T07:15:00" in event["end"]["dateTime"]


def test_task_to_gcal_event_raises_for_missing_scheduled_time():
    task = _make_task("No time task")
    with pytest.raises(ValueError, match="no scheduled_time"):
        task_to_gcal_event(task)


def test_task_to_gcal_event_high_priority_maps_to_red():
    task = _make_task("Urgent med", priority=Priority.HIGH, scheduled_time=datetime(2026, 4, 16, 9, 0))
    event = task_to_gcal_event(task)
    assert event["colorId"] == "11"


def test_task_to_gcal_event_medium_priority_maps_to_yellow():
    task = _make_task("Check water", priority=Priority.MEDIUM, scheduled_time=datetime(2026, 4, 16, 9, 0))
    event = task_to_gcal_event(task)
    assert event["colorId"] == "5"


def test_task_to_gcal_event_low_priority_maps_to_green():
    task = _make_task("Trim nails", priority=Priority.LOW, scheduled_time=datetime(2026, 4, 16, 9, 0))
    event = task_to_gcal_event(task)
    assert event["colorId"] == "2"


def test_task_to_gcal_event_daily_recurrence_sets_rrule():
    task = _make_task("Daily walk", scheduled_time=datetime(2026, 4, 16, 8, 0), recurrence="daily")
    event = task_to_gcal_event(task)
    assert event.get("recurrence") == ["RRULE:FREQ=DAILY"]


def test_task_to_gcal_event_weekly_recurrence_sets_rrule():
    task = _make_task("Weekly bath", scheduled_time=datetime(2026, 4, 16, 10, 0), recurrence="weekly")
    event = task_to_gcal_event(task)
    assert event.get("recurrence") == ["RRULE:FREQ=WEEKLY"]


def test_task_to_gcal_event_no_recurrence_key_when_none():
    # Non-recurring tasks must not include a recurrence key at all
    task = _make_task("One-off vet", scheduled_time=datetime(2026, 4, 16, 11, 0))
    event = task_to_gcal_event(task)
    assert "recurrence" not in event


def test_task_to_gcal_event_description_from_notes():
    task = _make_task("Medication", scheduled_time=datetime(2026, 4, 16, 8, 0))
    task.notes = "Half tablet with food"
    event = task_to_gcal_event(task)
    assert event.get("description") == "Half tablet with food"


# ── fetch_gcal_events ─────────────────────────────────────────────────────────

def test_fetch_gcal_events_queries_only_today():
    # Verify the API call is scoped to today's date, not a range of dates
    mock_service = MagicMock()
    mock_service.events().list().execute.return_value = {"items": []}

    fetch_gcal_events(mock_service)

    call_kwargs = mock_service.events().list.call_args.kwargs
    today = date.today()
    assert str(today) in call_kwargs["timeMin"]
    assert str(today) in call_kwargs["timeMax"]
    assert call_kwargs["singleEvents"] is True


def test_fetch_gcal_events_returns_items_list():
    fake_event = _make_gcal_event("Playdate", "2026-04-16T14:00:00Z", "2026-04-16T15:00:00Z")
    mock_service = MagicMock()
    mock_service.events().list().execute.return_value = {"items": [fake_event]}

    result = fetch_gcal_events(mock_service)
    assert result == [fake_event]


def test_fetch_gcal_events_returns_empty_list_when_no_events():
    # API returns a dict without "items" when the calendar is empty
    mock_service = MagicMock()
    mock_service.events().list().execute.return_value = {}

    result = fetch_gcal_events(mock_service)
    assert result == []


# ── push_task_to_gcal ─────────────────────────────────────────────────────────

def test_push_task_to_gcal_calls_insert_with_correct_summary():
    task = _make_task("Evening walk", duration=20, scheduled_time=datetime(2026, 4, 16, 18, 0))
    mock_service = MagicMock()
    mock_service.events().insert().execute.return_value = {"id": "abc123"}

    push_task_to_gcal(mock_service, task)

    # Confirm the event body and calendar target are correct
    insert_kwargs = mock_service.events().insert.call_args.kwargs
    assert insert_kwargs["body"]["summary"] == "Evening walk"
    assert insert_kwargs["calendarId"] == "primary"


# ── check_gcal_conflicts ──────────────────────────────────────────────────────

def test_check_gcal_conflicts_detects_overlap_with_gcal_event():
    # PawPal task at 09:30 overlaps with a GCal event running 09:00–10:00
    gcal_event = _make_gcal_event(
        "Doctor appointment",
        "2026-04-16T09:00:00+00:00",
        "2026-04-16T10:00:00+00:00",
    )
    mock_service = MagicMock()
    mock_service.events().list().execute.return_value = {"items": [gcal_event]}

    pawpal_task = _make_task(
        "Vet visit",
        duration=30,
        scheduled_time=datetime(2026, 4, 16, 9, 30),
    )
    scheduled = [_make_scheduled(pawpal_task)]

    warnings = check_gcal_conflicts(mock_service, scheduled)
    assert any("Overlap" in w or "Collision" in w for w in warnings)


def test_check_gcal_conflicts_no_warnings_when_no_overlap():
    # PawPal task at 08:00 and GCal event at 12:00 do not overlap
    gcal_event = _make_gcal_event(
        "Lunch",
        "2026-04-16T12:00:00+00:00",
        "2026-04-16T13:00:00+00:00",
    )
    mock_service = MagicMock()
    mock_service.events().list().execute.return_value = {"items": [gcal_event]}

    pawpal_task = _make_task(
        "Morning walk",
        duration=30,
        scheduled_time=datetime(2026, 4, 16, 8, 0),
    )
    scheduled = [_make_scheduled(pawpal_task)]

    warnings = check_gcal_conflicts(mock_service, scheduled)
    assert warnings == []


def test_check_gcal_conflicts_returns_empty_when_gcal_has_no_events():
    # No GCal events means no additional conflicts beyond PawPal's own checks
    mock_service = MagicMock()
    mock_service.events().list().execute.return_value = {"items": []}

    pawpal_task = _make_task("Feed cat", duration=10, scheduled_time=datetime(2026, 4, 16, 7, 0))
    scheduled = [_make_scheduled(pawpal_task)]

    warnings = check_gcal_conflicts(mock_service, scheduled)
    assert warnings == []
