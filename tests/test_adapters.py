import json
import sys
import tempfile
from datetime import date, datetime, time, timedelta
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

from adapters import load_libraries
from adapters.mock import MockAdapter
from adapters.scraper import ScraperAdapter
from booking_engine import BookingEngine, Library, RoomFilters, User


# ── Fixtures ───────────────────────────────────────────────────────────────────

@pytest.fixture
def library():
    return Library(
        id="founders", name="Founders Library", campus="Main", building="Founders Hall",
        base_url="", adapter_type="mock",
        open_time="08:00", close_time="22:00",
        max_booking_days_ahead=7, max_booking_duration_hours=2,
        max_bookings_per_user_per_day=2,
    )


@pytest.fixture
def user():
    return User(id="alice@example.com", name="Alice Smith", email="alice@example.com")


@pytest.fixture
def filters():
    return RoomFilters(min_capacity=1, duration_minutes=60)


@pytest.fixture
def mock_adapter(library):
    return MockAdapter(library, {"always_confirm": True})


@pytest.fixture
def today():
    return date.today()


# ── MockAdapter.fetch_availability ────────────────────────────────────────────

class TestMockAdapterAvailability:

    def test_returns_slots_for_today(self, mock_adapter, today, filters):
        slots = mock_adapter.fetch_availability(today, filters)
        assert len(slots) > 0

    def test_all_slots_on_requested_date(self, mock_adapter, today, filters):
        slots = mock_adapter.fetch_availability(today, filters)
        assert all(s.start_time.date() == today for s in slots)

    def test_all_slots_within_operating_hours(self, mock_adapter, today, filters, library):
        open_dt = datetime.combine(today, time(8, 0))
        close_dt = datetime.combine(today, time(22, 0))
        slots = mock_adapter.fetch_availability(today, filters)
        assert all(s.start_time >= open_dt for s in slots)
        assert all(s.end_time <= close_dt for s in slots)

    def test_slot_duration_matches_filter(self, mock_adapter, today):
        f = RoomFilters(min_capacity=1, duration_minutes=90)
        slots = mock_adapter.fetch_availability(today, f)
        assert all(s.duration_minutes == 90 for s in slots)

    def test_capacity_filter_min(self, mock_adapter, today):
        # Only rooms with capacity >= 6 (rooms 3 and 4)
        f = RoomFilters(min_capacity=6, duration_minutes=60)
        slots = mock_adapter.fetch_availability(today, f)
        assert len(slots) > 0
        room_ids = {s.room_id for s in slots}
        # Room 1 (cap 2) and Room 2 (cap 4) should be excluded
        assert all("room-3" in r or "room-4" in r for r in room_ids)

    def test_capacity_filter_excludes_all_small_rooms(self, mock_adapter, today):
        f = RoomFilters(min_capacity=10, duration_minutes=60)
        slots = mock_adapter.fetch_availability(today, f)
        assert slots == []

    def test_accessible_only_filter(self, mock_adapter, today):
        f = RoomFilters(min_capacity=1, duration_minutes=60, accessible_only=True)
        slots = mock_adapter.fetch_availability(today, f)
        # Only room-1 is accessible in MockAdapter
        assert all("room-1" in s.room_id for s in slots)

    def test_simulated_error_raises(self, library, today, filters):
        adapter = MockAdapter(library, {"simulated_error": "Service unavailable"})
        with pytest.raises(RuntimeError, match="Service unavailable"):
            adapter.fetch_availability(today, filters)

    def test_slots_have_library_id(self, mock_adapter, today, filters, library):
        slots = mock_adapter.fetch_availability(today, filters)
        assert all(s.library_id == library.id for s in slots)

    def test_slots_have_fetched_at(self, mock_adapter, today, filters):
        slots = mock_adapter.fetch_availability(today, filters)
        assert all(s.fetched_at is not None for s in slots)


# ── MockAdapter.book_room ──────────────────────────────────────────────────────

class TestMockAdapterBooking:

    def test_successful_booking_returns_confirmation(self, mock_adapter, today, filters, user):
        slots = mock_adapter.fetch_availability(today, filters)
        result = mock_adapter.book_room(slots[0], user)
        assert result.success is True
        assert result.confirmation_code is not None
        assert result.confirmation_code.startswith("MOCK-")

    def test_reject_mode_returns_failure(self, library, today, filters, user):
        adapter = MockAdapter(library, {"always_confirm": False})
        slots = adapter.fetch_availability(today, filters)
        result = adapter.book_room(slots[0], user)
        assert result.success is False
        assert result.error_code == "MOCK_REJECT"

    def test_simulated_error_returns_failure(self, library, today, filters, user):
        adapter = MockAdapter(library, {"simulated_error": "Quota exceeded"})
        slot = __import__("booking_engine").AvailabilitySlot(
            id="s1", room_id="r1", library_id="founders",
            start_time=datetime.combine(today, time(10, 0)),
            end_time=datetime.combine(today, time(11, 0)),
            duration_minutes=60,
        )
        result = adapter.book_room(slot, user)
        assert result.success is False
        assert result.error_code == "MOCK_ERROR"

    def test_cancel_booking_returns_true(self, mock_adapter):
        assert mock_adapter.cancel_booking("MOCK-ABC123") is True

    def test_cancel_with_error_returns_false(self, library):
        adapter = MockAdapter(library, {"simulated_error": "down"})
        assert adapter.cancel_booking("MOCK-ABC123") is False


# ── BookingEngine + adapter integration ───────────────────────────────────────

class TestBookingEngineWithAdapter:

    def test_fetch_availability_via_engine(self, library, today, filters):
        engine = BookingEngine()
        adapter = MockAdapter(library, {"always_confirm": True})
        engine.register_library(library.id, adapter)
        slots = engine.fetch_availability(library.id, today, filters)
        assert len(slots) > 0

    def test_fetch_unknown_library_raises(self, today, filters):
        engine = BookingEngine()
        with pytest.raises(ValueError, match="No adapter registered"):
            engine.fetch_availability("nonexistent", today, filters)

    def test_book_room_via_engine_adds_booking(self, library, today, filters, user):
        engine = BookingEngine()
        engine.register_library(library.id, MockAdapter(library, {"always_confirm": True}))
        slots = engine.fetch_availability(library.id, today, filters)
        result, booking = engine.book_room(slots[0], user, purpose="Study")
        assert result.success is True
        assert booking is not None
        assert booking.status == "confirmed"
        assert len(engine.bookings) == 1

    def test_book_room_dry_run_does_not_add_booking(self, library, today, filters, user):
        engine = BookingEngine()
        engine.register_library(library.id, MockAdapter(library, {"always_confirm": True}))
        slots = engine.fetch_availability(library.id, today, filters)
        result, booking = engine.book_room(slots[0], user, dry_run=True)
        assert result.success is True
        assert booking is None
        assert len(engine.bookings) == 0

    def test_book_room_failure_does_not_add_booking(self, library, today, filters, user):
        engine = BookingEngine()
        engine.register_library(library.id, MockAdapter(library, {"always_confirm": False}))
        slots = engine.fetch_availability(library.id, today, filters)
        result, booking = engine.book_room(slots[0], user)
        assert result.success is False
        assert booking is None
        assert len(engine.bookings) == 0

    def test_get_library_returns_metadata(self, library):
        engine = BookingEngine()
        engine.register_library(library.id, MockAdapter(library))
        assert engine.get_library(library.id) is library

    def test_get_library_unknown_returns_none(self):
        engine = BookingEngine()
        assert engine.get_library("nope") is None


# ── load_libraries ─────────────────────────────────────────────────────────────

class TestLoadLibraries:

    def _write_config(self, configs: list) -> str:
        tmp = tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False)
        json.dump(configs, tmp)
        tmp.close()
        return tmp.name

    def test_loads_mock_libraries(self):
        cfg = [
            {"id": "lib1", "name": "Library One", "campus": "Main", "building": "A",
             "adapter": "mock", "base_url": "", "open_time": "08:00", "close_time": "22:00"},
        ]
        path = self._write_config(cfg)
        engine = BookingEngine()
        libs = load_libraries(engine, path)
        assert "lib1" in libs
        assert libs["lib1"].name == "Library One"
        assert "lib1" in engine.libraries

    def test_loads_multiple_libraries(self):
        cfg = [
            {"id": "a", "name": "A", "campus": "", "building": "",
             "adapter": "mock", "base_url": "", "open_time": "08:00", "close_time": "22:00"},
            {"id": "b", "name": "B", "campus": "", "building": "",
             "adapter": "mock", "base_url": "", "open_time": "09:00", "close_time": "21:00"},
        ]
        path = self._write_config(cfg)
        engine = BookingEngine()
        libs = load_libraries(engine, path)
        assert set(libs.keys()) == {"a", "b"}

    def test_unknown_adapter_raises(self):
        cfg = [
            {"id": "x", "name": "X", "campus": "", "building": "",
             "adapter": "foobar", "base_url": "", "open_time": "08:00", "close_time": "22:00"},
        ]
        path = self._write_config(cfg)
        engine = BookingEngine()
        with pytest.raises(ValueError, match="Unknown adapter"):
            load_libraries(engine, path)

    def test_missing_file_raises(self):
        engine = BookingEngine()
        with pytest.raises(FileNotFoundError):
            load_libraries(engine, "does_not_exist.json")


# ── ScraperAdapter helpers ─────────────────────────────────────────────────────

class TestScraperAdapterParsing:

    @pytest.fixture
    def scraper(self, library):
        return ScraperAdapter(library, {
            "selectors": {
                "time_slot": ".slot",
                "room_name": ".room",
                "slot_time": ".time",
                "capacity": ".cap",
            }
        })

    def test_parse_time_range_standard(self, scraper, today):
        start, end = scraper._parse_time_range("10:00 - 11:00", today)
        assert start == datetime.combine(today, time(10, 0))
        assert end == datetime.combine(today, time(11, 0))

    def test_parse_time_range_em_dash(self, scraper, today):
        start, end = scraper._parse_time_range("14:30–15:30", today)
        assert start.hour == 14
        assert end.hour == 15

    def test_parse_time_range_invalid_returns_none(self, scraper, today):
        start, end = scraper._parse_time_range("No time here", today)
        assert start is None
        assert end is None

    def test_parse_html_extracts_slots(self, scraper, today):
        html = """
        <div class="slot">
            <span class="room">Room A</span>
            <span class="time">10:00 - 11:00</span>
            <span class="cap">4</span>
        </div>
        <div class="slot">
            <span class="room">Room B</span>
            <span class="time">13:00 - 14:00</span>
            <span class="cap">6</span>
        </div>
        """
        f = RoomFilters(min_capacity=1, duration_minutes=60)
        slots = scraper._parse_html(html, today, f)
        assert len(slots) == 2
        assert slots[0].start_time.hour == 10
        assert slots[1].start_time.hour == 13

    def test_parse_html_capacity_filter(self, scraper, today):
        html = """
        <div class="slot">
            <span class="room">Small Room</span>
            <span class="time">10:00 - 11:00</span>
            <span class="cap">2</span>
        </div>
        <div class="slot">
            <span class="room">Big Room</span>
            <span class="time">11:00 - 12:00</span>
            <span class="cap">8</span>
        </div>
        """
        f = RoomFilters(min_capacity=5, duration_minutes=60)
        slots = scraper._parse_html(html, today, f)
        assert len(slots) == 1
        assert "big-room" in slots[0].room_id

    def test_parse_html_skips_missing_time(self, scraper, today):
        html = """
        <div class="slot">
            <span class="room">Room X</span>
            <span class="cap">4</span>
        </div>
        """
        f = RoomFilters(min_capacity=1, duration_minutes=60)
        slots = scraper._parse_html(html, today, f)
        assert slots == []


# ── BaseLibraryAdapter retry ───────────────────────────────────────────────────

class TestBaseAdapterRetry:

    def test_retry_succeeds_on_second_attempt(self, library):
        adapter = MockAdapter(library, {"max_retries": 3})
        call_count = {"n": 0}

        def flaky():
            call_count["n"] += 1
            if call_count["n"] < 2:
                raise ConnectionError("transient")
            return "ok"

        result = adapter._retry(flaky)
        assert result == "ok"
        assert call_count["n"] == 2

    def test_retry_raises_after_max_attempts(self, library):
        adapter = MockAdapter(library, {"max_retries": 2})

        def always_fail():
            raise ConnectionError("permanent")

        with pytest.raises(ConnectionError):
            adapter._retry(always_fail)
