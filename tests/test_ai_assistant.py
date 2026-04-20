"""Tests for ai_assistant.py — all Anthropic API calls are mocked."""
import sys
from datetime import date, datetime, timedelta
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

import ai_assistant
from booking_engine import AvailabilitySlot


# ── Helpers ────────────────────────────────────────────────────────────────────

def _tool_response(input_dict: dict):
    """Build a mock Anthropic response that returns a tool_use block."""
    block = MagicMock()
    block.type = "tool_use"
    block.name = "set_booking_filters"
    block.input = input_dict
    resp = MagicMock()
    resp.content = [block]
    return resp


def _text_response(text: str):
    block = MagicMock()
    block.text = text
    resp = MagicMock()
    resp.content = [block]
    return resp


def _slot(room_num: int = 1, hour: int = 10, duration: int = 60) -> AvailabilitySlot:
    start = datetime(2026, 4, 21, hour, 0)
    return AvailabilitySlot(
        id=f"s-r{room_num}-{hour}",
        room_id=f"lib-room-{room_num}",
        library_id="lib",
        start_time=start,
        end_time=start + timedelta(minutes=duration),
        duration_minutes=duration,
    )


# ── parse_booking_request ──────────────────────────────────────────────────────

class TestParseBookingRequest:

    def _mock_client(self, tool_input: dict):
        client = MagicMock()
        client.messages.create.return_value = _tool_response(tool_input)
        return client

    def test_returns_empty_dict_for_blank_input(self):
        filters, err = ai_assistant.parse_booking_request("   ")
        assert filters == {}
        assert err is not None

    def test_returns_date_offset_days(self):
        with patch.object(ai_assistant, "_get_client",
                          return_value=self._mock_client({"date_offset_days": 1})):
            filters, err = ai_assistant.parse_booking_request("tomorrow", date(2026, 4, 18))
        assert err is None
        assert filters["date_offset_days"] == 1

    def test_returns_duration_minutes(self):
        with patch.object(ai_assistant, "_get_client",
                          return_value=self._mock_client({"duration_minutes": 90})):
            filters, err = ai_assistant.parse_booking_request("90 minute room", date(2026, 4, 18))
        assert err is None
        assert filters["duration_minutes"] == 90

    def test_returns_min_capacity(self):
        with patch.object(ai_assistant, "_get_client",
                          return_value=self._mock_client({"min_capacity": 5})):
            filters, err = ai_assistant.parse_booking_request("room for 5 people", date(2026, 4, 18))
        assert err is None
        assert filters["min_capacity"] == 5

    def test_returns_amenities_list(self):
        with patch.object(ai_assistant, "_get_client",
                          return_value=self._mock_client({"amenities": ["Whiteboard", "Display/TV"]})):
            filters, err = ai_assistant.parse_booking_request("needs whiteboard and TV", date(2026, 4, 18))
        assert err is None
        assert "Whiteboard" in filters["amenities"]
        assert "Display/TV" in filters["amenities"]

    def test_returns_earliest_start_hour(self):
        with patch.object(ai_assistant, "_get_client",
                          return_value=self._mock_client({"earliest_start_hour": 14})):
            filters, err = ai_assistant.parse_booking_request("afternoon slot", date(2026, 4, 18))
        assert err is None
        assert filters["earliest_start_hour"] == 14

    def test_returns_multiple_fields_together(self):
        payload = {
            "date_offset_days": 3,
            "min_capacity": 4,
            "duration_minutes": 60,
            "amenities": ["Accessible"],
            "earliest_start_hour": 10,
        }
        with patch.object(ai_assistant, "_get_client",
                          return_value=self._mock_client(payload)):
            filters, err = ai_assistant.parse_booking_request(
                "accessible room for 4 people in 3 days at 10am for 1 hour",
                date(2026, 4, 18),
            )
        assert err is None
        assert filters == payload

    def test_returns_error_on_api_exception(self):
        client = MagicMock()
        client.messages.create.side_effect = Exception("network error")
        with patch.object(ai_assistant, "_get_client", return_value=client):
            filters, err = ai_assistant.parse_booking_request("a room", date(2026, 4, 18))
        assert filters == {}
        assert err is not None
        assert "network error" in err

    def test_returns_error_when_no_tool_block(self):
        text_block = MagicMock()
        text_block.type = "text"
        resp = MagicMock()
        resp.content = [text_block]
        client = MagicMock()
        client.messages.create.return_value = resp
        with patch.object(ai_assistant, "_get_client", return_value=client):
            filters, err = ai_assistant.parse_booking_request("a room", date(2026, 4, 18))
        assert filters == {}
        assert err is not None

    def test_uses_today_as_default_date(self):
        client = self._mock_client({})
        with patch.object(ai_assistant, "_get_client", return_value=client):
            ai_assistant.parse_booking_request("a room")
        call_kwargs = client.messages.create.call_args
        messages = call_kwargs.kwargs["messages"]
        assert str(date.today().year) in messages[0]["content"]

    def test_passes_today_string_in_message(self):
        client = self._mock_client({})
        with patch.object(ai_assistant, "_get_client", return_value=client):
            ai_assistant.parse_booking_request("a room", date(2026, 4, 20))
        messages = client.messages.create.call_args.kwargs["messages"]
        assert "2026" in messages[0]["content"]
        assert "April" in messages[0]["content"]

    def test_uses_haiku_model(self):
        client = self._mock_client({})
        with patch.object(ai_assistant, "_get_client", return_value=client):
            ai_assistant.parse_booking_request("a room", date(2026, 4, 18))
        model = client.messages.create.call_args.kwargs["model"]
        assert "haiku" in model

    def test_system_prompt_has_cache_control(self):
        client = self._mock_client({})
        with patch.object(ai_assistant, "_get_client", return_value=client):
            ai_assistant.parse_booking_request("a room", date(2026, 4, 18))
        system = client.messages.create.call_args.kwargs["system"]
        assert any(
            block.get("cache_control", {}).get("type") == "ephemeral"
            for block in system
        )

    def test_forces_tool_use(self):
        client = self._mock_client({})
        with patch.object(ai_assistant, "_get_client", return_value=client):
            ai_assistant.parse_booking_request("a room", date(2026, 4, 18))
        tool_choice = client.messages.create.call_args.kwargs["tool_choice"]
        assert tool_choice["type"] == "tool"
        assert tool_choice["name"] == "set_booking_filters"


# ── suggest_alternative ────────────────────────────────────────────────────────

class TestSuggestAlternative:

    def _mock_client(self, text: str):
        client = MagicMock()
        client.messages.create.return_value = _text_response(text)
        return client

    def test_returns_empty_string_with_no_slots(self):
        result = ai_assistant.suggest_alternative(["Room is booked"], [], "Founders Library")
        assert result == ""

    def test_returns_suggestion_text(self):
        slots = [_slot(1, 11), _slot(2, 12)]
        client = self._mock_client("Try Room 2 at 12:00 — it's available and has great capacity.")
        with patch.object(ai_assistant, "_get_client", return_value=client):
            result = ai_assistant.suggest_alternative(["Conflict reason"], slots, "Founders Library")
        assert "Room 2" in result or len(result) > 0

    def test_returns_empty_string_on_api_exception(self):
        client = MagicMock()
        client.messages.create.side_effect = Exception("timeout")
        slots = [_slot(1, 10)]
        with patch.object(ai_assistant, "_get_client", return_value=client):
            result = ai_assistant.suggest_alternative(["conflict"], slots, "Founders Library")
        assert result == ""

    def test_passes_library_name_in_message(self):
        slots = [_slot(1, 10)]
        client = self._mock_client("Try 10:00.")
        with patch.object(ai_assistant, "_get_client", return_value=client):
            ai_assistant.suggest_alternative(["conflict"], slots, "Law School Library")
        content = client.messages.create.call_args.kwargs["messages"][0]["content"]
        assert "Law School Library" in content

    def test_caps_slots_at_eight(self):
        slots = [_slot(i % 4 + 1, 8 + i) for i in range(12)]
        client = self._mock_client("Try an earlier slot.")
        with patch.object(ai_assistant, "_get_client", return_value=client):
            ai_assistant.suggest_alternative(["conflict"], slots, "Founders Library")
        content = client.messages.create.call_args.kwargs["messages"][0]["content"]
        assert content.count("Room") <= 8

    def test_system_prompt_has_cache_control(self):
        slots = [_slot(1, 10)]
        client = self._mock_client("Suggestion.")
        with patch.object(ai_assistant, "_get_client", return_value=client):
            ai_assistant.suggest_alternative(["conflict"], slots, "Lib")
        system = client.messages.create.call_args.kwargs["system"]
        assert any(
            block.get("cache_control", {}).get("type") == "ephemeral"
            for block in system
        )

    def test_strips_whitespace_from_response(self):
        slots = [_slot(1, 10)]
        client = self._mock_client("  Try Room 1.  \n")
        with patch.object(ai_assistant, "_get_client", return_value=client):
            result = ai_assistant.suggest_alternative(["c"], slots, "Lib")
        assert result == "Try Room 1."
