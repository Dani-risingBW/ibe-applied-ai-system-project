"""Phase 8 persistence tests — BookingStore (SQLite) and BookingEngine integration."""
import sys
from datetime import datetime, timedelta
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

from booking_engine import Booking, BookingEngine
from persistence import BookingStore


# ── Fixtures ───────────────────────────────────────────────────────────────────

@pytest.fixture
def store():
    """In-memory BookingStore, fresh for each test."""
    return BookingStore(":memory:")


@pytest.fixture
def booking():
    start = datetime(2026, 4, 25, 10, 0)
    return Booking(
        id="bk-test-001",
        room_id="founders-room-1",
        user_id="alice@test.edu",
        library_id="founders",
        start_time=start,
        end_time=start + timedelta(hours=1),
        duration_minutes=60,
        purpose="Group project",
        status="confirmed",
        confirmation_code="CONF-TEST",
        notes="Bring markers",
        created_at=datetime.now(),
    )


# ── BookingStore.save / load_all ───────────────────────────────────────────────

class TestBookingStoreSaveLoad:

    def test_save_and_load_round_trip(self, store, booking):
        store.save(booking)
        loaded = store.load_all()
        assert len(loaded) == 1
        b = loaded[0]
        assert b.id == booking.id
        assert b.room_id == booking.room_id
        assert b.user_id == booking.user_id
        assert b.library_id == booking.library_id
        assert b.purpose == booking.purpose
        assert b.status == booking.status

    def test_start_end_times_preserved(self, store, booking):
        store.save(booking)
        b = store.load_all()[0]
        assert b.start_time == booking.start_time
        assert b.end_time == booking.end_time

    def test_notes_and_confirmation_code_preserved(self, store, booking):
        store.save(booking)
        b = store.load_all()[0]
        assert b.notes == booking.notes
        assert b.confirmation_code == booking.confirmation_code

    def test_none_fields_round_trip(self, store, booking):
        booking.gcal_event_id = None
        booking.cancellation_reason = None
        store.save(booking)
        b = store.load_all()[0]
        assert b.gcal_event_id is None
        assert b.cancellation_reason is None

    def test_multiple_bookings_saved(self, store, booking):
        b2 = Booking(
            id="bk-test-002", room_id="founders-room-2",
            user_id="bob@test.edu", library_id="founders",
            start_time=booking.start_time + timedelta(hours=2),
            end_time=booking.end_time + timedelta(hours=2),
            duration_minutes=60, purpose="Solo study", status="confirmed",
        )
        store.save(booking)
        store.save(b2)
        assert store.count() == 2

    def test_replace_on_duplicate_id(self, store, booking):
        store.save(booking)
        booking.purpose = "Updated purpose"
        store.save(booking)
        loaded = store.load_all()
        assert len(loaded) == 1
        assert loaded[0].purpose == "Updated purpose"

    def test_load_all_empty_store(self, store):
        assert store.load_all() == []

    def test_count_reflects_saves(self, store, booking):
        assert store.count() == 0
        store.save(booking)
        assert store.count() == 1


# ── BookingStore.update_status ─────────────────────────────────────────────────

class TestBookingStoreUpdateStatus:

    def test_cancels_booking(self, store, booking):
        store.save(booking)
        result = store.update_status(booking.id, "cancelled", "User request")
        assert result is True
        b = store.load_all()[0]
        assert b.status == "cancelled"
        assert b.cancellation_reason == "User request"

    def test_returns_false_for_unknown_id(self, store):
        result = store.update_status("nonexistent", "cancelled")
        assert result is False

    def test_updated_at_set_on_cancel(self, store, booking):
        store.save(booking)
        store.update_status(booking.id, "cancelled")
        b = store.load_all()[0]
        assert b.updated_at is not None

    def test_empty_reason_stored_as_none(self, store, booking):
        store.save(booking)
        store.update_status(booking.id, "cancelled", "")
        b = store.load_all()[0]
        assert b.cancellation_reason is None


# ── BookingStore.update_gcal_event_id ─────────────────────────────────────────

class TestBookingStoreUpdateGcal:

    def test_persists_gcal_event_id(self, store, booking):
        store.save(booking)
        store.update_gcal_event_id(booking.id, "gcal-abc-123")
        b = store.load_all()[0]
        assert b.gcal_event_id == "gcal-abc-123"

    def test_update_gcal_on_unknown_id_is_noop(self, store):
        store.update_gcal_event_id("no-such-id", "gcal-xyz")  # should not raise


# ── BookingEngine with db_path ─────────────────────────────────────────────────

class TestBookingEngineWithPersistence:

    def test_engine_defaults_to_no_store(self):
        engine = BookingEngine()
        assert engine._store is None

    def test_engine_creates_store_with_db_path(self):
        engine = BookingEngine(db_path=":memory:")
        assert engine._store is not None

    def test_add_booking_persists_to_store(self):
        engine = BookingEngine(db_path=":memory:")
        start = datetime(2026, 4, 25, 10, 0)
        b = Booking(
            id="bk-eng-001", room_id="r1", user_id="alice",
            library_id="founders", start_time=start,
            end_time=start + timedelta(hours=1),
            duration_minutes=60, purpose="Study", status="confirmed",
        )
        engine.add_booking(b)
        assert engine._store.count() == 1

    def test_cancel_booking_updates_store(self):
        engine = BookingEngine(db_path=":memory:")
        start = datetime(2026, 4, 25, 10, 0)
        b = Booking(
            id="bk-eng-002", room_id="r1", user_id="alice",
            library_id="founders", start_time=start,
            end_time=start + timedelta(hours=1),
            duration_minutes=60, purpose="Study", status="confirmed",
        )
        engine.add_booking(b)
        engine.cancel_booking("bk-eng-002", reason="Test cancel")
        stored = engine._store.load_all()[0]
        assert stored.status == "cancelled"
        assert stored.cancellation_reason == "Test cancel"

    def test_update_gcal_event_id_syncs_to_store(self):
        engine = BookingEngine(db_path=":memory:")
        start = datetime(2026, 4, 25, 10, 0)
        b = Booking(
            id="bk-eng-003", room_id="r1", user_id="alice",
            library_id="founders", start_time=start,
            end_time=start + timedelta(hours=1),
            duration_minutes=60, purpose="Study", status="confirmed",
        )
        engine.add_booking(b)
        engine.update_gcal_event_id("bk-eng-003", "gcal-event-xyz")
        assert engine._store.load_all()[0].gcal_event_id == "gcal-event-xyz"

    def test_update_gcal_event_id_updates_in_memory_booking(self):
        engine = BookingEngine(db_path=":memory:")
        start = datetime(2026, 4, 25, 10, 0)
        b = Booking(
            id="bk-eng-004", room_id="r1", user_id="alice",
            library_id="founders", start_time=start,
            end_time=start + timedelta(hours=1),
            duration_minutes=60, purpose="Study", status="confirmed",
        )
        engine.add_booking(b)
        engine.update_gcal_event_id("bk-eng-004", "gcal-in-mem")
        assert engine.bookings[0].gcal_event_id == "gcal-in-mem"

    def test_bookings_loaded_from_db_on_init(self):
        import tempfile, os
        with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
            db_path = f.name
        try:
            # Write a booking via first engine instance
            e1 = BookingEngine(db_path=db_path)
            start = datetime(2026, 4, 25, 10, 0)
            b = Booking(
                id="bk-persist", room_id="r1", user_id="alice",
                library_id="founders", start_time=start,
                end_time=start + timedelta(hours=1),
                duration_minutes=60, purpose="Study", status="confirmed",
            )
            e1.add_booking(b)
            e1._store.close()
            # Second engine instance reads it back from disk
            e2 = BookingEngine(db_path=db_path)
            assert len(e2.bookings) == 1
            assert e2.bookings[0].id == "bk-persist"
            e2._store.close()
        finally:
            os.unlink(db_path)

    def test_engine_without_store_works_as_before(self):
        engine = BookingEngine()
        start = datetime(2026, 4, 25, 10, 0)
        b = Booking(
            id="bk-nomem", room_id="r1", user_id="alice",
            library_id="founders", start_time=start,
            end_time=start + timedelta(hours=1),
            duration_minutes=60, purpose="Study", status="confirmed",
        )
        engine.add_booking(b)
        assert len(engine.bookings) == 1
        assert engine._store is None
