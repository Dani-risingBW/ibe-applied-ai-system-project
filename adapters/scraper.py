from __future__ import annotations

import re
import time as time_mod
from datetime import date, datetime
from typing import Any, Dict, List, Optional, Tuple

import httpx
from bs4 import BeautifulSoup

from adapters.base import BaseLibraryAdapter
from booking_engine import AvailabilitySlot, BookingResult, Library, RoomFilters, User




class ScraperAdapter(BaseLibraryAdapter):
    """Generic HTML scraper adapter for library sites without a public API.

    Driven by CSS selectors in libraries.json — no code changes needed per site.
    Uses Selenium for JS-rendered pages when use_selenium: true in config.
    """

    def __init__(self, library: Library, config: dict) -> None:
        super().__init__(library, config)
        self.base_url = library.base_url.rstrip("/")
        self.selectors: Dict[str, str] = config.get("selectors", {})
        self.request_delay: float = config.get("request_delay_seconds", 1.5)
        self.use_selenium: bool = config.get("use_selenium", False)
        self._driver: Any = None

    # ── HTTP helpers ───────────────────────────────────────────────────────────

    def _get_html(self, url: str, params: Optional[Dict] = None) -> str:
        time_mod.sleep(self.request_delay)
        if self.use_selenium:
            return self._selenium_get(url)
        self._rate_limit()
        with httpx.Client(timeout=self.request_timeout) as client:
            resp = client.get(url, params=params)
            resp.raise_for_status()
            return resp.text

    def _selenium_get(self, url: str) -> str:
        if self._driver is None:
            from selenium import webdriver
            from selenium.webdriver.chrome.options import Options
            opts = Options()
            opts.add_argument("--headless")
            opts.add_argument("--no-sandbox")
            opts.add_argument("--disable-dev-shm-usage")
            self._driver = webdriver.Chrome(options=opts)
        self._driver.get(url)
        time_mod.sleep(2)  # wait for JS hydration
        return self._driver.page_source

    def __del__(self) -> None:
        if self._driver:
            try:
                self._driver.quit()
            except Exception:
                pass

    # ── Public interface ───────────────────────────────────────────────────────

    def fetch_availability(self, target_date: date, filters: RoomFilters) -> List[AvailabilitySlot]:
        def _fetch() -> List[AvailabilitySlot]:
            url = f"{self.base_url}/{target_date.isoformat()}"
            html = self._get_html(url)
            return self._parse_html(html, target_date, filters)

        return self._retry(_fetch)

    def book_room(self, slot: AvailabilitySlot, user: User) -> BookingResult:
        # Booking form submission is highly site-specific.
        # Configure form_selectors and form_url in libraries.json to enable.
        form_url = self.config.get("form_url")
        if not form_url:
            return BookingResult(
                success=False,
                message="Scraper booking requires 'form_url' and form selectors in libraries.json.",
                error_code="NOT_CONFIGURED",
            )
        try:
            return self._retry(lambda: self._submit_form(slot, user, form_url))
        except Exception as exc:
            return BookingResult(success=False, message=str(exc), error_code="SCRAPER_ERROR")

    def cancel_booking(self, confirmation_code: str) -> bool:
        return False  # requires site-specific implementation

    def fetch_hours(self, target_date: date) -> Optional[Tuple[str, str]]:
        """Return hours for target_date.

        If a 'hours_url' is in config, scrapes that page using the 'hours_row' selector.
        Otherwise falls back to static config. Returns None if library is closed that day.
        """
        day_abbr = target_date.strftime("%a")
        if day_abbr not in self.library.open_days:
            return None
        hours_url = self.config.get("hours_url")
        if hours_url:
            try:
                return self._scrape_hours(hours_url, target_date)
            except Exception:
                pass
        return (self.library.open_time, self.library.close_time)

    def _scrape_hours(self, url: str, target_date: date) -> Optional[Tuple[str, str]]:
        """Scrape a library hours page using the configured 'hours_row' selector."""
        html = self._get_html(url)
        soup = BeautifulSoup(html, "lxml")
        hours_sel = self.selectors.get("hours_row", "")
        if not hours_sel:
            return None
        row = soup.select_one(hours_sel)
        if not row:
            return None
        start_dt, end_dt = self._parse_time_range(row.get_text(strip=True), target_date)
        if start_dt and end_dt:
            return (start_dt.strftime("%H:%M"), end_dt.strftime("%H:%M"))
        return None

    # ── Parsing ────────────────────────────────────────────────────────────────

    def _parse_html(self, html: str, target_date: date, filters: RoomFilters) -> List[AvailabilitySlot]:
        soup = BeautifulSoup(html, "lxml")
        slot_sel = self.selectors.get("time_slot", ".available-slot")
        room_sel = self.selectors.get("room_name", ".room-name")
        time_sel = self.selectors.get("slot_time", ".slot-time")
        cap_sel = self.selectors.get("capacity", ".capacity")

        slots: List[AvailabilitySlot] = []
        for i, elem in enumerate(soup.select(slot_sel)):
            try:
                room_elem = elem.select_one(room_sel)
                room_name = room_elem.get_text(strip=True) if room_elem else f"Room {i + 1}"

                time_elem = elem.select_one(time_sel)
                time_text = time_elem.get_text(strip=True) if time_elem else ""
                start_dt, end_dt = self._parse_time_range(time_text, target_date)
                if start_dt is None or end_dt is None:
                    continue

                cap_elem = elem.select_one(cap_sel)
                capacity = int(cap_elem.get_text(strip=True)) if cap_elem else 1
                if capacity < filters.min_capacity:
                    continue
                if filters.max_capacity and capacity > filters.max_capacity:
                    continue

                duration = int((end_dt - start_dt).total_seconds() / 60)
                if duration < filters.duration_minutes:
                    continue

                slots.append(AvailabilitySlot(
                    id=f"scrape-{self.library.id}-{i}",
                    room_id=f"{self.library.id}-{room_name.lower().replace(' ', '-')}",
                    library_id=self.library.id,
                    start_time=start_dt,
                    end_time=end_dt,
                    duration_minutes=duration,
                    is_available=True,
                    fetched_at=datetime.now(),
                ))
            except Exception:
                continue

        return slots

    def _parse_time_range(
        self, text: str, base_date: date
    ) -> Tuple[Optional[datetime], Optional[datetime]]:
        """Parse 'HH:MM - HH:MM' or 'HH:MM–HH:MM' into a (start, end) datetime pair."""
        match = re.search(r"(\d{1,2}:\d{2})\s*[–\-]\s*(\d{1,2}:\d{2})", text)
        if not match:
            return None, None
        try:
            start = datetime.strptime(f"{base_date} {match.group(1)}", "%Y-%m-%d %H:%M")
            end = datetime.strptime(f"{base_date} {match.group(2)}", "%Y-%m-%d %H:%M")
            if end <= start:
                end = end.replace(hour=end.hour + 12)  # resolve AM/PM ambiguity
            return start, end
        except ValueError:
            return None, None

    def _submit_form(self, slot: AvailabilitySlot, user: User, form_url: str) -> BookingResult:
        """POST booking form with per-site field mappings from config."""
        field_map: Dict[str, str] = self.config.get("form_fields", {})
        payload = {
            field_map.get("email", "email"): user.email,
            field_map.get("name", "name"): user.name,
            field_map.get("room_id", "room_id"): slot.room_id,
            field_map.get("start", "start"): slot.start_time.isoformat(),
            field_map.get("end", "end"): slot.end_time.isoformat(),
        }
        with httpx.Client(timeout=self.request_timeout) as client:
            resp = client.post(form_url, data=payload)
            resp.raise_for_status()
        # Confirmation parsing is site-specific — return generic success
        return BookingResult(
            success=True,
            message="Form submitted. Check your email for confirmation.",
            raw_response={"status_code": resp.status_code},
        )
