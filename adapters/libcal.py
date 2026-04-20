from __future__ import annotations

import os
import re
import time as time_mod
from datetime import date, datetime
from typing import Any, Dict, List, Optional, Tuple

import httpx

from adapters.base import BaseLibraryAdapter
from booking_engine import AvailabilitySlot, BookingResult, Library, RoomFilters, User


class LibCalAdapter(BaseLibraryAdapter):
    """Springshare LibCal REST API adapter (v1.1).

    Used by hundreds of university libraries. Requires OAuth2 client credentials
    set via env vars (see .env.example).

    API docs: https://springshare.com/libcal/
    """

    API_VERSION = "1.1"

    def __init__(self, library: Library, config: dict) -> None:
        super().__init__(library, config)
        self.base_url = library.base_url.rstrip("/")
        self.client_id = _resolve_env(config.get("client_id", ""))
        self.client_secret = _resolve_env(config.get("client_secret", ""))
        self._token: Optional[str] = None
        self._token_expiry: Optional[float] = None

    # ── Auth ───────────────────────────────────────────────────────────────────

    def _get_token(self) -> str:
        now = time_mod.time()
        if self._token and self._token_expiry and now < self._token_expiry - 30:
            return self._token
        self._rate_limit()
        with httpx.Client(timeout=self.request_timeout) as client:
            resp = client.post(
                f"{self.base_url}/{self.API_VERSION}/oauth/token",
                data={
                    "grant_type": "client_credentials",
                    "client_id": self.client_id,
                    "client_secret": self.client_secret,
                },
            )
            resp.raise_for_status()
            data = resp.json()
        self._token = data["access_token"]
        self._token_expiry = now + data.get("expires_in", 3600)
        return self._token

    def _get(self, path: str, params: Optional[Dict[str, Any]] = None) -> Any:
        self._rate_limit()
        token = self._get_token()
        with httpx.Client(timeout=self.request_timeout) as client:
            resp = client.get(
                f"{self.base_url}/{self.API_VERSION}{path}",
                params=params,
                headers={"Authorization": f"Bearer {token}"},
            )
            resp.raise_for_status()
            return resp.json()

    # ── Public interface ───────────────────────────────────────────────────────

    def fetch_availability(self, target_date: date, filters: RoomFilters) -> List[AvailabilitySlot]:
        def _fetch() -> List[AvailabilitySlot]:
            locations = self._get("/space/locations")
            slots: List[AvailabilitySlot] = []
            for loc in locations:
                lid = loc.get("lid")
                if not lid:
                    continue
                raw = self._get(f"/space/slots/{lid}", params={"date": target_date.isoformat()})
                slots.extend(self._parse_slots(raw, filters))
            return slots

        return self._retry(_fetch)

    def book_room(self, slot: AvailabilitySlot, user: User) -> BookingResult:
        def _book() -> BookingResult:
            token = self._get_token()
            self._rate_limit()
            name_parts = user.name.split(maxsplit=1)
            fname = name_parts[0]
            lname = name_parts[1] if len(name_parts) > 1 else ""
            with httpx.Client(timeout=self.request_timeout) as client:
                resp = client.post(
                    f"{self.base_url}/{self.API_VERSION}/space/reserve",
                    headers={"Authorization": f"Bearer {token}"},
                    json={
                        "start": slot.start_time.isoformat(),
                        "fname": fname,
                        "lname": lname,
                        "email": user.email,
                        "bookings": [{"id": slot.room_id, "seat_id": None}],
                    },
                )
                resp.raise_for_status()
                data = resp.json()
            if data.get("booking_id"):
                code = str(data["booking_id"])
                return BookingResult(
                    success=True, confirmation_code=code, booking_id=code,
                    message="Booking confirmed", raw_response=data,
                )
            return BookingResult(
                success=False, message=data.get("error", "Unknown error"),
                error_code="LIBCAL_REJECT", raw_response=data,
            )

        try:
            return self._retry(_book)
        except Exception as exc:
            return BookingResult(success=False, message=str(exc), error_code="NETWORK_ERROR")

    def cancel_booking(self, confirmation_code: str) -> bool:
        def _cancel() -> bool:
            token = self._get_token()
            self._rate_limit()
            with httpx.Client(timeout=self.request_timeout) as client:
                resp = client.post(
                    f"{self.base_url}/{self.API_VERSION}/space/cancel/{confirmation_code}",
                    headers={"Authorization": f"Bearer {token}"},
                )
                resp.raise_for_status()
                return bool(resp.json().get("cancelled", False))

        try:
            return self._retry(_cancel)
        except Exception:
            return False

    def fetch_hours(self, target_date: date) -> Optional[Tuple[str, str]]:
        """Query LibCal /hours/{lid} for live hours on target_date.

        Falls back to static config on any error so conflict detection always has data.
        """
        def _fetch() -> Optional[Tuple[str, str]]:
            locations = self._get("/space/locations")
            if not locations:
                return (self.library.open_time, self.library.close_time)
            lid = locations[0].get("lid")
            date_str = target_date.isoformat()
            raw = self._get(f"/hours/{lid}", params={"from": date_str, "to": date_str})
            for loc in (raw if isinstance(raw, list) else [raw]):
                day_info = loc.get("dates", {}).get(date_str, {})
                if day_info.get("status") == "closed":
                    return None
                hours_list = day_info.get("hours", [])
                if hours_list:
                    return (
                        _normalize_hhmm(hours_list[0].get("from", self.library.open_time)),
                        _normalize_hhmm(hours_list[0].get("to", self.library.close_time)),
                    )
            return (self.library.open_time, self.library.close_time)

        try:
            return self._retry(_fetch)
        except Exception:
            return (self.library.open_time, self.library.close_time)

    # ── Parsing ────────────────────────────────────────────────────────────────

    def _parse_slots(self, raw: Any, filters: RoomFilters) -> List[AvailabilitySlot]:
        items = raw if isinstance(raw, list) else raw.get("slots", [])
        slots: List[AvailabilitySlot] = []
        for item in items:
            if item.get("className") == "s-lc-eq-checkout":
                continue  # equipment checkout, not a room
            try:
                start = datetime.fromisoformat(item["start"])
                end = datetime.fromisoformat(item["end"])
            except (KeyError, ValueError):
                continue
            capacity = item.get("capacity", 1)
            if capacity < filters.min_capacity:
                continue
            if filters.max_capacity and capacity > filters.max_capacity:
                continue
            duration = int((end - start).total_seconds() / 60)
            if duration < filters.duration_minutes:
                continue
            slots.append(AvailabilitySlot(
                id=str(item.get("itemId", "")),
                room_id=str(item.get("itemId", "")),
                library_id=self.library.id,
                start_time=start,
                end_time=end,
                duration_minutes=duration,
                is_available=True,
                fetched_at=datetime.now(),
            ))
        return slots


def _resolve_env(value: str) -> str:
    """Resolve 'env:VAR_NAME' strings to the actual environment variable."""
    if value.startswith("env:"):
        return os.environ.get(value[4:], "")
    return value


def _normalize_hhmm(t: str) -> str:
    """Convert LibCal time strings like '8:00am' or '10:00pm' to 'HH:MM'."""
    m = re.match(r"(\d{1,2}):(\d{2})\s*(am|pm)?", t.strip().lower())
    if not m:
        return t
    h, mi, period = int(m.group(1)), int(m.group(2)), m.group(3)
    if period == "pm" and h != 12:
        h += 12
    elif period == "am" and h == 12:
        h = 0
    return f"{h:02d}:{mi:02d}"
