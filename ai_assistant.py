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

_PROMPT_HELP_SYSTEM = (
    "You are a university room-booking prompt coach. "
    "If the user's input is not clearly about booking a study room, return a short, kind message "
    "that explains what details help and provide 2 concrete example prompts. "
    "Keep it under 3 short lines."
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
    "You are a specialized university library room booking assistant. "
    "Your job is to parse natural language booking requests and extract structured "
    "filter parameters as JSON. Only include fields the user explicitly mentioned or clearly implied. "
    "Today's date will be provided in each request.\n\n"
    "SPECIALIZATION: Library Room Booking Domain\n"
    "Example interpretations:\n"
    "- 'tomorrow afternoon' → date_offset_days=1, earliest_start_hour=12\n"
    "- 'quiet room for 4' → min_capacity=4, no specific amenities unless mentioned\n"
    "- '90 minute meeting' → duration_minutes=90\n"
    "- 'room with projector and whiteboard' → amenities=['Display/TV', 'Whiteboard']\n"
    "- 'next Monday morning' → calculate date_offset to next Monday, earliest_start_hour=8\n"
    "Use these patterns to interpret vague or domain-specific language precisely."
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


def _extract_text_response(response: Any) -> str:
    """Best-effort text extraction across Gemini response shapes."""
    text = (getattr(response, "text", "") or "").strip()
    if text:
        return text

    parts: List[str] = []
    for cand in getattr(response, "candidates", []) or []:
        content = getattr(cand, "content", None)
        for part in getattr(content, "parts", []) or []:
            part_text = getattr(part, "text", None)
            if part_text:
                parts.append(part_text)
    return "\n".join(parts).strip()


def _looks_cut_off(text: str) -> bool:
    if not text:
        return True
    if len(text.split()) <= 2:
        return True
    return text[-1] not in ".!?"


# ── Agentic Reasoning Tracker ──────────────────────────────────────────────────

class _ReasoningStep:
    """Captures an intermediate reasoning step for explainability."""
    def __init__(self, step_name: str, input_data: Any, output_data: Any, reasoning: str):
        self.step_name = step_name
        self.input_data = input_data
        self.output_data = output_data
        self.reasoning = reasoning

    def __repr__(self):
        return f"[{self.step_name}] {self.reasoning}"


_current_reasoning_trace: List[_ReasoningStep] = []


def get_reasoning_trace() -> List[_ReasoningStep]:
    """Get the full reasoning trace from the last AI operation."""
    return _current_reasoning_trace.copy()


def clear_reasoning_trace():
    """Clear the reasoning trace."""
    global _current_reasoning_trace
    _current_reasoning_trace = []


def _record_step(step_name: str, input_data: Any, output_data: Any, reasoning: str):
    """Record a reasoning step."""
    _current_reasoning_trace.append(
        _ReasoningStep(step_name, input_data, output_data, reasoning)
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

    Agentic workflow:
    1. Normalize and validate input
    2. Prepare today's date context
    3. Call Gemini with structured prompt
    4. Extract and validate JSON response
    5. Log reasoning steps for explainability

    """
    clear_reasoning_trace()

    if not user_input.strip():
        _record_step("validation", user_input, None, "Input is empty; returning empty filters")
        return {}, "Enter a description first."

    today = today or date.today()
    today_str = today.strftime("%A, %B %d %Y")

    _record_step("input_preparation", user_input, today_str, f"Prepared context: today is {today_str}")

    try:
        client = _get_client()
        _record_step("client_init", None, "ready", "Gemini client initialized")

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
        _record_step("model_call", user_input, "response_received", "Gemini 2.5 Flash invoked with structured schema")

        raw_response = getattr(response, "text", "") or "{}"
        data = _parse_json_response(raw_response)

        _record_step("response_parsing", raw_response, data, f"JSON parsed successfully; extracted {len(data)} filters")

        return data, None
    except EnvironmentError as exc:
        _record_step("error", user_input, None, f"Environment error: {str(exc)}")
        return {}, str(exc)
    except (json.JSONDecodeError, ValueError) as exc:
        _record_step("error", user_input, None, f"Parse error: {str(exc)}")
        return {}, f"AI response could not be parsed: {exc}"
    except Exception as exc:
        _record_step("error", user_input, None, f"Unexpected error: {str(exc)}")
        return {}, f"AI error: {exc}"


def suggest_alternative(
    conflict_messages: List[str],
    available_slots: List[Any],
    library_name: str,
) -> str:
    """Given conflict blockers and a list of available slots, suggest the best alternative.

    Returns a short 1–2 sentence friendly string, or "" on failure / no slots.

    Agentic workflow:
    1. Validate input slots and conflicts
    2. Format slot information for readability
    3. Compose conflict context
    4. Call Gemini with specialization context
    5. Extract and validate suggestion response
    6. Handle truncation with automatic retry

    """
    clear_reasoning_trace()

    if not available_slots:
        _record_step("validation", available_slots, None, "No available slots provided")
        return ""

    _record_step("slot_gathering", f"{len(available_slots)} slots", available_slots[:3], f"Gathered {len(available_slots)} alternative slots")

    slot_lines = "\n".join(
        f"- Room {s.room_id.split('-')[-1]}: "
        f"{s.start_time.strftime('%H:%M')}–{s.end_time.strftime('%H:%M')} "
        f"({s.duration_minutes} min)"
        for s in available_slots[:8]
    )
    _record_step("slot_formatting", available_slots[:8], slot_lines, "Formatted top 8 slots for readability")

    conflict_text = "; ".join(conflict_messages)
    _record_step("conflict_analysis", conflict_messages, conflict_text, f"Identified {len(conflict_messages)} conflict reasons")

    prompt_body = (
        f"Conflict: {conflict_text}\n\n"
        f"Available slots at {library_name}:\n{slot_lines}\n\n"
        "Please suggest the best alternative in 1–2 concise sentences. "
        "Consider room quality, time of day, and duration when recommending."
    )

    try:
        client = _get_client()
        _record_step("client_init", None, "ready", "Gemini client initialized for suggestion")

        response = client.models.generate_content(
            model=_MODEL_NAME,
            contents=prompt_body,
            config={
                "temperature": 0.4,
                "max_output_tokens": 220,
                "system_instruction": _SUGGESTION_PROMPT,
            },
        )
        suggestion = _extract_text_response(response)
        _record_step("first_generation", prompt_body[:100], suggestion, f"Initial suggestion: {len(suggestion)} chars")

        if _looks_cut_off(suggestion):
            _record_step("truncation_detected", suggestion, None, f"Response appears truncated ({len(suggestion.split())} words); retrying with higher token limit")

            retry = client.models.generate_content(
                model=_MODEL_NAME,
                contents=prompt_body,
                config={
                    "temperature": 0.2,
                    "max_output_tokens": 320,
                    "system_instruction": _SUGGESTION_PROMPT + " Always finish with complete sentence punctuation.",
                },
            )
            retry_text = _extract_text_response(retry)
            _record_step("retry_generation", "max_tokens=320", retry_text, f"Retry succeeded: {len(retry_text)} chars")

            if retry_text:
                return retry_text

        return suggestion
    except Exception as e:
        _record_step("error", prompt_body[:50], None, f"Exception during suggestion: {str(e)}")
        return ""


def suggest_booking_prompt(user_input: str) -> str:
    """Generate a short coaching message for unhelpful/non-booking prompts."""
    if not user_input.strip():
        return (
            "Try describing your booking need with details like date, time, group size, duration, "
            "and amenities. Example: 'Room for 4 tomorrow at 2pm for 90 minutes with a whiteboard.'"
        )

    try:
        client = _get_client()
        response = client.models.generate_content(
            model=_MODEL_NAME,
            contents=(
                "User message:\n"
                f"{user_input}\n\n"
                "Write a concise coaching message to help them submit a useful booking prompt."
            ),
            config={
                "temperature": 0.3,
                "max_output_tokens": 120,
                "system_instruction": _PROMPT_HELP_SYSTEM,
            },
        )
        text = (getattr(response, "text", "") or "").strip()
        if text:
            return text
    except Exception:
        pass

    return (
        "That request does not look like a room-booking prompt yet. Include date, earliest time, "
        "duration, group size, and amenities. Example: 'Quiet room for 3 this Friday after 1pm, 2 hours, Display/TV.'"
    )


# ── Reasoning Debugging & Visualization ────────────────────────────────────────

def print_reasoning_trace(verbose: bool = False) -> str:
    """Generate a human-readable trace of reasoning steps.

    Args:
        verbose: if True, include input/output details; if False, just step names and reasoning.

    Returns:
        formatted string suitable for logging or display.
    """
    if not _current_reasoning_trace:
        return "[No reasoning trace available]"

    lines = ["Reasoning Trace:"]
    lines.append("-" * 60)

    for i, step in enumerate(_current_reasoning_trace, 1):
        lines.append(f"{i}. {step.step_name}")
        lines.append(f"   → {step.reasoning}")

        if verbose:
            if step.input_data is not None:
                input_str = str(step.input_data)[:80]
                lines.append(f"   in:  {input_str}")
            if step.output_data is not None:
                output_str = str(step.output_data)[:80]
                lines.append(f"   out: {output_str}")

    lines.append("-" * 60)
    return "\n".join(lines)


def get_reasoning_json() -> Dict[str, Any]:
    """Export reasoning trace as JSON-serializable dict for UI or logging."""
    return {
        "trace_length": len(_current_reasoning_trace),
        "steps": [
            {
                "step_name": step.step_name,
                "reasoning": step.reasoning,
            }
            for step in _current_reasoning_trace
        ],
    }
