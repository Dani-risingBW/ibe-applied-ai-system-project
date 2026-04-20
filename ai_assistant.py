"""AI-powered booking assistant — natural language search and conflict suggestions.

Uses Claude claude-haiku-4-5-20251001 with prompt caching for low latency and cost.
Set ANTHROPIC_API_KEY in your environment or in a .env file before use.
"""
from __future__ import annotations

import os
from datetime import date
from typing import Any, Dict, List, Optional, Tuple

from dotenv import load_dotenv

load_dotenv()

_client = None  # lazy-init Anthropic client


def _get_client():
    global _client
    if _client is None:
        import anthropic
        key = os.environ.get("ANTHROPIC_API_KEY")
        if not key:
            raise EnvironmentError(
                "ANTHROPIC_API_KEY is not set. "
                "Add it to your .env file (see .env.example)."
            )
        _client = anthropic.Anthropic(api_key=key)
    return _client


# ── Tool schema for structured filter extraction ───────────────────────────────

_PARSE_TOOL = {
    "name": "set_booking_filters",
    "description": (
        "Extract room booking preferences from a natural language request. "
        "Only populate fields that the user explicitly mentioned or clearly implied."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "date_offset_days": {
                "type": "integer",
                "description": (
                    "Days from today: 0=today, 1=tomorrow, 7=next week. "
                    "For named days (e.g. 'Monday') calculate the offset from today."
                ),
            },
            "duration_minutes": {
                "type": "integer",
                "description": "Booking duration in minutes. Common values: 30, 60, 90, 120, 150, 180.",
            },
            "min_capacity": {
                "type": "integer",
                "description": "Minimum number of seats/people needed.",
            },
            "amenities": {
                "type": "array",
                "items": {
                    "type": "string",
                    "enum": [
                        "Whiteboard",
                        "Display/TV",
                        "Video conferencing",
                        "Phone",
                        "Accessible",
                    ],
                },
                "description": "Required room amenities.",
            },
            "earliest_start_hour": {
                "type": "integer",
                "description": (
                    "Earliest acceptable start hour (0–23). "
                    "E.g. 'morning' → 8, 'afternoon' → 12, '2pm' → 14."
                ),
            },
        },
        "required": [],
    },
}

_SYSTEM_PROMPT = (
    "You are a university library room booking assistant. "
    "Your job is to parse natural language booking requests and extract structured "
    "filter parameters using the set_booking_filters tool. "
    "Only include fields the user explicitly mentioned or clearly implied. "
    "Today's date will be provided in each request."
)


# ── Public API ─────────────────────────────────────────────────────────────────

def parse_booking_request(
    user_input: str,
    today: Optional[date] = None,
) -> Tuple[Dict[str, Any], Optional[str]]:
    """Parse a natural language booking request into filter parameters.

    Returns (filters_dict, error_message).
    On success: (non-empty dict, None).
    On failure: ({}, human-readable error string).

    Uses prompt caching on the system prompt to reduce latency on repeated calls.
    """
    if not user_input.strip():
        return {}, "Enter a description first."

    today = today or date.today()
    today_str = today.strftime("%A, %B %d %Y")

    try:
        client = _get_client()
        response = client.messages.create(
            model="claude-haiku-4-5-20251001",
            max_tokens=256,
            system=[
                {
                    "type": "text",
                    "text": _SYSTEM_PROMPT,
                    "cache_control": {"type": "ephemeral"},
                }
            ],
            tools=[_PARSE_TOOL],
            tool_choice={"type": "tool", "name": "set_booking_filters"},
            messages=[
                {
                    "role": "user",
                    "content": f"Today is {today_str}.\n\nBooking request: {user_input}",
                }
            ],
        )
        for block in response.content:
            if hasattr(block, "type") and block.type == "tool_use":
                if block.name == "set_booking_filters":
                    return block.input or {}, None
        return {}, "No filters could be extracted from that description."
    except EnvironmentError as exc:
        return {}, str(exc)
    except Exception as exc:
        return {}, f"AI error: {exc}"


def suggest_alternative(
    conflict_messages: List[str],
    available_slots: List[Any],
    library_name: str,
) -> str:
    """Given conflict blockers and a list of available slots, suggest the best alternative.

    Returns a short 1–2 sentence friendly string, or "" on failure / no slots.

    Uses prompt caching on the system prompt.
    """
    if not available_slots:
        return ""

    slot_lines = "\n".join(
        f"- Room {s.room_id.split('-')[-1]}: "
        f"{s.start_time.strftime('%H:%M')}–{s.end_time.strftime('%H:%M')} "
        f"({s.duration_minutes} min)"
        for s in available_slots[:8]
    )
    conflict_text = "; ".join(conflict_messages)

    try:
        client = _get_client()
        response = client.messages.create(
            model="claude-haiku-4-5-20251001",
            max_tokens=120,
            system=[
                {
                    "type": "text",
                    "text": (
                        "You are a helpful university library booking assistant. "
                        "Given a booking conflict and a list of available alternatives, "
                        "recommend the best option in 1–2 friendly, concise sentences. "
                        "Do not repeat the conflict; focus on the suggestion."
                    ),
                    "cache_control": {"type": "ephemeral"},
                }
            ],
            messages=[
                {
                    "role": "user",
                    "content": (
                        f"Conflict: {conflict_text}\n\n"
                        f"Available slots at {library_name}:\n{slot_lines}\n\n"
                        "Please suggest the best alternative."
                    ),
                }
            ],
        )
        return response.content[0].text.strip()
    except Exception:
        return ""
