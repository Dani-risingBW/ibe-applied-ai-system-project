"""Google Calendar integration — auth, fetch, conflict-check, and booking sync."""
from __future__ import annotations

import glob
import os
from datetime import date, datetime, timezone
from typing import List, Optional

from google.auth.credentials import Credentials as GoogleAuthCredentials
from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build

from booking_engine import Booking, Library

SCOPES = ["https://www.googleapis.com/auth/calendar"]
TOKEN_PATH = "token.json"
_BOOKED_BY_TAG = "library-room-booking"


# ── Auth ───────────────────────────────────────────────────────────────────────

def _find_credentials_file() -> str:
    matches = glob.glob("client_secret_*.json")
    if not matches:
        raise FileNotFoundError(
            "No client_secret_*.json found. Download OAuth credentials from Google Cloud Console."
        )
    return matches[0]


def _local_tz_offset() -> str:
    """Return local UTC offset as '+HH:MM' / '-HH:MM' for RFC 3339 datetimes."""
    raw = datetime.now(timezone.utc).astimezone().strftime("%z")  # e.g. "-0500"
    return f"{raw[:3]}:{raw[3:]}" if len(raw) == 5 else "+00:00"


def authenticate():
    """Run OAuth 2.0 flow and return an authorized Google Calendar service object."""
    creds: Optional[GoogleAuthCredentials] = None
    if os.path.exists(TOKEN_PATH):
        creds = Credentials.from_authorized_user_file(TOKEN_PATH, SCOPES)
    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())
        else:
            flow = InstalledAppFlow.from_client_secrets_file(_find_credentials_file(), SCOPES)
            creds = flow.run_local_server(port=0)
        if isinstance(creds, Credentials):
            with open(TOKEN_PATH, "w") as fh:
                fh.write(creds.to_json())
    return build("calendar", "v3", credentials=creds)


# ── Fetch & parse ──────────────────────────────────────────────────────────────

def fetch_gcal_events(service, target_date: Optional[date] = None) -> List[dict]:
    """Fetch all Google Calendar events for target_date (defaults to today)."""
    target_date = target_date or date.today()
    time_min = datetime(target_date.year, target_date.month, target_date.day,
                        0, 0, 0, tzinfo=timezone.utc).isoformat()
    time_max = datetime(target_date.year, target_date.month, target_date.day,
                        23, 59, 59, tzinfo=timezone.utc).isoformat()
    result = (
        service.events()
        .list(
            calendarId="primary",
            timeMin=time_min,
            timeMax=time_max,
            singleEvents=True,
            orderBy="startTime",
        )
        .execute()
    )
    return result.get("items", [])


def parse_gcal_event(event: dict) -> Optional[dict]:
    """Parse a raw GCal event dict into a normalized dict."""
    start_raw = (event.get("start") or {}).get("dateTime") or (event.get("start") or {}).get("date")
    end_raw = (event.get("end") or {}).get("dateTime") or (event.get("end") or {}).get("date")
    if not start_raw:
        return None
    try:
        start_dt = datetime.fromisoformat(start_raw[:19])
        end_dt = datetime.fromisoformat(end_raw[:19]) if end_raw else start_dt
    except ValueError:
        return None
    return {
        "id": event.get("id"),
        "summary": event.get("summary", "Untitled"),
        "start": start_dt,
        "end": end_dt,
        "description": event.get("description"),
        "location": event.get("location"),
    }


# ── Booking → GCal event ───────────────────────────────────────────────────────

def booking_to_gcal_event(
    booking: Booking,
    library: Library,
    room_name: str = "",
) -> dict:
    """Convert a confirmed Booking into a Google Calendar event dict (RFC 3339)."""
    tz = _local_tz_offset()
    start_str = booking.start_time.isoformat() + tz
    end_str = booking.end_time.isoformat() + tz

    display_room = room_name or f"Room {booking.room_id.split('-')[-1]}"
    title = f"Study Room — {display_room} @ {library.name}"

    desc_lines = [
        f"Confirmation: {booking.confirmation_code or 'N/A'}",
        f"Purpose: {booking.purpose}",
        f"Library: {library.name}",
        f"Building: {library.building}",
    ]
    if booking.notes:
        desc_lines.append(f"Notes: {booking.notes}")
    desc_lines.append(f"Booked via: {_BOOKED_BY_TAG}")

    return {
        "summary": title,
        "location": f"{library.building}, {library.campus}",
        "description": "\n".join(desc_lines),
        "start": {"dateTime": start_str},
        "end": {"dateTime": end_str},
        "extendedProperties": {
            "private": {
                "booking_id": booking.id or "",
                "confirmation_code": booking.confirmation_code or "",
                "library_id": booking.library_id,
                "room_id": booking.room_id,
                "booked_by": _BOOKED_BY_TAG,
            }
        },
    }


def gcal_event_to_booking_dict(event: dict) -> Optional[dict]:
    """Re-parse a GCal event created by this system back into booking metadata.

    Returns None for events not created by the booking system.
    """
    props = (event.get("extendedProperties") or {}).get("private", {})
    if props.get("booked_by") != _BOOKED_BY_TAG:
        return None
    parsed = parse_gcal_event(event)
    if not parsed:
        return None
    return {
        **parsed,
        "booking_id": props.get("booking_id"),
        "confirmation_code": props.get("confirmation_code"),
        "library_id": props.get("library_id"),
        "room_id": props.get("room_id"),
    }


# ── Create & cancel ────────────────────────────────────────────────────────────

def create_gcal_event(service, event_dict: dict) -> dict:
    """Insert event_dict into the primary calendar. Returns the full created event dict."""
    return service.events().insert(calendarId="primary", body=event_dict).execute()


def cancel_gcal_event(service, event_id: str) -> bool:
    """Delete a GCal event by ID. Returns True on success, False on any error."""
    try:
        service.events().delete(calendarId="primary", eventId=event_id).execute()
        return True
    except Exception:
        return False


def sync_booking_to_gcal(
    service,
    booking: Booking,
    library: Library,
    room_name: str = "",
) -> Optional[str]:
    """Create a GCal event for a confirmed booking.

    Sets booking.gcal_event_id on success.
    Returns the event's htmlLink for display, or None on failure.
    """
    try:
        event_dict = booking_to_gcal_event(booking, library, room_name)
        created = create_gcal_event(service, event_dict)
        booking.gcal_event_id = created.get("id", "")
        return created.get("htmlLink")
    except Exception:
        return None
