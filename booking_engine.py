from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta, date, time
from typing import Any, Dict, List, Optional


def _parse_hhmm(hhmm: str, base_date: date) -> datetime:
    h, m = map(int, hhmm.split(":"))
    return datetime.combine(base_date, time(hour=h, minute=m))


def _parse_gcal_dt(event_time: Dict[str, str]) -> Optional[datetime]:
    raw = event_time.get("dateTime") or event_time.get("date")
    if not raw:
        return None
    try:
        return datetime.fromisoformat(raw[:19])  # strip tz offset for naive comparison
    except ValueError:
        return None


# ── Domain models ──────────────────────────────────────────────────────────────

@dataclass
class User:
    id: Optional[str]
    name: str
    email: str
    university_id: Optional[str] = None
    password_hash: Optional[str] = None
    default_library_id: Optional[str] = None
    max_hours_per_week: int = 10
    preferred_times: Dict[str, Any] = field(default_factory=dict)
    created_at: Optional[datetime] = None


@dataclass
class Library:
    id: str
    name: str
    campus: str
    building: str
    base_url: str
    adapter_type: str                  # 'libcal' | 'scraper' | 'mock'
    open_time: str                     # "HH:MM"
    close_time: str                    # "HH:MM"
    open_days: List[str] = field(default_factory=lambda: ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"])
    max_booking_days_ahead: int = 7
    max_booking_duration_hours: int = 2
    max_bookings_per_user_per_day: int = 1


@dataclass
class Room:
    id: str
    library_id: str
    name: str
    floor: str
    room_type: str                     # 'study_room' | 'conference' | 'lab'
    capacity: int
    accessible: bool = False
    has_whiteboard: bool = False
    has_display: bool = False
    has_phone: bool = False
    has_video_conf: bool = False
    image_url: Optional[str] = None
    notes: Optional[str] = None


@dataclass
class Booking:
    id: Optional[str]
    room_id: str
    user_id: str
    library_id: str
    start_time: datetime
    end_time: datetime
    duration_minutes: int
    purpose: str
    status: str = "pending"            # pending | confirmed | cancelled | completed
    gcal_event_id: Optional[str] = None
    confirmation_code: Optional[str] = None
    cancellation_reason: Optional[str] = None
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None
    notes: Optional[str] = None

    def validate(self) -> bool:
        if self.end_time <= self.start_time:
            raise ValueError("Booking end_time must be after start_time")
        if self.duration_minutes <= 0:
            raise ValueError("Booking duration_minutes must be positive")
        return True


@dataclass
class AvailabilitySlot:
    id: str
    room_id: str
    library_id: str
    start_time: datetime
    end_time: datetime
    duration_minutes: int
    is_available: bool = True
    unavailable_reason: Optional[str] = None
    fetched_at: Optional[datetime] = None
    metadata: Dict[str, Any] = field(default_factory=dict)


@dataclass
class RoomFilters:
    min_capacity: int = 1
    max_capacity: Optional[int] = None
    amenities: List[str] = field(default_factory=list)
    accessible_only: bool = False
    duration_minutes: int = 60
    room_type: Optional[str] = None
    floor: Optional[str] = None


@dataclass
class BookingResult:
    success: bool
    confirmation_code: Optional[str] = None
    booking_id: Optional[str] = None
    message: str = ""
    error_code: Optional[str] = None
    raw_response: Optional[Dict[str, Any]] = None


@dataclass
class ConflictResult:
    has_conflict: bool
    warnings: List[str] = field(default_factory=list)
    blockers: List[str] = field(default_factory=list)
    conflicting_event_titles: List[str] = field(default_factory=list)
    conflicting_booking_ids: List[str] = field(default_factory=list)


# ── Conflict detection ─────────────────────────────────────────────────────────

class ConflictDetector:

    def detect(
        self,
        slot: AvailabilitySlot,
        gcal_events: List[Dict[str, Any]],
        existing_bookings: List[Booking],
        library: Library,
        adapter: Any = None,
        user_id: Optional[str] = None,
    ) -> ConflictResult:
        warnings: List[str] = []
        blockers: List[str] = []
        conflicting_event_titles: List[str] = []
        conflicting_booking_ids: List[str] = []

        warnings.extend(self._check_gcal_overlap(slot, gcal_events, conflicting_event_titles))
        blockers.extend(self._check_room_double_book(slot, existing_bookings, conflicting_booking_ids))
        blockers.extend(self._check_open_day(slot, library))
        blockers.extend(self._check_operating_hours(slot, library, adapter))
        blockers.extend(self._check_advance_limit(slot, library))
        blockers.extend(self._check_duration_limit(slot, library))
        if user_id:
            blockers.extend(self._check_user_daily_limit(slot, user_id, existing_bookings, library))

        return ConflictResult(
            has_conflict=bool(warnings or blockers),
            warnings=warnings,
            blockers=blockers,
            conflicting_event_titles=conflicting_event_titles,
            conflicting_booking_ids=conflicting_booking_ids,
        )

    def _check_gcal_overlap(
        self,
        slot: AvailabilitySlot,
        events: List[Dict[str, Any]],
        titles_out: List[str],
    ) -> List[str]:
        found: List[str] = []
        for ev in events:
            ev_start = _parse_gcal_dt(ev.get("start", {}))
            ev_end = _parse_gcal_dt(ev.get("end", {}))
            if ev_start is None or ev_end is None:
                continue
            if slot.start_time < ev_end and slot.end_time > ev_start:
                title = ev.get("summary", "Untitled event")
                found.append(
                    f"Overlaps Google Calendar event '{title}' "
                    f"({ev_start.strftime('%H:%M')}–{ev_end.strftime('%H:%M')})."
                )
                titles_out.append(title)
        return found

    def _check_room_double_book(
        self,
        slot: AvailabilitySlot,
        bookings: List[Booking],
        ids_out: List[str],
    ) -> List[str]:
        found: List[str] = []
        for b in bookings:
            if b.room_id != slot.room_id or b.status == "cancelled":
                continue
            if slot.start_time < b.end_time and slot.end_time > b.start_time:
                found.append(
                    f"Room already booked from {b.start_time.strftime('%H:%M')} "
                    f"to {b.end_time.strftime('%H:%M')}."
                )
                if b.id:
                    ids_out.append(b.id)
        return found

    def _check_open_day(self, slot: AvailabilitySlot, library: Library) -> List[str]:
        """Block if the library does not operate on the slot's day of week."""
        day_abbr = slot.start_time.strftime("%a")  # "Mon", "Tue", …
        if day_abbr not in library.open_days:
            return [
                f"{library.name} is closed on "
                f"{slot.start_time.strftime('%A')}s."
            ]
        return []

    def _check_operating_hours(
        self,
        slot: AvailabilitySlot,
        library: Library,
        adapter: Any = None,
    ) -> List[str]:
        """Check slot against operating hours.

        Calls adapter.fetch_hours() for live/holiday-aware hours when available.
        Falls back to Library.open_time / close_time on error or when no adapter.
        """
        base = slot.start_time.date()
        open_time = library.open_time
        close_time = library.close_time

        if adapter is not None:
            try:
                hours = adapter.fetch_hours(base)
                if hours is None:
                    return [
                        f"{library.name} is closed on "
                        f"{slot.start_time.strftime('%A, %B %d')}."
                    ]
                open_time, close_time = hours
            except Exception:
                pass  # fall back to static config

        found: List[str] = []
        open_dt = _parse_hhmm(open_time, base)
        close_dt = _parse_hhmm(close_time, base)
        if slot.start_time < open_dt:
            found.append(f"Library opens at {open_time} — slot starts too early.")
        if slot.end_time > close_dt:
            found.append(f"Library closes at {close_time} — slot ends too late.")
        return found

    def _check_advance_limit(self, slot: AvailabilitySlot, library: Library) -> List[str]:
        now_dt = datetime.now()
        if slot.start_time <= now_dt:
            return [
                "Cannot book a slot that has already started or passed "
                f"({slot.start_time.strftime('%b %d %H:%M')})."
            ]

        days_ahead = (slot.start_time.date() - date.today()).days
        if days_ahead < 0:
            return [f"Cannot book a slot in the past ({slot.start_time.strftime('%b %d')})."]
        if days_ahead > library.max_booking_days_ahead:
            return [
                f"Cannot book more than {library.max_booking_days_ahead} days in advance "
                f"(this slot is {days_ahead} days away)."
            ]
        return []

    def _check_duration_limit(self, slot: AvailabilitySlot, library: Library) -> List[str]:
        max_minutes = library.max_booking_duration_hours * 60
        if slot.duration_minutes > max_minutes:
            return [
                f"Max booking duration is {library.max_booking_duration_hours}h "
                f"({slot.duration_minutes} min requested)."
            ]
        return []

    def _check_user_daily_limit(
        self,
        slot: AvailabilitySlot,
        user_id: str,
        bookings: List[Booking],
        library: Library,
    ) -> List[str]:
        """Block if the user already holds max_bookings_per_user_per_day at this library."""
        slot_date = slot.start_time.date()
        count = sum(
            1 for b in bookings
            if b.user_id == user_id
            and b.library_id == library.id
            and b.status not in ("cancelled",)
            and b.start_time.date() == slot_date
        )
        if count >= library.max_bookings_per_user_per_day:
            return [
                f"You already have {count} booking(s) at {library.name} on "
                f"{slot_date.strftime('%b %d')} "
                f"(daily limit: {library.max_bookings_per_user_per_day})."
            ]
        return []


# ── Booking engine ─────────────────────────────────────────────────────────────

class BookingEngine:

    def __init__(self, db_path: Optional[str] = None) -> None:
        self.libraries: Dict[str, Any] = {}    # library_id -> BaseLibraryAdapter
        self.library_meta: Dict[str, Any] = {} # library_id -> Library (metadata only)
        self.gcal = None
        self.conflict_detector = ConflictDetector()
        self._store = None
        if db_path:
            from persistence import BookingStore
            self._store = BookingStore(db_path)
            self.bookings: List[Booking] = self._store.load_all()
        else:
            self.bookings: List[Booking] = []

    def register_library(self, library_id: str, adapter: Any) -> None:
        self.libraries[library_id] = adapter
        self.library_meta[library_id] = adapter.library

    def get_library(self, library_id: str) -> Optional["Library"]:
        return self.library_meta.get(library_id)

    # ── Availability ───────────────────────────────────────────────────────────

    def fetch_availability(
        self,
        library_id: str,
        target_date: "date",
        filters: "RoomFilters",
    ) -> List[AvailabilitySlot]:
        adapter = self.libraries.get(library_id)
        if adapter is None:
            raise ValueError(f"No adapter registered for library '{library_id}'")
        return adapter.fetch_availability(target_date, filters)

    # ── Conflict detection ─────────────────────────────────────────────────────

    def check_conflicts(
        self,
        slot: AvailabilitySlot,
        gcal_events: List[Dict[str, Any]],
        library: "Library",
        user_id: Optional[str] = None,
    ) -> ConflictResult:
        adapter = self.libraries.get(library.id)
        return self.conflict_detector.detect(
            slot, gcal_events, self.bookings, library,
            adapter=adapter, user_id=user_id,
        )

    # ── Booking lifecycle ──────────────────────────────────────────────────────

    def book_room(
        self,
        slot: AvailabilitySlot,
        user: Any,
        purpose: str = "Study",
        notes: Optional[str] = None,
        dry_run: bool = False,
    ) -> tuple[Any, Optional[Booking]]:
        """Submit booking via adapter. Returns (BookingResult, Booking | None).

        On success, the Booking is added to the local store.
        dry_run=True validates and returns a mock result without hitting the library.
        """
        from booking_engine import BookingResult as BR

        if dry_run:
            result = BR(success=True, message="Dry run — not submitted", booking_id="DRY_RUN")
            return result, None

        adapter = self.libraries.get(slot.library_id)
        if adapter is None:
            result = BR(success=False, message=f"No adapter for '{slot.library_id}'", error_code="NO_ADAPTER")
            return result, None

        result = adapter.book_room(slot, user)
        booking = None
        if result.success:
            booking = Booking(
                id=result.booking_id or result.confirmation_code,
                room_id=slot.room_id,
                user_id=user.id,
                library_id=slot.library_id,
                start_time=slot.start_time,
                end_time=slot.end_time,
                duration_minutes=slot.duration_minutes,
                purpose=(purpose or "").strip() or "Study",
                status="confirmed",
                confirmation_code=result.confirmation_code,
                notes=notes,
            )
            self.add_booking(booking)
        return result, booking

    def add_booking(self, booking: Booking) -> None:
        booking.validate()
        booking.created_at = datetime.now()
        self.bookings.append(booking)
        if self._store:
            self._store.save(booking)

    def cancel_booking(self, booking_id: str, reason: str = "") -> bool:
        for b in self.bookings:
            if b.id == booking_id:
                b.status = "cancelled"
                b.cancellation_reason = reason
                b.updated_at = datetime.now()
                if self._store:
                    self._store.update_status(booking_id, "cancelled", reason)
                return True
        return False

    def update_gcal_event_id(self, booking_id: str, gcal_event_id: str) -> None:
        """Persist a Google Calendar event ID after a successful sync."""
        for b in self.bookings:
            if b.id == booking_id:
                b.gcal_event_id = gcal_event_id
                break
        if self._store:
            self._store.update_gcal_event_id(booking_id, gcal_event_id)

    def get_user_bookings(self, user_id: str) -> List[Booking]:
        return [b for b in self.bookings if b.user_id == user_id]

    def get_room_bookings(self, room_id: str) -> List[Booking]:
        return [b for b in self.bookings if b.room_id == room_id]


__all__ = [
    "User", "Library", "Room", "Booking", "AvailabilitySlot",
    "RoomFilters", "BookingResult", "ConflictResult",
    "ConflictDetector", "BookingEngine",
]
