from __future__ import annotations

import time as time_mod
from abc import ABC, abstractmethod
from datetime import date
from typing import Any, List, Optional, Tuple

from booking_engine import AvailabilitySlot, BookingResult, Library, RoomFilters, User


class BaseLibraryAdapter(ABC):

    def __init__(self, library: Library, config: dict) -> None:
        self.library = library
        self.config = config
        self.request_timeout: int = config.get("request_timeout", 10)
        self.max_retries: int = config.get("max_retries", 3)
        self.requests_per_minute: int = config.get("requests_per_minute", 30)
        self._request_times: List[float] = []

    @abstractmethod
    def fetch_availability(self, target_date: date, filters: RoomFilters) -> List[AvailabilitySlot]: ...

    @abstractmethod
    def book_room(self, slot: AvailabilitySlot, user: User) -> BookingResult: ...

    @abstractmethod
    def cancel_booking(self, confirmation_code: str) -> bool: ...

    @abstractmethod
    def fetch_hours(self, target_date: date) -> Optional[Tuple[str, str]]:
        """Return (open_time, close_time) as 'HH:MM' strings for target_date.

        Returns None if the library is closed on that date (holiday, closed day, etc.).
        Implementations should fall back to Library.open_time / close_time on error.
        """
        ...

    def _rate_limit(self) -> None:
        """Sliding-window rate limiter: max requests_per_minute per 60s window."""
        now = time_mod.monotonic()
        self._request_times = [t for t in self._request_times if now - t < 60]
        if len(self._request_times) >= self.requests_per_minute:
            wait = 60 - (now - self._request_times[0])
            if wait > 0:
                time_mod.sleep(wait)
        self._request_times.append(time_mod.monotonic())

    def _retry(self, fn: Any, *args: Any, **kwargs: Any) -> Any:
        """Call fn with exponential backoff, raising the last exception after max_retries."""
        last_exc: Exception = RuntimeError("No attempts made")
        for attempt in range(self.max_retries):
            try:
                return fn(*args, **kwargs)
            except Exception as exc:
                last_exc = exc
                time_mod.sleep(2 ** attempt)  # 1s, 2s, 4s
        raise last_exc
