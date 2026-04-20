# Library Room Booking System — Diagrams

## 1. System Architecture

```mermaid
graph TD
    UI[Streamlit UI\nsession_state: user, bookings, filters] --> Engine[BookingEngine\nlibraries, gcal, conflict_detector, bookings]
    Engine --> LibAdapter[Library Adapter Layer\nfetch_availability · book_room · cancel_booking]
    Engine --> GCal[GoogleCalendarIntegration\ncredentials_file, token_file, scopes]
    Engine --> ConflictEngine[ConflictDetector\nwarnings: list · blockers: list]

    LibAdapter -->|client_id, client_secret, base_url| LC[LibCalAdapter\nOAuth2 token · REST API]
    LibAdapter -->|base_url, selectors dict| WS[ScraperAdapter\nWebDriver · BeautifulSoup]
    LibAdapter -->|rooms list, fixed slots| Mock[MockAdapter\nfor testing only]

    GCal -->|token.json| Auth[OAuth 2.0 Credentials\naccess_token, refresh_token, expiry]
    GCal -->|date, calendar_id| Fetch[Fetch Events\nreturns list of GCal event dicts]
    GCal -->|Booking → RFC3339 event| Push[Push Booking\nreturns gcal_event_id]

    ConflictEngine -->|date range| GCal
    ConflictEngine -->|room_id, start_time, end_time| Bookings[Local Bookings Store\nlist of Booking objects]

    Engine -->|room_id, slot, user_credentials| BookingAPI[Booking Submitter\nreturns BookingResult]
```

---

## 2. Entity-Relationship Diagram

```mermaid
erDiagram
    USER {
        string id PK
        string name
        string email
        string university_id
        string password_hash
        int max_hours_per_week
        string default_library_id FK
        json preferred_times
        datetime created_at
    }

    LIBRARY {
        string id PK
        string name
        string campus
        string building
        string base_url
        string adapter_type
        string open_time
        string close_time
        string open_days
        int max_booking_days_ahead
        int max_booking_duration_hours
        int max_bookings_per_user_per_day
    }

    ROOM {
        string id PK
        string library_id FK
        string name
        string floor
        string room_type
        int capacity
        bool accessible
        bool has_whiteboard
        bool has_display
        bool has_phone
        bool has_video_conf
        string image_url
        string notes
    }

    BOOKING {
        string id PK
        string room_id FK
        string user_id FK
        string library_id FK
        datetime start_time
        datetime end_time
        int duration_minutes
        string purpose
        string status
        string gcal_event_id
        string confirmation_code
        string cancellation_reason
        datetime created_at
        datetime updated_at
        string notes
    }

    AVAILABILITY_SLOT {
        string id PK
        string room_id FK
        string library_id FK
        datetime start_time
        datetime end_time
        int duration_minutes
        bool is_available
        string unavailable_reason
        datetime fetched_at
    }

    USER ||--o{ BOOKING : "makes"
    USER }o--|| LIBRARY : "prefers"
    LIBRARY ||--o{ ROOM : "contains"
    ROOM ||--o{ BOOKING : "reserved via"
    ROOM ||--o{ AVAILABILITY_SLOT : "has"
    LIBRARY ||--o{ AVAILABILITY_SLOT : "provides"
    BOOKING ||--o| AVAILABILITY_SLOT : "locks"
```

---

## 3. Full Domain Class Diagram

```mermaid
classDiagram
    class User {
        +id: str
        +name: str
        +email: str
        +university_id: str
        +password_hash: str
        +default_library_id: str
        +max_hours_per_week: int
        +preferred_times: dict
        +created_at: datetime
    }

    class Library {
        +id: str
        +name: str
        +campus: str
        +building: str
        +base_url: str
        +adapter_type: str
        +open_time: str
        +close_time: str
        +open_days: list~str~
        +max_booking_days_ahead: int
        +max_booking_duration_hours: int
        +max_bookings_per_user_per_day: int
    }

    class Room {
        +id: str
        +library_id: str
        +name: str
        +floor: str
        +room_type: str
        +capacity: int
        +accessible: bool
        +has_whiteboard: bool
        +has_display: bool
        +has_phone: bool
        +has_video_conf: bool
        +image_url: str
        +notes: str
    }

    class Booking {
        +id: str
        +room_id: str
        +user_id: str
        +library_id: str
        +start_time: datetime
        +end_time: datetime
        +duration_minutes: int
        +purpose: str
        +status: str
        +gcal_event_id: str
        +confirmation_code: str
        +cancellation_reason: str
        +created_at: datetime
        +updated_at: datetime
        +notes: str
    }

    class AvailabilitySlot {
        +id: str
        +room_id: str
        +library_id: str
        +start_time: datetime
        +end_time: datetime
        +duration_minutes: int
        +is_available: bool
        +unavailable_reason: str
        +fetched_at: datetime
    }

    class RoomFilters {
        +min_capacity: int
        +max_capacity: int
        +amenities: list~str~
        +accessible_only: bool
        +duration_minutes: int
        +room_type: str
        +floor: str
    }

    class BookingResult {
        +success: bool
        +confirmation_code: str
        +booking_id: str
        +message: str
        +error_code: str
        +raw_response: dict
    }

    class ConflictResult {
        +has_conflict: bool
        +warnings: list~str~
        +blockers: list~str~
        +conflicting_event_titles: list~str~
        +conflicting_booking_ids: list~str~
    }

    class BookingEngine {
        +libraries: dict~str_BaseLibraryAdapter~
        +gcal: GoogleCalendarIntegration
        +conflict_detector: ConflictDetector
        +bookings: list~Booking~
        +fetch_availability(library_id, date, filters) list~AvailabilitySlot~
        +check_conflicts(slot, user_id) ConflictResult
        +book_room(slot, user, dry_run) BookingResult
        +cancel_booking(booking_id, reason) bool
        +get_user_bookings(user_id) list~Booking~
    }

    class ConflictDetector {
        +detect(slot, gcal_events, existing_bookings, library) ConflictResult
        -_check_gcal_overlap(slot, events) list~str~
        -_check_room_double_book(slot, bookings) list~str~
        -_check_operating_hours(slot, library) list~str~
        -_check_advance_limit(slot, library) list~str~
        -_check_duration_limit(slot, library) list~str~
        -_check_user_daily_limit(slot, user_id, bookings, library) list~str~
    }

    class GoogleCalendarIntegration {
        +credentials_file: str
        +token_file: str
        +scopes: list~str~
        +calendar_id: str
        +authenticate() Credentials
        +fetch_gcal_events(date) list~dict~
        +booking_to_gcal_event(booking) dict
        +gcal_event_to_booking(event) Booking
        +create_event(event_dict) str
        +cancel_event(event_id) bool
        +check_gcal_conflicts(slot, gcal_events) ConflictResult
    }

    class BaseLibraryAdapter {
        <<abstract>>
        +library_id: str
        +config: dict
        +request_timeout: int
        +max_retries: int
        +requests_per_minute: int
        +fetch_availability(date, filters) list~AvailabilitySlot~
        +book_room(slot, user) BookingResult
        +cancel_booking(confirmation_code) bool
        #_rate_limit()
        #_retry(fn, retries) any
        #_check_robots_txt(url) bool
    }

    class LibCalAdapter {
        +base_url: str
        +client_id: str
        +client_secret: str
        +api_version: str
        -_token: str
        -_token_expiry: datetime
        +fetch_availability(date, filters) list~AvailabilitySlot~
        +book_room(slot, user) BookingResult
        +cancel_booking(confirmation_code) bool
        -_authenticate() str
        -_parse_slots(raw_json) list~AvailabilitySlot~
        -_build_reserve_payload(slot, user) dict
    }

    class ScraperAdapter {
        +base_url: str
        +selectors: dict
        +request_delay_seconds: float
        -_driver: WebDriver
        +fetch_availability(date, filters) list~AvailabilitySlot~
        +book_room(slot, user) BookingResult
        +cancel_booking(confirmation_code) bool
        -_load_page(url) str
        -_parse_html(html) list~AvailabilitySlot~
        -_fill_booking_form(slot, user)
        -_extract_confirmation(page_source) str
    }

    class MockAdapter {
        +rooms: list~Room~
        +fixed_slots: list~AvailabilitySlot~
        +always_confirm: bool
        +simulated_error: str
        +fetch_availability(date, filters) list~AvailabilitySlot~
        +book_room(slot, user) BookingResult
        +cancel_booking(confirmation_code) bool
    }

    BookingEngine --> ConflictDetector
    BookingEngine --> GoogleCalendarIntegration
    BookingEngine --> BaseLibraryAdapter
    BookingEngine --> Booking
    ConflictDetector --> ConflictResult
    ConflictDetector --> GoogleCalendarIntegration
    BaseLibraryAdapter <|-- LibCalAdapter
    BaseLibraryAdapter <|-- ScraperAdapter
    BaseLibraryAdapter <|-- MockAdapter
    BaseLibraryAdapter --> AvailabilitySlot
    BaseLibraryAdapter --> BookingResult
    User --> Booking
    Room --> Booking
    Room --> AvailabilitySlot
    Library --> Room
    Library --> AvailabilitySlot
    Booking --> BookingResult
    BookingEngine --> RoomFilters
```

---

## 4. Booking Flow (Sequence Diagram)

```mermaid
sequenceDiagram
    actor User
    participant UI as Streamlit UI
    participant Engine as BookingEngine
    participant Adapter as LibraryAdapter
    participant GCal as GoogleCalendarIntegration
    participant Library as Library Website

    User->>UI: Select library_id, date, duration_minutes, min_capacity
    UI->>Adapter: fetch_availability(library_id, date, RoomFilters)
    Adapter->>Library: GET /space/slots?date&capacity (LibCal) or scrape HTML
    Library-->>Adapter: Raw slots JSON / HTML
    Adapter-->>UI: list[AvailabilitySlot]

    UI->>User: Render room cards (name, floor, capacity, amenities, start_time, end_time)
    User->>UI: Select AvailabilitySlot

    UI->>GCal: fetch_gcal_events(date) → list[dict]
    GCal-->>UI: calendar events (summary, start, end, id)

    UI->>Engine: check_conflicts(slot, gcal_events, existing_bookings, library)
    Engine-->>UI: ConflictResult(has_conflict, warnings, blockers, conflicting_event_titles)

    alt blockers present
        UI->>User: Show blocker — cannot proceed
    else warnings only
        UI->>User: Show warnings — user can override
        User->>UI: Confirm override
    end

    User->>UI: Confirm booking (purpose, notes)
    UI->>Adapter: book_room(slot, user, dry_run=False)
    Adapter->>Library: POST /space/reserve payload (room_id, start, end, fname, lname, email)
    Library-->>Adapter: confirmation_code / error
    Adapter-->>UI: BookingResult(success, confirmation_code, booking_id, message)

    UI->>GCal: create_event(booking_to_gcal_event(booking))
    GCal-->>UI: gcal_event_id
    UI->>User: Show confirmation_code + gcal_event_id + calendar link
```

---

## 5. Booking State Machine

```mermaid
stateDiagram-v2
    [*] --> Searching : user opens app\nstate: library_id=None, slot=None
    Searching --> SlotSelected : user picks AvailabilitySlot\nstate: slot.room_id, slot.start_time, slot.end_time
    SlotSelected --> ConflictChecked : fetch_gcal_events(date)\ncheck_conflicts(slot, gcal_events)
    ConflictChecked --> ConflictWarned : ConflictResult.warnings not empty\nor ConflictResult.blockers not empty
    ConflictChecked --> ReadyToBook : ConflictResult.has_conflict = False
    ConflictWarned --> ReadyToBook : user overrides warnings\nblockers must be empty
    ConflictWarned --> Searching : user picks new slot
    ReadyToBook --> Submitting : user confirms\npurpose + notes provided
    Submitting --> Confirmed : BookingResult.success = True\nconfirmation_code assigned
    Submitting --> Failed : BookingResult.success = False\nerror_code set
    Failed --> Searching : user retries
    Confirmed --> SyncedToGCal : create_event returns gcal_event_id\nBooking.status = confirmed
    SyncedToGCal --> [*]
    Confirmed --> Cancelled : user cancels\ncancellation_reason provided
    Cancelled --> [*] : cancel_booking + cancel_event\nBooking.status = cancelled
```

---

## 6. Phase Timeline (Gantt)

```mermaid
gantt
    title Library Room Booking System — Build Phases
    dateFormat  YYYY-MM-DD
    section Phase 1
    Domain Refactor           :p1, 2026-04-17, 7d
    section Phase 2
    LibCal Adapter            :p2a, after p1, 5d
    Scraper Adapter           :p2b, after p2a, 5d
    section Phase 3
    Conflict Detection Engine :p3, after p1, 7d
    section Phase 4
    GCal Integration Update   :p4, after p3, 5d
    section Phase 5
    Streamlit UI Redesign     :p5, after p4, 7d
    section Phase 6
    Unit Tests                :p6a, after p1, 14d
    Integration Tests         :p6b, after p2b, 7d
    Guardrails & Hardening    :p6c, after p5, 5d
```
