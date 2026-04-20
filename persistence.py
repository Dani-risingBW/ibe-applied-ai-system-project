"""SQLite-backed booking store for Phase 8 persistence.

BookingStore is used by BookingEngine when a db_path is provided.
The default :memory: path gives identical in-memory behaviour for tests.
"""
from __future__ import annotations

import sqlite3
from datetime import datetime
from typing import List, Optional

from booking_engine import Booking

_SCHEMA = """
CREATE TABLE IF NOT EXISTS bookings (
    id                   TEXT PRIMARY KEY,
    room_id              TEXT NOT NULL,
    user_id              TEXT NOT NULL,
    library_id           TEXT NOT NULL,
    start_time           TEXT NOT NULL,
    end_time             TEXT NOT NULL,
    duration_minutes     INTEGER NOT NULL,
    purpose              TEXT NOT NULL,
    status               TEXT NOT NULL DEFAULT 'confirmed',
    gcal_event_id        TEXT,
    confirmation_code    TEXT,
    cancellation_reason  TEXT,
    created_at           TEXT,
    updated_at           TEXT,
    notes                TEXT
);
"""


class BookingStore:
    """Thin SQLite wrapper used by BookingEngine as its backing store."""

    def __init__(self, db_path: str = ":memory:") -> None:
        self.db_path = db_path
        self._conn = sqlite3.connect(db_path, check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._conn.executescript(_SCHEMA)
        self._conn.commit()

    # ── Write ──────────────────────────────────────────────────────────────────

    def save(self, booking: Booking) -> None:
        """Insert or replace a booking row."""
        self._conn.execute(
            """
            INSERT OR REPLACE INTO bookings
              (id, room_id, user_id, library_id, start_time, end_time,
               duration_minutes, purpose, status, gcal_event_id,
               confirmation_code, cancellation_reason, created_at, updated_at, notes)
            VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
            """,
            (
                booking.id,
                booking.room_id,
                booking.user_id,
                booking.library_id,
                booking.start_time.isoformat(),
                booking.end_time.isoformat(),
                booking.duration_minutes,
                booking.purpose,
                booking.status,
                booking.gcal_event_id,
                booking.confirmation_code,
                booking.cancellation_reason,
                booking.created_at.isoformat() if booking.created_at else None,
                booking.updated_at.isoformat() if booking.updated_at else None,
                booking.notes,
            ),
        )
        self._conn.commit()

    def update_status(self, booking_id: str, status: str, reason: str = "") -> bool:
        """Set status (and optionally cancellation_reason) for a booking."""
        cur = self._conn.execute(
            """
            UPDATE bookings
               SET status = ?, cancellation_reason = ?, updated_at = ?
             WHERE id = ?
            """,
            (status, reason or None, datetime.now().isoformat(), booking_id),
        )
        self._conn.commit()
        return cur.rowcount > 0

    def update_gcal_event_id(self, booking_id: str, gcal_event_id: str) -> None:
        """Persist the Google Calendar event ID after a successful GCal sync."""
        self._conn.execute(
            "UPDATE bookings SET gcal_event_id = ? WHERE id = ?",
            (gcal_event_id, booking_id),
        )
        self._conn.commit()

    # ── Read ───────────────────────────────────────────────────────────────────

    def load_all(self) -> List[Booking]:
        """Return every booking row as Booking objects."""
        rows = self._conn.execute(
            "SELECT * FROM bookings ORDER BY start_time"
        ).fetchall()
        return [_row_to_booking(r) for r in rows]

    def count(self) -> int:
        return self._conn.execute("SELECT COUNT(*) FROM bookings").fetchone()[0]

    # ── Lifecycle ──────────────────────────────────────────────────────────────

    def close(self) -> None:
        self._conn.close()


# ── Helpers ────────────────────────────────────────────────────────────────────

def _row_to_booking(row: sqlite3.Row) -> Booking:
    def _dt(s: Optional[str]) -> Optional[datetime]:
        return datetime.fromisoformat(s) if s else None

    return Booking(
        id=row["id"],
        room_id=row["room_id"],
        user_id=row["user_id"],
        library_id=row["library_id"],
        start_time=datetime.fromisoformat(row["start_time"]),
        end_time=datetime.fromisoformat(row["end_time"]),
        duration_minutes=row["duration_minutes"],
        purpose=row["purpose"],
        status=row["status"],
        gcal_event_id=row["gcal_event_id"],
        confirmation_code=row["confirmation_code"],
        cancellation_reason=row["cancellation_reason"],
        created_at=_dt(row["created_at"]),
        updated_at=_dt(row["updated_at"]),
        notes=row["notes"],
    )
