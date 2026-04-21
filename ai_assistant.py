"""AI-powered booking assistant — natural language search and conflict suggestions.

Uses Gemini 2.5 Flash for both structured filter extraction and short suggestion
generation. Set GEMINI_API_KEY or GOOGLE_API_KEY in your environment or in a
.env file before use.
"""
from __future__ import annotations

import json
import importlib
import os
from datetime import date
from typing import Any, Dict, List, Optional, Tuple

from dotenv import load_dotenv

load_dotenv()

_client = None  # lazy-init Gemini client

_MODEL_NAME = "gemini-2.5-flash"

_FILTER_SCHEMA = {
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
    "additionalProperties": False,
}

_SUGGESTION_PROMPT = (
    "You are a helpful university library booking assistant. "
    "Given a booking conflict and a list of available alternatives, recommend the best option "
    "in 1–2 friendly, concise sentences. Do not repeat the conflict; focus on the suggestion."
)


def _get_client():
    global _client
    if _client is None:
        genai = importlib.import_module("google.genai")
        key = os.environ.get("GEMINI_API_KEY") or os.environ.get("GOOGLE_API_KEY")
        if not key:
            raise EnvironmentError(
                "GEMINI_API_KEY is not set. "
                "Add it to your .env file (see .env.example)."
            )
        _client = genai.Client(api_key=key)
    return _client


_SYSTEM_PROMPT = (
    "You are a university library room booking assistant. "
    "Your job is to parse natural language booking requests and extract structured "
    "filter parameters as JSON. Only include fields the user explicitly mentioned or clearly implied. "
    "Today's date will be provided in each request."
)


def _parse_json_response(text: str) -> Dict[str, Any]:
    cleaned = text.strip()
    if cleaned.startswith("```"):
        cleaned = cleaned.strip("`")
        cleaned = cleaned.replace("json\n", "", 1) if cleaned.startswith("json\n") else cleaned
    data = json.loads(cleaned)
    if not isinstance(data, dict):
        raise ValueError("Model response was not a JSON object.")
    return data


# ── Public API ─────────────────────────────────────────────────────────────────

def parse_booking_request(
    user_input: str,
    today: Optional[date] = None,
) -> Tuple[Dict[str, Any], Optional[str]]:
    """Parse a natural language booking request into filter parameters.

    Returns (filters_dict, error_message).
    On success: (non-empty dict, None).
    On failure: ({}, human-readable error string).

    """
    if not user_input.strip():
        return {}, "Enter a description first."

    today = today or date.today()
    today_str = today.strftime("%A, %B %d %Y")

    try:
        client = _get_client()
        response = client.models.generate_content(
            model=_MODEL_NAME,
            contents=(
                f"Today is {today_str}.\n\n"
                f"Booking request: {user_input}\n\n"
                "Return only valid JSON matching the provided schema."
            ),
            config={
                "temperature": 0,
                "max_output_tokens": 256,
                "system_instruction": _SYSTEM_PROMPT,
                "response_mime_type": "application/json",
                "response_json_schema": _FILTER_SCHEMA,
            },
        )
        data = _parse_json_response(getattr(response, "text", "") or "{}")
        return data, None
    except EnvironmentError as exc:
        return {}, str(exc)
    except (json.JSONDecodeError, ValueError) as exc:
        return {}, f"AI response could not be parsed: {exc}"
    except Exception as exc:
        return {}, f"AI error: {exc}"


def suggest_alternative(
    conflict_messages: List[str],
    available_slots: List[Any],
    library_name: str,
) -> str:
    """Given conflict blockers and a list of available slots, suggest the best alternative.

    Returns a short 1–2 sentence friendly string, or "" on failure / no slots.

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
        response = client.models.generate_content(
            model=_MODEL_NAME,
            contents=(
                f"Conflict: {conflict_text}\n\n"
                f"Available slots at {library_name}:\n{slot_lines}\n\n"
                "Please suggest the best alternative in 1–2 concise sentences."
            ),
            config={
                "temperature": 0.4,
                "max_output_tokens": 120,
                "system_instruction": _SUGGESTION_PROMPT,
            },
        )
        return (getattr(response, "text", "") or "").strip()
    except Exception:
        return ""
