"""Phase 3 conflict-detection tests: dynamic hours, open-day, user daily limit."""
import sys
from datetime import date, datetime, time, timedelta
from pathlib import Path
from unittest.mock import MagicMock

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

from adapters.mock import MockAdapter
from booking_engine import (
    AvailabilitySlot, Booking, BookingEngine,
    ConflictDetector, ConflictResult, Library,
)


# ── Fixtures ───────────────────────────────────────────────────────────────────

@pytest.fixture
def library():
    return Library(
        id="founders", name="Founders Library", campus="Main", building="Founders Hall",
        base_url="", adapter_type="mock",
        open_time="08:00", close_time="22:00",
        open_days=["Mon", "Tue", "Wed", "Thu", "Fri", "Sat"],  # closed Sunday
        max_booking_days_ahead=7, max_booking_duration_hours=2,
        max_bookings_per_user_per_day=1,
    )


def _slot_on_weekday(library_id: str = "founders", hour: int = 10, duration: int = 60) -> AvailabilitySlot:
    """Return a slot on the next Monday."""
    today = date.today()
    days_until_monday = (7 - today.weekday()) % 7 or 7
    monday = today + timedelta(days=days_until_monday)
    start = datetime.combine(monday, time(hour, 0))
    return AvailabilitySlot(
        id="s1", room_id="r1", library_id=library_id,
        start_time=start, end_time=start + timedelta(minutes=duration),
        duration_minutes=duration,
    )


def _slot_on_sunday(library_id: str = "founders") -> AvailabilitySlot:
    """Return a slot on the next Sunday."""
    today = date.today()
    days_until_sunday = (6 - today.weekday()) % 7 or 7
    sunday = today + timedelta(days=days_until_sunday)
    start = datetime.combine(sunday, time(10, 0))
    return AvailabilitySlot(
        id="s2", room_id="r1", library_id=library_id,
        start_time=start, end_time=start + timedelta(hours=1),
        duration_minutes=60,
    )


# ── _check_open_day ────────────────────────────────────────────────────────────

class TestCheckOpenDay:

    def test_blocks_on_closed_day(self, library):
        slot = _slot_on_sunday()
        result = ConflictDetector().detect(slot, [], [], library)
        assert any("closed on Sunday" in b for b in result.blockers)

    def test_allows_on_open_day(self, library):
        slot = _slot_on_weekday()
        cd = ConflictDetector()
        blockers = cd._check_open_day(slot, library)
        assert blockers == []

    def test_open_days_all_seven_never_blocks(self, library):
        library.open_days = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]
        slot = _slot_on_sunday()
        blockers = ConflictDetector()._check_open_day(slot, library)
        assert blockers == []


# ── _check_operating_hours with dynamic hours ──────────────────────────────────

class TestDynamicOperatingHours:

    def test_uses_adapter_hours_not_static(self, library):
        """Adapter returns 10:00–18:00; static is 08:00–22:00. Slot at 09:00 should block."""
        adapter = MagicMock()
        adapter.fetch_hours.return_value = ("10:00", "18:00")
        slot = _slot_on_weekday(hour=9)  # before 10:00
        cd = ConflictDetector()
        blockers = cd._check_operating_hours(slot, library, adapter)
        assert any("opens at 10:00" in b for b in blockers)

    def test_adapter_closed_returns_blocker(self, library):
        """Adapter signals holiday closure (returns None) → blocker."""
        adapter = MagicMock()
        adapter.fetch_hours.return_value = None
        slot = _slot_on_weekday()
        blockers = ConflictDetector()._check_operating_hours(slot, library, adapter)
        assert any("closed on" in b for b in blockers)

    def test_adapter_error_falls_back_to_static(self, library):
        """Adapter raises → fall back to static 08:00–22:00 → slot at 10:00 is fine."""
        adapter = MagicMock()
        adapter.fetch_hours.side_effect = ConnectionError("timeout")
        slot = _slot_on_weekday(hour=10)
        blockers = ConflictDetector()._check_operating_hours(slot, library, adapter)
        assert blockers == []

    def test_no_adapter_uses_static_config(self, library):
        """No adapter passed → static hours used directly."""
        slot = _slot_on_weekday(hour=10)
        blockers = ConflictDetector()._check_operating_hours(slot, library, adapter=None)
        assert blockers == []

    def test_adapter_extended_hours_allows_late_slot(self, library):
        """Adapter returns extended hours 08:00–23:00 → slot at 22:30 is allowed."""
        adapter = MagicMock()
        adapter.fetch_hours.return_value = ("08:00", "23:00")
        monday = _slot_on_weekday().start_time.date()
        start = datetime.combine(monday, time(22, 30))
        late_slot = AvailabilitySlot(
            id="s3", room_id="r1", library_id="founders",
            start_time=start, end_time=start + timedelta(minutes=30),
            duration_minutes=30,
        )
        blockers = ConflictDetector()._check_operating_hours(late_slot, library, adapter)
        assert blockers == []


# ── MockAdapter.fetch_hours ────────────────────────────────────────────────────

class TestMockAdapterFetchHours:

    def test_returns_config_hours_on_open_day(self, library):
        adapter = MockAdapter(library)
        monday = _slot_on_weekday().start_time.date()
        result = adapter.fetch_hours(monday)
        assert result == ("08:00", "22:00")

    def test_returns_none_on_closed_day(self, library):
        adapter = MockAdapter(library)
        sunday = _slot_on_sunday().start_time.date()
        result = adapter.fetch_hours(sunday)
        assert result is None

    def test_returns_hours_for_saturday_when_open(self, library):
        adapter = MockAdapter(library)
        today = date.today()
        days_until_sat = (5 - today.weekday()) % 7 or 7
        saturday = today + timedelta(days=days_until_sat)
        result = adapter.fetch_hours(saturday)
        assert result == ("08:00", "22:00")


# ── _check_user_daily_limit ───────────────────────────────────────────────────

class TestUserDailyLimit:

    def _make_booking(self, user_id: str, library_id: str, slot: AvailabilitySlot,
                      status: str = "confirmed") -> Booking:
        return Booking(
            id=f"bk-{user_id}-{slot.start_time.hour}",
            room_id=slot.room_id, user_id=user_id, library_id=library_id,
            start_time=slot.start_time, end_time=slot.end_time,
            duration_minutes=slot.duration_minutes, purpose="Study", status=status,
        )

    def test_blocks_when_daily_limit_reached(self, library):
        slot = _slot_on_weekday()
        existing = self._make_booking("alice", "founders", slot)
        cd = ConflictDetector()
        blockers = cd._check_user_daily_limit(slot, "alice", [existing], library)
        assert any("daily limit" in b for b in blockers)

    def test_allows_when_under_limit(self, library):
        library.max_bookings_per_user_per_day = 2
        slot = _slot_on_weekday()
        existing = self._make_booking("alice", "founders", slot)
        cd = ConflictDetector()
        blockers = cd._check_user_daily_limit(slot, "alice", [existing], library)
        assert blockers == []

    def test_cancelled_booking_not_counted(self, library):
        slot = _slot_on_weekday()
        cancelled = self._make_booking("alice", "founders", slot, status="cancelled")
        cd = ConflictDetector()
        blockers = cd._check_user_daily_limit(slot, "alice", [cancelled], library)
        assert blockers == []

    def test_different_library_not_counted(self, library):
        slot = _slot_on_weekday()
        other_lib_booking = self._make_booking("alice", "law", slot)
        cd = ConflictDetector()
        blockers = cd._check_user_daily_limit(slot, "alice", [other_lib_booking], library)
        assert blockers == []

    def test_different_user_not_counted(self, library):
        slot = _slot_on_weekday()
        bobs = self._make_booking("bob", "founders", slot)
        cd = ConflictDetector()
        blockers = cd._check_user_daily_limit(slot, "alice", [bobs], library)
        assert blockers == []

    def test_different_day_not_counted(self, library):
        slot = _slot_on_weekday()
        yesterday_start = slot.start_time - timedelta(days=1)
        old = Booking(
            id="bk-old", room_id="r2", user_id="alice", library_id="founders",
            start_time=yesterday_start,
            end_time=yesterday_start + timedelta(hours=1),
            duration_minutes=60, purpose="Study", status="confirmed",
        )
        cd = ConflictDetector()
        blockers = cd._check_user_daily_limit(slot, "alice", [old], library)
        assert blockers == []

    def test_no_existing_bookings_always_allowed(self, library):
        slot = _slot_on_weekday()
        blockers = ConflictDetector()._check_user_daily_limit(slot, "alice", [], library)
        assert blockers == []


# ── BookingEngine.check_conflicts integration ─────────────────────────────────

class TestBookingEnginePhase3Integration:

    def test_engine_passes_user_id_for_daily_limit(self, library):
        engine = BookingEngine()
        adapter = MockAdapter(library)
        engine.register_library(library.id, adapter)

        slot = _slot_on_weekday()
        # Add one existing confirmed booking for alice
        existing = Booking(
            id="bk-existing", room_id="r2", user_id="alice", library_id="founders",
            start_time=slot.start_time, end_time=slot.end_time,
            duration_minutes=60, purpose="Study", status="confirmed",
        )
        engine.bookings.append(existing)

        result = engine.check_conflicts(slot, [], library, user_id="alice")
        assert any("daily limit" in b for b in result.blockers)

    def test_engine_uses_adapter_for_dynamic_hours(self, library):
        engine = BookingEngine()
        adapter = MagicMock()
        adapter.library = library
        adapter.fetch_hours.return_value = ("12:00", "18:00")  # only open afternoons
        engine.libraries[library.id] = adapter
        engine.library_meta[library.id] = library

        slot = _slot_on_weekday(hour=9)  # before noon
        result = engine.check_conflicts(slot, [], library)
        assert any("opens at 12:00" in b for b in result.blockers)

    def test_engine_blocks_closed_day_via_adapter(self, library):
        engine = BookingEngine()
        adapter = MockAdapter(library)
        engine.register_library(library.id, adapter)

        slot = _slot_on_sunday()
        result = engine.check_conflicts(slot, [], library, user_id="alice")
        # Should trigger both _check_open_day and _check_operating_hours(None)
        assert result.has_conflict is True
        assert result.blockers != []

    def test_engine_no_conflicts_clean_weekday_slot(self, library):
        engine = BookingEngine()
        adapter = MockAdapter(library)
        engine.register_library(library.id, adapter)

        slot = _slot_on_weekday(hour=10)
        result = engine.check_conflicts(slot, [], library, user_id="alice")
        assert result.has_conflict is False
