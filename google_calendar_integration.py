# Google Calendar integration for PawPal+ — auth, fetch, convert, push, and conflict detection
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

from pawpal_system import Owner, Priority, Scheduler, ScheduledTask, Task

# Full calendar access needed for both reading events and creating new ones
SCOPES = ["https://www.googleapis.com/auth/calendar"]
# Saved token path — reused on every subsequent run to skip the browser flow
TOKEN_PATH = "token.json"

# Maps PawPal priority levels to Google Calendar's built-in color IDs
_COLOR_MAP = {
    Priority.HIGH: "11",    # Tomato (red)
    Priority.MEDIUM: "5",   # Banana (yellow)
    Priority.LOW: "2",      # Sage (green)
}


# Searches the project root for the downloaded OAuth2 client secret JSON
def _find_credentials_file() -> str:
    matches = glob.glob("client_secret_*.json")
    if not matches:
        raise FileNotFoundError(
            "No client_secret_*.json found. Download OAuth credentials from Google Cloud Console."
        )
    return matches[0]


def _local_tz_offset() -> str:
    """Return the local UTC offset as a '+HH:MM' / '-HH:MM' string for RFC 3339."""
    # strftime("%z") returns compact form like "-0500"; insert colon for RFC 3339
    raw = datetime.now(timezone.utc).astimezone().strftime("%z")  # e.g. "-0500"
    return f"{raw[:3]}:{raw[3:]}" if len(raw) == 5 else "+00:00"


def authenticate():
    """Run OAuth 2.0 flow and return an authorized Google Calendar service object."""
    # Load saved token to avoid re-running the browser flow on every run
    creds: Optional[GoogleAuthCredentials] = None
    if os.path.exists(TOKEN_PATH):
        creds = Credentials.from_authorized_user_file(TOKEN_PATH, SCOPES)
    if not creds or not creds.valid:
        # Refresh silently if the token is expired but a refresh_token is available
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())
        else:
            # First-time setup or revoked token — open browser for user consent
            flow = InstalledAppFlow.from_client_secrets_file(_find_credentials_file(), SCOPES)
            creds = flow.run_local_server(port=0)
        # Persist the new or refreshed token for next run
        if isinstance(creds, Credentials):
            with open(TOKEN_PATH, "w") as fh:
                fh.write(creds.to_json())
    return build("calendar", "v3", credentials=creds)


def fetch_gcal_events(service) -> List[dict]:
    """Fetch all Google Calendar events for today (midnight-to-midnight UTC)."""
    today = date.today()
    # Bound query to today only — singleEvents=True expands recurring entries
    time_min = datetime(today.year, today.month, today.day, 0, 0, 0, tzinfo=timezone.utc).isoformat()
    time_max = datetime(today.year, today.month, today.day, 23, 59, 59, tzinfo=timezone.utc).isoformat()
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


def gcal_event_to_task(event: dict) -> Optional[Task]:
    """Convert a Google Calendar event dict into a PawPal Task, or None if unparseable."""
    start = event.get("start", {})
    # Prefer dateTime (timed event) over date (all-day event)
    start_str = start.get("dateTime") or start.get("date")
    if not start_str:
        return None

    try:
        if "T" in start_str:
            # Strip timezone info so the datetime stays naive, matching PawPal's internal format
            scheduled_time = datetime.fromisoformat(start_str).replace(tzinfo=None)
        else:
            # All-day events have no time component — anchor to midnight
            d = date.fromisoformat(start_str)
            scheduled_time = datetime(d.year, d.month, d.day, 0, 0)
    except ValueError:
        return None

    # Default to 60 minutes if the event has no end time
    duration_minutes = 60
    end_str = (event.get("end") or {}).get("dateTime") or (event.get("end") or {}).get("date")
    if end_str:
        try:
            if "T" in end_str:
                end_dt = datetime.fromisoformat(end_str).replace(tzinfo=None)
            else:
                d = date.fromisoformat(end_str)
                end_dt = datetime(d.year, d.month, d.day, 0, 0)
            duration_minutes = max(1, int((end_dt - scheduled_time).total_seconds() / 60))
        except ValueError:
            pass

    return Task(
        id=None,
        title=event.get("summary", "Untitled Google Calendar Event"),
        duration_minutes=duration_minutes,
        priority=Priority.MEDIUM,
        notes=event.get("description"),
        scheduled_time=scheduled_time,
    )


def task_to_gcal_event(task: Task) -> dict:
    """Convert a PawPal Task into a Google Calendar event dict (RFC 3339 datetimes)."""
    if not task.scheduled_time:
        raise ValueError(f"Task '{task.title}' has no scheduled_time — cannot push to Google Calendar.")

    # Append local UTC offset so Google Calendar places the event in the correct timezone
    tz = _local_tz_offset()
    start_str = task.scheduled_time.isoformat() + tz
    end_str = task.estimate_end(task.scheduled_time).isoformat() + tz

    event: dict = {
        "summary": task.title,
        "start": {"dateTime": start_str},
        "end": {"dateTime": end_str},
        "colorId": _COLOR_MAP.get(task.priority, "5"),
    }

    # Merge notes and description into a single GCal description field
    description_parts = [p for p in [task.notes, task.description] if p]
    if description_parts:
        event["description"] = "\n".join(description_parts)

    # Translate PawPal recurrence strings to iCalendar RRULE format
    if task.recurrence == "daily":
        event["recurrence"] = ["RRULE:FREQ=DAILY"]
    elif task.recurrence == "weekly":
        event["recurrence"] = ["RRULE:FREQ=WEEKLY"]

    return event


def push_task_to_gcal(service, task: Task) -> dict:
    """Insert a PawPal Task as an event in the primary Google Calendar. Returns the created event."""
    return service.events().insert(calendarId="primary", body=task_to_gcal_event(task)).execute()


def check_gcal_conflicts(
    service,
    scheduled_tasks: List[ScheduledTask],
    owner: Optional[Owner] = None,
) -> List[str]:
    """Fetch today's GCal events and return conflict warnings against PawPal scheduled tasks."""
    gcal_events = fetch_gcal_events(service)
    # Convert GCal events to ScheduledTask objects so they feed into detect_conflicts
    gcal_scheduled: List[ScheduledTask] = []
    for event in gcal_events:
        task = gcal_event_to_task(event)
        if task and task.scheduled_time:
            gcal_scheduled.append(
                ScheduledTask(
                    id=None,
                    task=task,
                    start_time=task.scheduled_time,
                    end_time=task.estimate_end(task.scheduled_time),
                    reason="Google Calendar event",
                )
            )

    # Reuse Scheduler.detect_conflicts — no duplicate conflict logic needed
    return Scheduler().detect_conflicts(list(scheduled_tasks) + gcal_scheduled, owner=owner)
