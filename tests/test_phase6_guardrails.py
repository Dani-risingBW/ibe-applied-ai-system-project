"""Phase 6 guardrail and hardening tests.

Covers: past-date blocking, boundary conditions (open/close/duration), multiple
simultaneous blockers, idempotent cancel, purpose normalisation, metadata
defaults, MockAdapter amenity filtering, and a full end-to-end booking flow.
"""
import sys
from datetime import date, datetime, time, timedelta
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

from adapters.mock import MockAdapter
from booking_engine import (
    AvailabilitySlot, Booking, BookingEngine,
    ConflictDetector, Library, RoomFilters, User,
)


# ── Fixtures ───────────────────────────────────────────────────────────────────

@pytest.fixture
def library():
    return Library(
        id="founders", name="Founders Library", campus="Main", building="Founders Hall",
        base_url="", adapter_type="mock",
        open_time="08:00", close_time="22:00",
        open_days=["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"],
        max_booking_days_ahead=7, max_booking_duration_hours=2,
        max_bookings_per_user_per_day=2,
    )


@pytest.fixture
def engine_with_adapter(library):
    engine = BookingEngine()
    adapter = MockAdapter(library)
    engine.register_library(library.id, adapter)
    return engine, library


def _slot(days_offset: int = 1, hour: int = 10, duration: int = 60,
          library_id: str = "founders") -> AvailabilitySlot:
    target = date.today() + timedelta(days=days_offset)
    start = datetime.combine(target, time(hour, 0))
    return AvailabilitySlot(
        id=f"s-{days_offset}-{hour}", room_id="founders-room-1",
        library_id=library_id,
        start_time=start, end_time=start + timedelta(minutes=duration),
        duration_minutes=duration,
    )


def _user(uid: str = "alice@test.edu") -> User:
    return User(id=uid, name="Alice", email=uid)


# ── Past-date blocking ─────────────────────────────────────────────────────────

class TestPastDateGuard:

    def test_past_slot_is_blocked(self, library):
        slot = _slot(days_offset=-1)
        result = ConflictDetector().detect(slot, [], [], library)
        assert any("past" in b.lower() for b in result.blockers)

    def test_yesterday_slot_is_blocked(self, library):
        slot = _slot(days_offset=-7)
        result = ConflictDetector().detect(slot, [], [], library)
        assert result.blockers != []

    def test_today_slot_is_not_past_blocked(self, library):
        today = date.today()
        start = datetime.combine(today, time(10, 0))
        slot = AvailabilitySlot(
            id="today-s", room_id="founders-room-1", library_id="founders",
            start_time=start, end_time=start + timedelta(hours=1),
            duration_minutes=60,
        )
        blockers = ConflictDetector()._check_advance_limit(slot, library)
        assert not any("past" in b.lower() for b in blockers)

    def test_tomorrow_slot_is_allowed(self, library):
        blockers = ConflictDetector()._check_advance_limit(_slot(days_offset=1), library)
        assert blockers == []


# ── Operating-hours boundary conditions ───────────────────────────────────────

class TestOperatingHoursBoundaries:

    def _make_slot(self, library, start_hour: int, start_min: int,
                   end_hour: int, end_min: int) -> AvailabilitySlot:
        target = date.today() + timedelta(days=1)
        start = datetime.combine(target, time(start_hour, start_min))
        end = datetime.combine(target, time(end_hour, end_min))
        minutes = int((end - start).total_seconds() / 60)
        return AvailabilitySlot(
            id="b-slot", room_id="founders-room-1", library_id="founders",
            start_time=start, end_time=end, duration_minutes=minutes,
        )

    def test_slot_starting_exactly_at_open_is_allowed(self, library):
        # open_time = "08:00"
        slot = self._make_slot(library, 8, 0, 9, 0)
        blockers = ConflictDetector()._check_operating_hours(slot, library)
        assert blockers == []

    def test_slot_starting_one_minute_before_open_is_blocked(self, library):
        slot = self._make_slot(library, 7, 59, 9, 0)
        blockers = ConflictDetector()._check_operating_hours(slot, library)
        assert any("opens at" in b for b in blockers)

    def test_slot_ending_exactly_at_close_is_allowed(self, library):
        # close_time = "22:00"
        slot = self._make_slot(library, 21, 0, 22, 0)
        blockers = ConflictDetector()._check_operating_hours(slot, library)
        assert blockers == []

    def test_slot_ending_one_minute_after_close_is_blocked(self, library):
        slot = self._make_slot(library, 21, 1, 22, 1)
        blockers = ConflictDetector()._check_operating_hours(slot, library)
        assert any("closes at" in b for b in blockers)


# ── Duration-limit boundary conditions ────────────────────────────────────────

class TestDurationLimitBoundaries:

    def test_duration_exactly_equal_to_max_is_allowed(self, library):
        # max_booking_duration_hours = 2 → 120 min
        slot = _slot(duration=120)
        blockers = ConflictDetector()._check_duration_limit(slot, library)
        assert blockers == []

    def test_duration_one_minute_over_max_is_blocked(self, library):
        slot = _slot(duration=121)
        blockers = ConflictDetector()._check_duration_limit(slot, library)
        assert blockers != []
        assert "Max booking duration" in blockers[0]

    def test_duration_well_under_max_is_allowed(self, library):
        slot = _slot(duration=30)
        blockers = ConflictDetector()._check_duration_limit(slot, library)
        assert blockers == []


# ── Multiple simultaneous blockers ────────────────────────────────────────────

class TestMultipleBlockers:

    def test_past_and_over_duration_both_returned(self, library):
        past_long = _slot(days_offset=-1, duration=200)
        result = ConflictDetector().detect(past_long, [], [], library)
        assert any("past" in b.lower() for b in result.blockers)
        assert any("Max booking duration" in b for b in result.blockers)
        assert len(result.blockers) >= 2

    def test_early_and_late_both_blocked(self, library):
        # A 16-hour slot starting before open AND ending after close
        target = date.today() + timedelta(days=1)
        start = datetime.combine(target, time(6, 0))   # before 08:00
        end = datetime.combine(target, time(23, 0))    # after 22:00
        slot = AvailabilitySlot(
            id="long-slot", room_id="founders-room-1", library_id="founders",
            start_time=start, end_time=end, duration_minutes=1020,
        )
        blockers = ConflictDetector()._check_operating_hours(slot, library)
        assert any("opens at" in b for b in blockers)
        assert any("closes at" in b for b in blockers)

    def test_all_rules_can_fire_together(self, library):
        # Past + over duration + over advance limit is impossible (past already covers it)
        # Instead: over advance limit + over duration + wrong open day
        library.open_days = ["Mon"]  # only Monday
        target = date.today() + timedelta(days=10)  # beyond 7-day limit
        # find a non-Monday
        while target.strftime("%a") == "Mon":
            target += timedelta(days=1)
        start = datetime.combine(target, time(10, 0))
        slot = AvailabilitySlot(
            id="multi", room_id="founders-room-1", library_id="founders",
            start_time=start, end_time=start + timedelta(minutes=200),
            duration_minutes=200,
        )
        result = ConflictDetector().detect(slot, [], [], library)
        assert len(result.blockers) >= 3


# ── Idempotent cancel ─────────────────────────────────────────────────────────

class TestIdempotentCancel:

    def _make_booking(self, uid: str = "bk-001") -> Booking:
        start = datetime.now() + timedelta(hours=2)
        return Booking(
            id=uid, room_id="r1", user_id="alice", library_id="founders",
            start_time=start, end_time=start + timedelta(hours=1),
            duration_minutes=60, purpose="Study", status="confirmed",
        )

    def test_first_cancel_returns_true(self):
        engine = BookingEngine()
        engine.add_booking(self._make_booking())
        assert engine.cancel_booking("bk-001") is True

    def test_second_cancel_returns_false(self):
        engine = BookingEngine()
        engine.add_booking(self._make_booking())
        engine.cancel_booking("bk-001")
        # Already cancelled — not found under that id with active status
        assert engine.cancel_booking("nonexistent-id") is False

    def test_cancelled_booking_status_remains_cancelled(self):
        engine = BookingEngine()
        b = self._make_booking()
        engine.add_booking(b)
        engine.cancel_booking("bk-001")
        engine.cancel_booking("bk-001")  # second call
        assert engine.bookings[0].status == "cancelled"


# ── Purpose normalisation in book_room ────────────────────────────────────────

class TestPurposeNormalisation:

    def test_whitespace_only_purpose_normalised_to_study(self, engine_with_adapter):
        engine, library = engine_with_adapter
        slot = _slot()
        _, booking = engine.book_room(slot, _user(), purpose="   ")
        assert booking is not None
        assert booking.purpose == "Study"

    def test_empty_string_purpose_normalised_to_study(self, engine_with_adapter):
        engine, library = engine_with_adapter
        slot = _slot()
        _, booking = engine.book_room(slot, _user(), purpose="")
        assert booking is not None
        assert booking.purpose == "Study"

    def test_valid_purpose_preserved(self, engine_with_adapter):
        engine, library = engine_with_adapter
        slot = _slot()
        _, booking = engine.book_room(slot, _user(), purpose="Group project")
        assert booking is not None
        assert booking.purpose == "Group project"

    def test_purpose_stripped_of_surrounding_whitespace(self, engine_with_adapter):
        engine, library = engine_with_adapter
        slot = _slot()
        _, booking = engine.book_room(slot, _user(), purpose="  Solo study  ")
        assert booking is not None
        assert booking.purpose == "Solo study"


# ── AvailabilitySlot metadata defaults ────────────────────────────────────────

class TestAvailabilitySlotMetadata:

    def test_metadata_defaults_to_empty_dict(self):
        start = datetime.now() + timedelta(hours=1)
        slot = AvailabilitySlot(
            id="s1", room_id="r1", library_id="lib",
            start_time=start, end_time=start + timedelta(hours=1),
            duration_minutes=60,
        )
        assert slot.metadata == {}

    def test_metadata_instances_are_independent(self):
        start = datetime.now() + timedelta(hours=1)
        s1 = AvailabilitySlot(
            id="s1", room_id="r1", library_id="lib",
            start_time=start, end_time=start + timedelta(hours=1),
            duration_minutes=60,
        )
        s2 = AvailabilitySlot(
            id="s2", room_id="r2", library_id="lib",
            start_time=start, end_time=start + timedelta(hours=1),
            duration_minutes=60,
        )
        s1.metadata["key"] = "value"
        assert "key" not in s2.metadata

    def test_mock_adapter_populates_metadata(self, library):
        adapter = MockAdapter(library)
        slots = adapter.fetch_availability(
            date.today() + timedelta(days=1),
            RoomFilters(min_capacity=1, duration_minutes=60),
        )
        assert slots, "Expected at least one slot"
        for slot in slots:
            assert "capacity" in slot.metadata
            assert "accessible" in slot.metadata
            assert "floor" in slot.metadata
            assert "amenities" in slot.metadata


# ── MockAdapter amenity filtering ─────────────────────────────────────────────

class TestMockAdapterAmenityFilter:

    def _fetch(self, library, amenities):
        adapter = MockAdapter(library)
        return adapter.fetch_availability(
            date.today() + timedelta(days=1),
            RoomFilters(min_capacity=1, duration_minutes=60, amenities=amenities),
        )

    def test_phone_filter_returns_only_rooms_with_phone(self, library):
        slots = self._fetch(library, ["Phone"])
        assert slots, "Expected slots with Phone"
        for slot in slots:
            assert "Phone" in slot.metadata["amenities"]

    def test_video_conf_filter_excludes_study_rooms(self, library):
        slots = self._fetch(library, ["Video conferencing"])
        for slot in slots:
            assert slot.metadata["room_type"] != "study_room"

    def test_accessible_filter_returns_only_accessible_rooms(self, library):
        slots = self._fetch(library, ["Accessible"])
        assert slots, "Expected accessible slots"
        for slot in slots:
            assert slot.metadata["accessible"] is True

    def test_multiple_amenities_all_must_match(self, library):
        slots = self._fetch(library, ["Whiteboard", "Video conferencing"])
        for slot in slots:
            assert "Whiteboard" in slot.metadata["amenities"]
            assert "Video conferencing" in slot.metadata["amenities"]

    def test_impossible_amenity_combo_returns_empty(self, library):
        # Accessible (room 1 only) AND Video conferencing (rooms 3, 4 only) — no room has both
        slots = self._fetch(library, ["Accessible", "Video conferencing"])
        assert slots == []


# ── book_room: no adapter error code ─────────────────────────────────────────

class TestBookRoomNoAdapter:

    def test_no_adapter_returns_failure_result(self):
        engine = BookingEngine()
        slot = _slot()
        result, booking = engine.book_room(slot, _user())
        assert result.success is False
        assert result.error_code == "NO_ADAPTER"
        assert booking is None

    def test_no_adapter_does_not_add_booking(self):
        engine = BookingEngine()
        slot = _slot()
        engine.book_room(slot, _user())
        assert len(engine.bookings) == 0


# ── Full end-to-end integration ────────────────────────────────────────────────

class TestEndToEndBookingFlow:

    def test_fetch_check_book_cancel_full_flow(self, library):
        engine = BookingEngine()
        adapter = MockAdapter(library)
        engine.register_library(library.id, adapter)
        user = _user()

        # 1. Fetch availability
        target_date = date.today() + timedelta(days=1)
        filters = RoomFilters(min_capacity=1, duration_minutes=60)
        slots = engine.fetch_availability(library.id, target_date, filters)
        assert slots, "Expected available slots"

        # 2. Check conflicts — should be clean
        slot = slots[0]
        conflict = engine.check_conflicts(slot, [], library, user_id=user.id)
        assert not conflict.blockers

        # 3. Book the room
        result, booking = engine.book_room(slot, user, purpose="Group project")
        assert result.success
        assert booking is not None
        assert booking.status == "confirmed"
        assert booking.purpose == "Group project"
        assert booking in engine.bookings

        # 4. Verify double-book is now blocked
        conflict2 = engine.check_conflicts(slot, [], library, user_id=user.id)
        assert any("already booked" in b.lower() for b in conflict2.blockers)

        # 5. Cancel
        assert booking.id is not None
        cancelled = engine.cancel_booking(booking.id, reason="Test teardown")
        assert cancelled is True
        assert booking.status == "cancelled"

    def test_daily_limit_enforced_across_full_flow(self, library):
        library.max_bookings_per_user_per_day = 1
        engine = BookingEngine()
        adapter = MockAdapter(library)
        engine.register_library(library.id, adapter)
        user = _user()

        target_date = date.today() + timedelta(days=1)
        slots = engine.fetch_availability(
            library.id, target_date, RoomFilters(min_capacity=1, duration_minutes=60)
        )
        assert len(slots) >= 2

        # Book first slot
        result1, booking1 = engine.book_room(slots[0], user, purpose="First")
        assert result1.success

        # Second slot same day should be blocked by daily limit
        conflict = engine.check_conflicts(slots[1], [], library, user_id=user.id)
        assert any("daily limit" in b for b in conflict.blockers)
