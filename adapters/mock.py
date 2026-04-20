from __future__ import annotations

import uuid
from datetime import date, datetime, time, timedelta
from typing import List, Optional

from adapters.base import BaseLibraryAdapter
from booking_engine import AvailabilitySlot, BookingResult, Library, RoomFilters, User


class MockAdapter(BaseLibraryAdapter):
    """Deterministic in-memory adapter for tests and local dev."""

    def __init__(self, library: Library, config: dict | None = None) -> None:
        super().__init__(library, config or {})
        self.always_confirm: bool = (config or {}).get("always_confirm", True)
        self.simulated_error: Optional[str] = (config or {}).get("simulated_error")

    def fetch_availability(self, target_date: date, filters: RoomFilters) -> List[AvailabilitySlot]:
        if self.simulated_error:
            raise RuntimeError(self.simulated_error)

        open_dt = datetime.combine(target_date, _parse_time(self.library.open_time))
        close_dt = datetime.combine(target_date, _parse_time(self.library.close_time))
        slots: List[AvailabilitySlot] = []

        _ROOM_META = {
            1: {"capacity": 2,  "accessible": True,  "floor": "1", "room_type": "study_room",    "amenities": ["Whiteboard", "Accessible"]},
            2: {"capacity": 4,  "accessible": False, "floor": "1", "room_type": "study_room",    "amenities": ["Whiteboard", "Display/TV"]},
            3: {"capacity": 6,  "accessible": False, "floor": "2", "room_type": "conference",    "amenities": ["Whiteboard", "Display/TV", "Video conferencing", "Phone"]},
            4: {"capacity": 8,  "accessible": False, "floor": "2", "room_type": "conference",    "amenities": ["Whiteboard", "Display/TV", "Video conferencing", "Phone"]},
        }

        for room_num in range(1, 5):
            meta = _ROOM_META[room_num]
            capacity = meta["capacity"]
            if capacity < filters.min_capacity:
                continue
            if filters.max_capacity and capacity > filters.max_capacity:
                continue
            if filters.accessible_only and not meta["accessible"]:
                continue
            if filters.amenities and not all(a in meta["amenities"] for a in filters.amenities):
                continue

            cursor = open_dt
            while cursor + timedelta(minutes=filters.duration_minutes) <= close_dt:
                end = cursor + timedelta(minutes=filters.duration_minutes)
                slots.append(AvailabilitySlot(
                    id=f"mock-{self.library.id}-r{room_num}-{cursor.strftime('%H%M')}",
                    room_id=f"{self.library.id}-room-{room_num}",
                    library_id=self.library.id,
                    start_time=cursor,
                    end_time=end,
                    duration_minutes=filters.duration_minutes,
                    is_available=True,
                    fetched_at=datetime.now(),
                    metadata=dict(meta),
                ))
                cursor += timedelta(hours=1)

        return slots

    def book_room(self, slot: AvailabilitySlot, user: User) -> BookingResult:
        if self.simulated_error:
            return BookingResult(
                success=False, message=self.simulated_error, error_code="MOCK_ERROR"
            )
        if self.always_confirm:
            code = f"MOCK-{uuid.uuid4().hex[:8].upper()}"
            return BookingResult(
                success=True, confirmation_code=code, booking_id=code,
                message="Mock booking confirmed",
            )
        return BookingResult(
            success=False, message="Mock: booking rejected", error_code="MOCK_REJECT"
        )

    def cancel_booking(self, confirmation_code: str) -> bool:
        return not bool(self.simulated_error)

    def fetch_hours(self, target_date: date) -> Optional[tuple[str, str]]:
        """Return static config hours, or None if target_date is a closed day."""
        day_abbr = target_date.strftime("%a")  # "Mon", "Tue", …
        if day_abbr not in self.library.open_days:
            return None
        return (self.library.open_time, self.library.close_time)


def _parse_time(hhmm: str) -> time:
    h, m = map(int, hhmm.split(":"))
    return time(hour=h, minute=m)
