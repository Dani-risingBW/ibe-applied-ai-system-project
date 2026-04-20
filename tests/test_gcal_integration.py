"""Tests for google_calendar_integration.py — all Google API calls are mocked."""
import sys
from datetime import date, datetime, timedelta
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

from booking_engine import Booking, Library
from google_calendar_integration import (
    booking_to_gcal_event,
    cancel_gcal_event,
    create_gcal_event,
    fetch_gcal_events,
    gcal_event_to_booking_dict,
    parse_gcal_event,
    sync_booking_to_gcal,
)

_BOOKED_BY_TAG = "library-room-booking"


# ── Fixtures ───────────────────────────────────────────────────────────────────

@pytest.fixture
def library():
    return Library(
        id="founders", name="Founders Library", campus="Main",
        building="Founders Hall", base_url="", adapter_type="mock",
        open_time="08:00", close_time="22:00",
    )


@pytest.fixture
def booking():
    start = datetime(2026, 4, 20, 10, 0)
    return Booking(
        id="bk-001", room_id="founders-r1", user_id="alice@test.edu",
        library_id="founders",
        start_time=start, end_time=start + timedelta(hours=1),
        duration_minutes=60, purpose="Group project",
        status="confirmed", confirmation_code="CONF-ABC",
        notes="Bring whiteboard markers",
    )


# ── fetch_gcal_events ─────────────────────────────────────────────────────────

class TestFetchGcalEvents:

    def _mock_service(self, items):
        svc = MagicMock()
        svc.events().list().execute.return_value = {"items": items}
        return svc

    def test_returns_items_list(self):
        ev = {"summary": "Lecture", "start": {"dateTime": "2026-04-17T10:00:00Z"},
              "end": {"dateTime": "2026-04-17T11:00:00Z"}}
        result = fetch_gcal_events(self._mock_service([ev]))
        assert result == [ev]

    def test_returns_empty_list_when_no_events(self):
        assert fetch_gcal_events(self._mock_service([])) == []

    def test_returns_empty_list_when_items_key_missing(self):
        svc = MagicMock()
        svc.events().list().execute.return_value = {}
        assert fetch_gcal_events(svc) == []

    def test_queries_target_date(self):
        svc = self._mock_service([])
        fetch_gcal_events(svc, target_date=date(2026, 5, 10))
        kwargs = svc.events().list.call_args.kwargs
        assert "2026-05-10" in kwargs["timeMin"]
        assert "2026-05-10" in kwargs["timeMax"]

    def test_defaults_to_today(self):
        svc = self._mock_service([])
        fetch_gcal_events(svc)
        kwargs = svc.events().list.call_args.kwargs
        assert str(date.today()) in kwargs["timeMin"]

    def test_uses_single_events_expansion(self):
        svc = self._mock_service([])
        fetch_gcal_events(svc)
        kwargs = svc.events().list.call_args.kwargs
        assert kwargs["singleEvents"] is True


# ── parse_gcal_event ──────────────────────────────────────────────────────────

class TestParseGcalEvent:

    def test_parses_timed_event(self):
        ev = {"id": "abc", "summary": "Study session",
              "start": {"dateTime": "2026-04-17T10:00:00"},
              "end": {"dateTime": "2026-04-17T11:30:00"}}
        result = parse_gcal_event(ev)
        assert result is not None
        assert result["summary"] == "Study session"
        assert result["start"] == datetime(2026, 4, 17, 10, 0)
        assert result["end"] == datetime(2026, 4, 17, 11, 30)

    def test_parses_event_with_tz_offset(self):
        ev = {"summary": "Meeting",
              "start": {"dateTime": "2026-04-17T09:00:00-05:00"},
              "end": {"dateTime": "2026-04-17T10:00:00-05:00"}}
        result = parse_gcal_event(ev)
        assert result is not None
        assert result["start"] == datetime(2026, 4, 17, 9, 0)

    def test_parses_all_day_event(self):
        ev = {"summary": "Holiday",
              "start": {"date": "2026-04-17"},
              "end": {"date": "2026-04-18"}}
        result = parse_gcal_event(ev)
        assert result is not None
        assert result["start"].date() == date(2026, 4, 17)

    def test_returns_none_for_missing_start(self):
        assert parse_gcal_event({"summary": "No time"}) is None

    def test_preserves_id_and_description(self):
        ev = {"id": "xyz", "summary": "Collab", "description": "Bring laptop",
              "start": {"dateTime": "2026-04-17T14:00:00"},
              "end": {"dateTime": "2026-04-17T15:00:00"}}
        result = parse_gcal_event(ev)
        assert result["id"] == "xyz"
        assert result["description"] == "Bring laptop"

    def test_default_title_when_no_summary(self):
        ev = {"start": {"dateTime": "2026-04-17T14:00:00"},
              "end": {"dateTime": "2026-04-17T15:00:00"}}
        result = parse_gcal_event(ev)
        assert result["summary"] == "Untitled"


# ── booking_to_gcal_event ─────────────────────────────────────────────────────

class TestBookingToGcalEvent:

    def test_returns_dict_with_required_keys(self, booking, library):
        ev = booking_to_gcal_event(booking, library)
        assert "summary" in ev
        assert "start" in ev
        assert "end" in ev
        assert "description" in ev
        assert "location" in ev

    def test_summary_contains_library_name(self, booking, library):
        ev = booking_to_gcal_event(booking, library)
        assert library.name in ev["summary"]

    def test_description_contains_confirmation_code(self, booking, library):
        ev = booking_to_gcal_event(booking, library)
        assert booking.confirmation_code in ev["description"]

    def test_description_contains_purpose(self, booking, library):
        ev = booking_to_gcal_event(booking, library)
        assert booking.purpose in ev["description"]

    def test_description_contains_notes_when_present(self, booking, library):
        ev = booking_to_gcal_event(booking, library)
        assert booking.notes in ev["description"]

    def test_description_omits_notes_line_when_none(self, booking, library):
        booking.notes = None
        ev = booking_to_gcal_event(booking, library)
        assert "Notes:" not in ev["description"]

    def test_start_datetime_is_rfc3339(self, booking, library):
        ev = booking_to_gcal_event(booking, library)
        start_str = ev["start"]["dateTime"]
        assert "T" in start_str
        assert ":" in start_str[-6:]  # tz offset present

    def test_extended_properties_contain_booking_id(self, booking, library):
        ev = booking_to_gcal_event(booking, library)
        props = ev["extendedProperties"]["private"]
        assert props["booking_id"] == booking.id

    def test_extended_properties_contain_booked_by_tag(self, booking, library):
        ev = booking_to_gcal_event(booking, library)
        props = ev["extendedProperties"]["private"]
        assert props["booked_by"] == _BOOKED_BY_TAG

    def test_custom_room_name_in_summary(self, booking, library):
        ev = booking_to_gcal_event(booking, library, room_name="Study Room 3B")
        assert "Study Room 3B" in ev["summary"]

    def test_location_contains_building_and_campus(self, booking, library):
        ev = booking_to_gcal_event(booking, library)
        assert library.building in ev["location"]
        assert library.campus in ev["location"]


# ── gcal_event_to_booking_dict ────────────────────────────────────────────────

class TestGcalEventToBookingDict:

    def _make_system_event(self, booking, library):
        ev_dict = booking_to_gcal_event(booking, library)
        ev_dict["id"] = "gcal-event-001"
        ev_dict["start"]["dateTime"] = booking.start_time.isoformat()
        ev_dict["end"]["dateTime"] = booking.end_time.isoformat()
        return ev_dict

    def test_round_trips_booking_id(self, booking, library):
        ev = self._make_system_event(booking, library)
        result = gcal_event_to_booking_dict(ev)
        assert result is not None
        assert result["booking_id"] == booking.id

    def test_round_trips_confirmation_code(self, booking, library):
        ev = self._make_system_event(booking, library)
        result = gcal_event_to_booking_dict(ev)
        assert result["confirmation_code"] == booking.confirmation_code

    def test_round_trips_library_and_room_ids(self, booking, library):
        ev = self._make_system_event(booking, library)
        result = gcal_event_to_booking_dict(ev)
        assert result["library_id"] == booking.library_id
        assert result["room_id"] == booking.room_id

    def test_returns_none_for_non_system_event(self):
        ev = {"id": "ext-001", "summary": "External meeting",
              "start": {"dateTime": "2026-04-20T10:00:00"},
              "end": {"dateTime": "2026-04-20T11:00:00"}}
        assert gcal_event_to_booking_dict(ev) is None

    def test_returns_none_for_event_without_start(self, booking, library):
        ev = self._make_system_event(booking, library)
        del ev["start"]
        assert gcal_event_to_booking_dict(ev) is None


# ── create_gcal_event ─────────────────────────────────────────────────────────

class TestCreateGcalEvent:

    def test_calls_insert_and_returns_result(self):
        svc = MagicMock()
        created = {"id": "new-event-id", "htmlLink": "https://calendar.google.com/e/123"}
        svc.events().insert().execute.return_value = created
        result = create_gcal_event(svc, {"summary": "Test"})
        assert result == created

    def test_inserts_into_primary_calendar(self):
        svc = MagicMock()
        svc.events().insert().execute.return_value = {}
        create_gcal_event(svc, {"summary": "Test"})
        kwargs = svc.events().insert.call_args.kwargs
        assert kwargs["calendarId"] == "primary"

    def test_passes_event_body(self):
        svc = MagicMock()
        svc.events().insert().execute.return_value = {}
        body = {"summary": "Room booking", "start": {"dateTime": "2026-04-20T10:00:00"}}
        create_gcal_event(svc, body)
        kwargs = svc.events().insert.call_args.kwargs
        assert kwargs["body"] == body


# ── cancel_gcal_event ─────────────────────────────────────────────────────────

class TestCancelGcalEvent:

    def test_returns_true_on_success(self):
        svc = MagicMock()
        svc.events().delete().execute.return_value = None
        assert cancel_gcal_event(svc, "event-id-123") is True

    def test_returns_false_on_exception(self):
        svc = MagicMock()
        svc.events().delete().execute.side_effect = Exception("API error")
        assert cancel_gcal_event(svc, "event-id-123") is False

    def test_calls_delete_with_correct_event_id(self):
        svc = MagicMock()
        svc.events().delete().execute.return_value = None
        cancel_gcal_event(svc, "target-event-id")
        kwargs = svc.events().delete.call_args.kwargs
        assert kwargs["eventId"] == "target-event-id"
        assert kwargs["calendarId"] == "primary"


# ── sync_booking_to_gcal ──────────────────────────────────────────────────────

class TestSyncBookingToGcal:

    def _mock_service_with_link(self, link: str, event_id: str = "gcal-123"):
        svc = MagicMock()
        svc.events().insert().execute.return_value = {
            "id": event_id, "htmlLink": link
        }
        return svc

    def test_returns_html_link_on_success(self, booking, library):
        svc = self._mock_service_with_link("https://calendar.google.com/e/abc")
        link = sync_booking_to_gcal(svc, booking, library)
        assert link == "https://calendar.google.com/e/abc"

    def test_sets_gcal_event_id_on_booking(self, booking, library):
        svc = self._mock_service_with_link("https://calendar.google.com/e/abc", "gcal-xyz")
        sync_booking_to_gcal(svc, booking, library)
        assert booking.gcal_event_id == "gcal-xyz"

    def test_returns_none_on_api_failure(self, booking, library):
        svc = MagicMock()
        svc.events().insert().execute.side_effect = Exception("Network error")
        result = sync_booking_to_gcal(svc, booking, library)
        assert result is None

    def test_gcal_event_id_unchanged_on_failure(self, booking, library):
        booking.gcal_event_id = None
        svc = MagicMock()
        svc.events().insert().execute.side_effect = Exception("fail")
        sync_booking_to_gcal(svc, booking, library)
        assert booking.gcal_event_id is None

    def test_passes_room_name_to_event(self, booking, library):
        svc = self._mock_service_with_link("https://cal.google.com/e/1")
        sync_booking_to_gcal(svc, booking, library, room_name="3B East Wing")
        body = svc.events().insert.call_args.kwargs["body"]
        assert "3B East Wing" in body["summary"]
