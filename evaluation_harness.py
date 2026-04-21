"""Evaluation harness for AI assistant quality assessment.

Runs predefined booking prompts through parse and suggestion logic,
scores outputs against expected results, and reports pass/fail summary.
"""
import os
from datetime import datetime, timedelta
from typing import Dict, List, Tuple
from ai_assistant import parse_booking_request, suggest_alternative
from booking_engine import Booking, Room, AvailabilitySlot


# ── Test Cases ──────────────────────────────────────────────────────────────

TEST_PARSE_CASES = [
    {
        "name": "Natural language with capacity and duration",
        "prompt": "quiet room for 4 tomorrow afternoon with a whiteboard for 90 minutes",
        "expected_keys": ["duration_minutes", "min_capacity", "amenities"],
        "expected_values": {
            "min_capacity": 4,
            "duration_minutes": 90,
        },
    },
    {
        "name": "Simple two-word request",
        "prompt": "study room tomorrow",
        "expected_keys": ["date_offset_days"],
        "expected_values": None,  # Just check that something was extracted
    },
    {
        "name": "Specific time preference",
        "prompt": "meeting room at 2pm for 1 hour",
        "expected_keys": ["duration_minutes", "earliest_start_hour"],
        "expected_values": {"duration_minutes": 60},
    },
    {
        "name": "Amenities request",
        "prompt": "room with projector and whiteboard",
        "expected_keys": ["amenities"],
        "expected_values": None,
    },
]

TEST_SUGGESTION_CASES = [
    {
        "name": "Suggest with multiple available slots",
        "available_slots": [
            AvailabilitySlot(
                id="slot1",
                room_id="r1",
                library_id="lib1",
                start_time=datetime.now() + timedelta(hours=1),
                end_time=datetime.now() + timedelta(hours=2),
                duration_minutes=60,
                is_available=True,
            ),
            AvailabilitySlot(
                id="slot2",
                room_id="r2",
                library_id="lib1",
                start_time=datetime.now() + timedelta(hours=2),
                end_time=datetime.now() + timedelta(hours=3),
                duration_minutes=60,
                is_available=True,
            ),
        ],
        "library_name": "Founders Library",
        "conflict_messages": ["Room double-book detected"],
        "expected_contains": ["alternative", "room", "time"],
    },
]


# ── Scoring ─────────────────────────────────────────────────────────────────

def score_parse(result: Dict, expected_keys: List[str], expected_values: Dict = None) -> Tuple[bool, str]:
    """Score a parse result against expected keys and values."""
    if not result:
        return False, "Parse returned empty result"

    # Check expected keys are present
    missing_keys = [k for k in expected_keys if k not in result]
    if missing_keys:
        return False, f"Missing keys: {missing_keys}"

    # Check expected values if provided
    if expected_values:
        for key, expected_val in expected_values.items():
            actual_val = result.get(key)
            if actual_val != expected_val:
                return False, f"Key '{key}': expected {expected_val}, got {actual_val}"

    return True, "Pass"


def score_suggestion(result: str, expected_contains: List[str]) -> Tuple[bool, str]:
    """Score a suggestion result against expected content."""
    if not result or not isinstance(result, str):
        return False, "Suggestion returned empty or non-string result"

    result_lower = result.lower()
    missing_words = [w for w in expected_contains if w.lower() not in result_lower]

    if missing_words:
        return False, f"Missing keywords: {missing_words}"

    # Check that suggestion is not too short (truncation guard)
    word_count = len(result_lower.split())
    if word_count < 10:
        return False, f"Suggestion too short ({word_count} words), likely truncated"

    return True, "Pass"


# ── Harness ─────────────────────────────────────────────────────────────────

def evaluate_parse_quality() -> Dict:
    """Run parse test cases and report results."""
    results = {
        "total": len(TEST_PARSE_CASES),
        "passed": 0,
        "failed": 0,
        "cases": [],
    }

    print("\n" + "=" * 70)
    print("PARSE QUALITY EVALUATION")
    print("=" * 70)

    for case in TEST_PARSE_CASES:
        print(f"\n[{case['name']}]")
        print(f"  Prompt: {case['prompt']}")

        result, error = parse_booking_request(case["prompt"])
        passed, reason = score_parse(result, case["expected_keys"], case.get("expected_values"))

        if passed:
            results["passed"] += 1
            status = "✓ PASS"
        else:
            results["failed"] += 1
            status = "✗ FAIL"

        results["cases"].append({
            "name": case["name"],
            "passed": passed,
            "reason": reason,
        })

        print(f"  {status}: {reason}")
        if result:
            print(f"  Extracted: {result}")
        if error:
            print(f"  Error: {error}")

    return results


def evaluate_suggestion_quality() -> Dict:
    """Run suggestion test cases and report results."""
    results = {
        "total": len(TEST_SUGGESTION_CASES),
        "passed": 0,
        "failed": 0,
        "cases": [],
    }

    print("\n" + "=" * 70)
    print("SUGGESTION QUALITY EVALUATION")
    print("=" * 70)

    for case in TEST_SUGGESTION_CASES:
        print(f"\n[{case['name']}]")
        print(f"  Available slots: {len(case['available_slots'])}")
        print(f"  Library: {case['library_name']}")
        print(f"  Conflict: {case['conflict_messages']}")

        result = suggest_alternative(
            conflict_messages=case["conflict_messages"],
            available_slots=case["available_slots"],
            library_name=case["library_name"],
        )

        passed, reason = score_suggestion(result, case["expected_contains"])

        if passed:
            results["passed"] += 1
            status = "✓ PASS"
        else:
            results["failed"] += 1
            status = "✗ FAIL"

        results["cases"].append({
            "name": case["name"],
            "passed": passed,
            "reason": reason,
        })

        print(f"  {status}: {reason}")
        if result:
            print(f"  Suggestion: {result[:150]}..." if len(result) > 150 else f"  Suggestion: {result}")

    return results


def generate_report(parse_results: Dict, suggestion_results: Dict) -> str:
    """Generate a final evaluation report."""
    total_passed = parse_results["passed"] + suggestion_results["passed"]
    total_cases = parse_results["total"] + suggestion_results["total"]
    pass_rate = (total_passed / total_cases * 100) if total_cases > 0 else 0

    report = f"""
╔════════════════════════════════════════════════════════════════════╗
║                   AI ASSISTANT EVALUATION REPORT                   ║
╚════════════════════════════════════════════════════════════════════╝

SUMMARY
───────
Total Cases:     {total_cases}
Passed:          {total_passed}
Failed:          {total_cases - total_passed}
Pass Rate:       {pass_rate:.1f}%

PARSE EVALUATION
────────────────
Cases:           {parse_results['total']}
Passed:          {parse_results['passed']}
Failed:          {parse_results['failed']}

SUGGESTION EVALUATION
─────────────────────
Cases:           {suggestion_results['total']}
Passed:          {suggestion_results['passed']}
Failed:          {suggestion_results['failed']}

DETAILS
───────
"""

    report += "\nParse Cases:\n"
    for case in parse_results["cases"]:
        status = "✓" if case["passed"] else "✗"
        report += f"  {status} {case['name']}: {case['reason']}\n"

    report += "\nSuggestion Cases:\n"
    for case in suggestion_results["cases"]:
        status = "✓" if case["passed"] else "✗"
        report += f"  {status} {case['name']}: {case['reason']}\n"

    return report


def main():
    """Run full evaluation harness."""
    print("\nStarting AI Assistant Evaluation Harness...")
    print(f"Timestamp: {datetime.now().isoformat()}")

    parse_results = evaluate_parse_quality()
    suggestion_results = evaluate_suggestion_quality()

    report = generate_report(parse_results, suggestion_results)
    print(report)

    # Optionally save report to file
    report_path = "evaluation_report.txt"
    with open(report_path, "w", encoding="utf-8") as f:
        f.write(report)
    print(f"\nReport saved to: {report_path}")

    return {
        "parse": parse_results,
        "suggestion": suggestion_results,
    }


if __name__ == "__main__":
    main()
