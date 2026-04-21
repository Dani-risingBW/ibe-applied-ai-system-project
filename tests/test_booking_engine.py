import pytest
import sys
from pathlib import Path
from datetime import datetime, date, time, timedelta

sys.path.insert(0, str(Path(__file__).parent.parent))

from booking_engine import (
    User, Library, Room, Booking, AvailabilitySlot, RoomFilters,
    BookingResult, ConflictResult, ConflictDetector, BookingEngine,
)


# ── Fixtures ───────────────────────────────────────────────────────────────────

@pytest.fixture
def library():
    return Library(
        id="founders", name="Founders Library", campus="Main", building="Founders Hall",
        base_url="", adapter_type="mock",
        open_time="08:00", close_time="22:00",
        max_booking_days_ahead=7, max_booking_duration_hours=2,
        max_bookings_per_user_per_day=1,
    )


@pytest.fixture
def slot():
    start = datetime.combine(date.today() + timedelta(days=1), time(10, 0))
    return AvailabilitySlot(
        id="s1", room_id="r1", library_id="founders",
        start_time=start, end_time=start + timedelta(hours=1),
        duration_minutes=60,
    )


@pytest.fixture
def confirmed_booking(slot):
    return Booking(
        id="bk1", room_id="r1", user_id="alice", library_id="founders",
        start_time=slot.start_time, end_time=slot.end_time,
        duration_minutes=60, purpose="Study", status="confirmed",
    )


@pytest.fixture
def engine():
    return BookingEngine()


# ── ConflictDetector ───────────────────────────────────────────────────────────

class TestConflictDetector:

    def test_no_conflicts_clean_slot(self, slot, library):
        result = ConflictDetector().detect(slot, [], [], library)
        assert result.has_conflict is False
        assert result.warnings == []
        assert result.blockers == []

    def test_gcal_overlap_is_a_warning(self, slot, library):
        ev = {
            "summary": "Team Meeting",
            "start": {"dateTime": slot.start_time.isoformat()},
            "end": {"dateTime": slot.end_time.isoformat()},
        }
        result = ConflictDetector().detect(slot, [ev], [], library)
        assert result.has_conflict is True
        assert any("Team Meeting" in w for w in result.warnings)
        assert "Team Meeting" in result.conflicting_event_titles
        assert result.blockers == []

    def test_gcal_event_no_overlap_is_ignored(self, slot, library):
        ev = {
            "summary": "Later Event",
            "start": {"dateTime": slot.end_time.isoformat()},
            "end": {"dateTime": (slot.end_time + timedelta(hours=1)).isoformat()},
        }
        result = ConflictDetector().detect(slot, [ev], [], library)
        assert result.has_conflict is False

    def test_room_double_book_is_a_blocker(self, slot, library, confirmed_booking):
        result = ConflictDetector().detect(slot, [], [confirmed_booking], library)
        assert result.has_conflict is True
        assert result.blockers != []
        assert "bk1" in result.conflicting_booking_ids

    def test_cancelled_booking_not_a_blocker(self, slot, library, confirmed_booking):
        confirmed_booking.status = "cancelled"
        result = ConflictDetector().detect(slot, [], [confirmed_booking], library)
        assert result.has_conflict is False

    def test_different_room_booking_not_a_blocker(self, slot, library, confirmed_booking):
        confirmed_booking.room_id = "r2"
        result = ConflictDetector().detect(slot, [], [confirmed_booking], library)
        assert result.has_conflict is False

    def test_operating_hours_early_start_is_blocker(self, library):
        start = datetime.combine(date.today(), time(6, 0))
        early = AvailabilitySlot(
            id="s2", room_id="r1", library_id="founders",
            start_time=start, end_time=start + timedelta(hours=1), duration_minutes=60,
        )
        result = ConflictDetector().detect(early, [], [], library)
        assert any("opens at" in b for b in result.blockers)

    def test_operating_hours_late_end_is_blocker(self, library):
        start = datetime.combine(date.today(), time(22, 0))
        late = AvailabilitySlot(
            id="s3", room_id="r1", library_id="founders",
            start_time=start, end_time=start + timedelta(hours=1), duration_minutes=60,
        )
        result = ConflictDetector().detect(late, [], [], library)
        assert any("closes at" in b for b in result.blockers)

    def test_duration_over_limit_is_blocker(self, library):
        start = datetime.combine(date.today(), time(10, 0))
        long_slot = AvailabilitySlot(
            id="s4", room_id="r1", library_id="founders",
            start_time=start, end_time=start + timedelta(hours=3),
            duration_minutes=180,  # exceeds max of 2h
        )
        result = ConflictDetector().detect(long_slot, [], [], library)
        assert any("Max booking duration" in b for b in result.blockers)

    def test_advance_booking_too_far_is_blocker(self, library):
        future = datetime.now() + timedelta(days=10)  # exceeds 7-day limit
        far = AvailabilitySlot(
            id="s5", room_id="r1", library_id="founders",
            start_time=future, end_time=future + timedelta(hours=1), duration_minutes=60,
        )
        result = ConflictDetector().detect(far, [], [], library)
        assert any("advance" in b for b in result.blockers)

    def test_same_day_past_time_is_blocker(self, library):
        start = datetime.now() - timedelta(minutes=30)
        past_slot = AvailabilitySlot(
            id="s5b", room_id="r1", library_id="founders",
            start_time=start, end_time=start + timedelta(hours=1), duration_minutes=60,
        )
        result = ConflictDetector().detect(past_slot, [], [], library)
        assert any("already started or passed" in b for b in result.blockers)

    def test_advance_booking_within_limit_is_allowed(self, library):
        future = datetime.now() + timedelta(days=3)
        near = AvailabilitySlot(
            id="s6", room_id="r1", library_id="founders",
            start_time=future, end_time=future + timedelta(hours=1), duration_minutes=60,
        )
        result = ConflictDetector().detect(near, [], [], library)
        assert not any("advance" in b for b in result.blockers)


# ── BookingEngine ──────────────────────────────────────────────────────────────

class TestBookingEngine:

    def test_add_valid_booking(self, engine, slot):
        booking = Booking(
            id="bk1", room_id="r1", user_id="alice", library_id="founders",
            start_time=slot.start_time, end_time=slot.end_time,
            duration_minutes=60, purpose="Study", status="confirmed",
        )
        engine.add_booking(booking)
        assert len(engine.bookings) == 1

    def test_add_booking_sets_created_at(self, engine, slot):
        booking = Booking(
            id="bk2", room_id="r1", user_id="alice", library_id="founders",
            start_time=slot.start_time, end_time=slot.end_time,
            duration_minutes=60, purpose="Study",
        )
        engine.add_booking(booking)
        assert booking.created_at is not None

    def test_add_booking_invalid_times_raises(self, engine, slot):
        bad = Booking(
            id="bk3", room_id="r1", user_id="alice", library_id="founders",
            start_time=slot.end_time, end_time=slot.start_time,  # reversed
            duration_minutes=60, purpose="Study",
        )
        with pytest.raises(ValueError):
            engine.add_booking(bad)

    def test_add_booking_zero_duration_raises(self, engine, slot):
        bad = Booking(
            id="bk4", room_id="r1", user_id="alice", library_id="founders",
            start_time=slot.start_time, end_time=slot.end_time,
            duration_minutes=0, purpose="Study",
        )
        with pytest.raises(ValueError):
            engine.add_booking(bad)

    def test_cancel_booking_updates_status(self, engine, slot, confirmed_booking):
        engine.add_booking(confirmed_booking)
        result = engine.cancel_booking("bk1", reason="Changed plans")
        assert result is True
        assert engine.bookings[0].status == "cancelled"
        assert engine.bookings[0].cancellation_reason == "Changed plans"

    def test_cancel_booking_sets_updated_at(self, engine, slot, confirmed_booking):
        engine.add_booking(confirmed_booking)
        engine.cancel_booking("bk1")
        assert engine.bookings[0].updated_at is not None

    def test_cancel_nonexistent_booking_returns_false(self, engine):
        assert engine.cancel_booking("does-not-exist") is False

    def test_get_user_bookings_filters_by_user(self, engine, slot):
        b_alice = Booking(
            id="bk5", room_id="r1", user_id="alice", library_id="founders",
            start_time=slot.start_time, end_time=slot.end_time,
            duration_minutes=60, purpose="Study", status="confirmed",
        )
        b_bob = Booking(
            id="bk6", room_id="r2", user_id="bob", library_id="founders",
            start_time=slot.start_time, end_time=slot.end_time,
            duration_minutes=60, purpose="Study", status="confirmed",
        )
        engine.add_booking(b_alice)
        engine.add_booking(b_bob)
        assert [b.id for b in engine.get_user_bookings("alice")] == ["bk5"]
        assert [b.id for b in engine.get_user_bookings("bob")] == ["bk6"]

    def test_get_user_bookings_empty_for_unknown_user(self, engine, slot, confirmed_booking):
        engine.add_booking(confirmed_booking)
        assert engine.get_user_bookings("nobody") == []

    def test_check_conflicts_delegates_to_detector(self, engine, slot, library, confirmed_booking):
        engine.add_booking(confirmed_booking)
        # Same room, overlapping time — should produce a blocker
        overlap = AvailabilitySlot(
            id="s7", room_id="r1", library_id="founders",
            start_time=slot.start_time + timedelta(minutes=30),
            end_time=slot.end_time + timedelta(minutes=30),
            duration_minutes=60,
        )
        result = engine.check_conflicts(overlap, [], library)
        assert result.has_conflict is True
        assert result.blockers != []


# ── Domain model validation ────────────────────────────────────────────────────

class TestBookingValidation:

    def test_valid_booking_passes(self, slot):
        b = Booking(
            id="bk7", room_id="r1", user_id="u1", library_id="founders",
            start_time=slot.start_time, end_time=slot.end_time,
            duration_minutes=60, purpose="Study",
        )
        assert b.validate() is True

    def test_end_before_start_raises(self, slot):
        b = Booking(
            id="bk8", room_id="r1", user_id="u1", library_id="founders",
            start_time=slot.end_time, end_time=slot.start_time,
            duration_minutes=60, purpose="Study",
        )
        with pytest.raises(ValueError, match="end_time must be after start_time"):
            b.validate()

    def test_zero_duration_raises(self, slot):
        b = Booking(
            id="bk9", room_id="r1", user_id="u1", library_id="founders",
            start_time=slot.start_time, end_time=slot.end_time,
            duration_minutes=0, purpose="Study",
        )
        with pytest.raises(ValueError, match="duration_minutes must be positive"):
            b.validate()
