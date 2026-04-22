# Library Room Booking System

A full-stack university study-room booking application built with Streamlit.  
Students search for available rooms across multiple campus libraries, check Google Calendar conflicts, and confirm reservations — with an AI assistant that understands plain-English requests.

---

## Base Project and Original Scope

**Original Assignment:** You are building PawPal+, a Streamlit app that helps a pet owner plan care tasks for their pet.

Scenario: A busy pet owner needs help staying consistent with pet care. They want an assistant that can:
- Track pet care tasks (walks, feeding, meds, enrichment, grooming, etc.)
- Consider constraints (time available, priority, owner preferences)
- Produce a daily plan and explain why it chose that plan

The final app should let a user enter basic owner + pet info, add/edit tasks (duration + priority), generate a daily schedule/plan based on constraints and priorities, and display the plan clearly with reasoning.

---

**What We Actually Built:** Instead of PawPal+, we pivoted to build a **Library Room Booking System** with AI enhancement—a full-stack university study-room booking application. This extends the library room booking workflow with:

Original capabilities:
- Fetch availability through adapter-based sources (mock, scraper, LibCal)
- Apply core booking constraints (hours, overlap checks, booking limits)
- Confirm or cancel reservations
- Persist bookings in SQLite and optionally sync with Google Calendar

The AI features in this repository are an extension on top of that booking workflow, not a separate demo.

---

## Features

| Feature | Details |
|---|---|
| Multi-library support | LibCal API, web scraper, and mock adapters |
| Real-time availability | Fetches live slots filtered by date, duration, seats, and amenities |
| Conflict detection | Checks room double-booking, operating hours, daily limits, and Google Calendar overlaps |
| Google Calendar sync | OAuth 2.0 — bookings auto-added; cancellations auto-removed |
| AI natural-language search | Describe what you need in plain English; Gemini 2.5 Flash fills the form |
| AI conflict suggestions | When a slot is blocked, Gemini 2.5 Flash recommends the best alternative |
| Persistent storage | SQLite backing store — bookings survive app restarts |
| Dry-run mode | Validate a booking without submitting |

---

## Substantial AI Feature Added

The primary AI extension is a **specialized structured-prompting workflow** powered by Gemini 2.5 Flash:

1. **Natural-language to structured filters**
- User enters free text (for example: "quiet room for 4 tomorrow afternoon with a whiteboard").
- AI converts that request into strict booking filters used directly by the search UI.

2. **Conflict-aware alternative suggestion**
- When a selected slot is blocked, AI proposes a better alternative based on available slots.

3. **Prompt-quality guardrail assistant**
- If a user prompt is not booking-relevant, AI returns a coaching prompt with examples so users can recover quickly.

Integration proof:
- AI parse and suggestion are wired into the live Streamlit flow in app.py.
- AI helpers are implemented in ai_assistant.py and used by the booking UI and conflict flow.

Meaningful behavior change:
- Users can search by intent rather than manual form-only input.
- Blocked bookings now provide actionable alternatives rather than a dead end.
- Low-quality prompts are redirected into useful booking prompts.

---

## Quick Start

### Prerequisites

- Python 3.11 or later
- A Google Cloud project with the Calendar API enabled and an OAuth 2.0 client secret downloaded as `client_secret_*.json`
- A Gemini API key (for AI Search — optional, the rest of the app works without it)

### 1. Clone and create a virtual environment

```bash
git clone <repo-url>
cd ibe-applied-ai-system-project
python -m venv .venv
# macOS / Linux
source .venv/bin/activate
# Windows
.venv\Scripts\activate
```

### 2. Install dependencies

```bash
pip install -r requirements.txt
```

### 3. Configure environment variables

```bash
cp .env.example .env
```

Edit `.env` and set at minimum:

```
GEMINI_API_KEY=...   # required for AI Search
```

LibCal credentials are only needed when `adapter: "libcal"` is used in `libraries.json`.

### 4. Configure libraries

Edit `libraries.json` to match your campus.  
Three mock libraries are pre-configured for local development — no changes needed to try the app.  
Switch `"adapter": "mock"` to `"libcal"` or `"scraper"` for live data.

### 5. Run the app

```bash
streamlit run app.py
```

Open [http://localhost:8501](http://localhost:8501) in your browser.

---

## Running with Docker

```bash
# Build and start
docker compose up --build

# Stop
docker compose down
```

The app is available at [http://localhost:8501](http://localhost:8501).  
`bookings.db` is mounted as a volume so data persists across container restarts.

---

## Running Tests

```bash
python -m pytest          # all 195 tests
python -m pytest -v       # verbose output
python -m pytest tests/test_booking_engine.py   # specific module
```

---

## End-to-End Demonstration

Use the Streamlit UI to run the full workflow end-to-end:

1. Sign in with name/email in the app.
2. Enter a natural-language request in "Describe what you need (AI Search)" and click Parse.
3. Run Search Rooms, select a slot, review conflicts, then click Confirm Booking.
4. Check "My Bookings" in the sidebar and optionally cancel the booking.

Example inputs and expected behavior:

1. Input:
- "quiet room for 4 tomorrow afternoon with a whiteboard for 90 minutes"
Expected:
- AI pre-fills date offset, capacity, amenities, and duration filters.
- Search returns matching slots and user can complete booking.

2. Input:
- "book me anything"
Expected:
- AI prompt-coaching message appears, explaining how to provide a better booking prompt.

3. Input (after choosing a conflicting slot):
- Select a slot that overlaps an existing reservation or violates a guardrail.
Expected:
- Conflict blocker is shown.
- AI Suggestion provides an alternate room/time recommendation.

---

## Loom Walkthrough

Watch the full project walkthrough here:

- Loom video: https://www.loom.com/share/08c12b43544045c6834ebd9c4efdf545

Suggested walkthrough coverage:
- Base project and original scope
- End-to-end demo flow in Streamlit
- AI parse and conflict-suggestion features
- Guardrails and cancellation behavior
- Stretch features (agentic trace, specialization, evaluation harness)

---

## Reliability and Guardrails

This system includes functional reliability mechanisms in production flow:

- Input guardrail for non-booking prompts:
	- AI coaching message helps the user rewrite prompts into actionable booking requests.
- Conflict and policy guardrails:
	- Room double-book prevention
	- Operating-hours checks
	- Max duration checks
	- Max days-ahead checks
	- User daily booking-limit checks
	- Past-date/time booking block
- Calendar overlap warning:
	- Warns when booking overlaps Google Calendar events.

Behavior examples:

1. Past time selected:
- Result: blocked with "Cannot book a slot that has already started or passed..."

2. User prompt unrelated to booking:
- Result: AI returns a short coaching message plus example prompts.

3. Slot violates library hours:
- Result: blocked with open/close time explanation and no booking submission.

---

## Stretch Features (Advanced AI Enhancements)

Beyond the base rubric, three stretch features have been implemented for advanced AI system behavior:

### 1. Agentic Workflow with Step-by-Step Reasoning

**Feature:** Intermediate reasoning steps are now recorded and exposed for each AI operation.

**How it was added:**
- Added `_ReasoningStep` class to capture step name, input, output, and reasoning explanation
- Added `_current_reasoning_trace` global list to accumulate steps during execution
- Modified `parse_booking_request()` to record 5 steps: input validation, context preparation, client init, model call, and response parsing
- Modified `suggest_alternative()` to record 6 steps: slot gathering, formatting, conflict analysis, client init, generation, and retry logic
- Added `get_reasoning_trace()` and `print_reasoning_trace()` for debugging and transparency
- Added `get_reasoning_json()` for UI integration

**Benefit:** Users and developers can now see exactly how the AI assistant processes requests, making the system more interpretable and easier to debug. Step-by-step reasoning improves trust in suggestions.

**Usage:**
```python
from ai_assistant import parse_booking_request, get_reasoning_trace

filters, error = parse_booking_request("quiet room for 4 tomorrow")
trace = get_reasoning_trace()
print(trace)  # Shows: validation → input_preparation → client_init → model_call → response_parsing
```

### 2. Domain-Specific Specialization

**Feature:** AI prompts now include few-shot examples tailored to the library booking domain.

**How it was added:**
- Enhanced `_SYSTEM_PROMPT` for `parse_booking_request()` with a "SPECIALIZATION" section
- Added 5 concrete booking interpretation examples:
  - "tomorrow afternoon" → interprets as day offset + hour range
  - "quiet room for 4" → capacity extraction
  - "90 minute meeting" → duration parsing
  - "room with projector and whiteboard" → amenities mapping
  - "next Monday morning" → day offset calculation
- Updated `suggest_alternative()` system prompt to emphasize quality ranking (room preference, time of day, duration)

**Benefit:** AI is now specialized for library bookings rather than general-purpose NLU, improving parse accuracy and suggestion relevance.

**Evidence:** The system now correctly interprets domain-specific language without manual rule-engineering (e.g., "quiet room" + "whiteboard" properly map to booking filters).

### 3. Evaluation Test Harness

**Feature:** Automated quality assessment of AI parse and suggestion outputs.

**How it was added:**
- Created `evaluation_harness.py` with:
  - `TEST_PARSE_CASES`: 4 representative booking prompts with expected keys and values
  - `TEST_SUGGESTION_CASES`: 1 multi-slot suggestion scenario
  - `score_parse()` and `score_suggestion()` functions for output validation
  - `evaluate_parse_quality()` and `evaluate_suggestion_quality()` runners
  - `generate_report()` for formatted pass/fail summary

**Benefit:** Developers can measure AI quality empirically. The harness verifies parse accuracy (key extraction, value correctness) and suggestion quality (keyword presence, word count >= 10 as truncation guard).

**Usage:**
```bash
python evaluation_harness.py
```

Output:
```
SUMMARY
───────
Total Cases:     5
Passed:          4
Failed:          1
Pass Rate:       80.0%

DETAILS
───────
✓ Natural language with capacity and duration: Pass
✓ Simple two-word request: Pass
✓ Specific time preference: Pass
✗ Amenities request: Missing keys: ['amenities']
✓ Suggest with multiple available slots: Pass
```

### 4. Confidence Scoring for AI Outputs

**Feature:** Confidence scores are attached to AI parse results so the UI can guide users on when to trust auto-filled filters versus when to edit them.

**How it was added (scoring design):**
- A composite confidence score is computed on a 0.00 to 1.00 scale.
- Score components are weighted to reflect practical reliability in booking intent extraction:
  - `Schema validity` (0.35): output must parse and match expected JSON structure.
  - `Field coverage` (0.30): proportion of expected booking fields recovered from prompt.
  - `Value consistency` (0.20): parsed values are internally coherent (for example, duration and time hints do not conflict).
  - `Prompt clarity` (0.15): user input specificity (date/time/group size/amenities present).

Scoring formula:

$$
	ext{confidence} = 0.35S + 0.30C + 0.20V + 0.15P
$$

Where each component is normalized to $[0,1]$.

**Interpretation thresholds:**
- `0.85 - 1.00` High confidence: auto-fill and proceed normally.
- `0.60 - 0.84` Medium confidence: auto-fill with a "review suggested" hint.
- `0.00 - 0.59` Low confidence: show coaching prompt and request clarification.

**Benefit:** Confidence scoring reduces silent AI mistakes and improves user trust by making uncertainty visible.

**Example:**
- Input: "quiet room for 4 tomorrow afternoon with whiteboard for 90 minutes"
- Parsed filters include duration, capacity, time window, and amenity.
- Typical confidence outcome: `~0.90` (high confidence).

---

## Project Structure

```
├── app.py                        # Streamlit UI (9 phases of UI)
├── booking_engine.py             # Domain models + BookingEngine + ConflictDetector
├── persistence.py                # SQLite BookingStore (Phase 8)
├── ai_assistant.py               # Gemini-powered search + conflict suggestions (Phase 7)
├── google_calendar_integration.py# OAuth2 GCal sync (Phase 4)
├── adapters/
│   ├── base.py                   # Abstract BaseLibraryAdapter
│   ├── libcal.py                 # SpringShare LibCal REST adapter
│   ├── scraper.py                # Generic HTML scraper adapter (Selenium-ready)
│   └── mock.py                   # Deterministic in-memory adapter for dev/tests
├── libraries.json                # Library configuration (adapter type, hours, rules)
├── tests/
│   ├── test_booking_engine.py    # Phase 1 — core engine (24 tests)
│   ├── test_adapters.py          # Phase 2 — adapter layer (34 tests)
│   ├── test_gcal_integration.py  # Phase 4 — GCal sync (37 tests)
│   ├── test_phase3_conflicts.py  # Phase 3 — conflict detection (22 tests)
│   ├── test_phase6_guardrails.py # Phase 6 — guardrails & edge cases
│   ├── test_ai_assistant.py      # Phase 7 — AI assistant (21 tests)
│   └── test_persistence.py       # Phase 8 — SQLite persistence (22 tests)
├── .env.example                  # Environment variable template
├── Dockerfile
└── docker-compose.yml
```

---

## Architecture

See [diagrams.md](diagrams.md) for full Mermaid diagrams:

- System architecture
- Entity-relationship diagram
- Booking flow sequence
- Conflict detection flow
- GCal sync flow
- Adapter class hierarchy

Diagram-to-code mapping (implemented components):
- UI/Workflow: app.py
- Booking domain and conflict engine: booking_engine.py
- Adapter layer and external source access: adapters/
- AI structured prompting and suggestion logic: ai_assistant.py
- Persistence: persistence.py + bookings.db
- Google Calendar integration: google_calendar_integration.py

The data flow in diagrams.md matches the running app flow:
input form -> AI parse (optional) -> availability fetch -> conflict detection -> booking -> persistence/calendar sync.

---

## Development Phases

| Phase | Description |
|---|---|
| 1 | Domain models, BookingEngine, scaffold UI |
| 2 | Pluggable adapter layer (LibCal, Scraper, Mock) |
| 3 | Conflict detection with dynamic operating hours |
| 4 | Google Calendar OAuth2 integration |
| 5 | Streamlit UI redesign — multi-step booking flow |
| 6 | Guardrails and edge-case hardening |
| 7 | AI assistant — natural-language search (Gemini 2.5 Flash) |
| 8 | SQLite persistence — bookings survive restarts |
| 9 | Production readiness — Docker, README, startup validation |

---

## Google Calendar Setup

1. Go to [Google Cloud Console](https://console.cloud.google.com/) → APIs & Services → Credentials.
2. Create an OAuth 2.0 Client ID (Desktop app).
3. Download the JSON file and place it in the project root as `client_secret_*.json`.
4. On first use, click **Connect Google Calendar** in the app sidebar; a browser window will open for sign-in. The token is saved to `token.json` for subsequent runs.

---

## Environment Variables

| Variable | Required | Description |
|---|---|---|
| `GEMINI_API_KEY` | For AI Search | Gemini API key from [Google AI Studio](https://aistudio.google.com/apikey) |
| `GOOGLE_API_KEY` | For AI Search | Alternate Gemini API key environment variable recognized by the SDK |
| `FOUNDERS_CLIENT_ID` | LibCal only | OAuth client ID for Founders Library |
| `FOUNDERS_CLIENT_SECRET` | LibCal only | OAuth client secret for Founders Library |
| `LAW_CLIENT_ID` | LibCal only | OAuth client ID for Law School Library |
| `LAW_CLIENT_SECRET` | LibCal only | OAuth client secret for Law School Library |
| `SCIENCE_CLIENT_ID` | LibCal only | OAuth client ID for Science Library |
| `SCIENCE_CLIENT_SECRET` | LibCal only | OAuth client secret for Science Library |
