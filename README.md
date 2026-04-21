# Library Room Booking System

A full-stack university study-room booking application built with Streamlit.  
Students search for available rooms across multiple campus libraries, check Google Calendar conflicts, and confirm reservations — with an AI assistant that understands plain-English requests.

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
| 7 | AI assistant — natural-language search (Claude API) |
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
