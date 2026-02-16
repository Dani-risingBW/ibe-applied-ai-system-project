## UML Diagrams for PawPal+

### Mermaid Class Diagram

```mermaid
classDiagram
    %% Classes
    class Owner {
      +int id
      +string name
      +get_availability() TimeWindow
      +add_pet(p: Pet)
    }

    class Pet {
      +int id
      +string name
      +string species
      +int owner_id
      +describe() string
    }

    class Task {
      +int id
      +string title
      +int owner_id
      +int pet_id
      +int duration_minutes
      +string priority
      +estimate_end(start: datetime) datetime
    }

    class ScheduledTask {
      +int id
      +Task task
      +datetime start_time
      +datetime end_time
      +string reason
      +to_dict() dict
      +validate() bool
    }

    class Scheduler {
      +rules: dict
      +schedule_tasks(tasks: List~Task~, owner: Owner, pets: List~Pet~) List~ScheduledTask~
      +explain_schedule(scheduled: List~ScheduledTask~) List~string~
    }

    %% Relationships
    Owner "1" -- "0..*" Pet : owns
    Owner "1" -- "0..*" Task : creates
    Pet "0..*" -- "0..*" Task : assigned_to
    Scheduler ..> Task : uses
    Scheduler ..> Owner : reads
    Scheduler ..> Pet : reads

```

### Mermaid Sequence Diagram (main flow)

```mermaid
sequenceDiagram
    participant User
    participant Browser
    participant App as StreamlitApp
    participant Scheduler

    User->>Browser: open app
    Browser->>App: render UI
    User->>App: fill owner/pet inputs
    User->>App: add task(s)
    App->>App: append task dicts to st.session_state.tasks
    User->>App: click Generate schedule
    App->>Scheduler: schedule_tasks(tasks, owner, pets)
    Scheduler-->>App: return scheduled tasks + explanations
    App-->>Browser: render schedule and explanations
```

### Mermaid ER Diagram (DB schema)

```mermaid
erDiagram
    OWNERS {
      INTEGER id PK
      TEXT name NOT NULL UNIQUE
    }
    PETS {
      INTEGER id PK
      TEXT name NOT NULL
      TEXT species
      INTEGER owner_id FK
    }
    TASKS {
      INTEGER id PK
      TEXT title NOT NULL
      INTEGER owner_id FK NOT NULL
      INTEGER pet_id FK
      INTEGER duration_minutes NOT NULL
      TEXT priority NOT NULL
    }
    SCHEDULED_TASKS {
      INTEGER id PK
      INTEGER task_id FK UNIQUE
      DATETIME start_time NOT NULL
      DATETIME end_time NOT NULL
      TEXT reason
    }

    OWNERS ||--o{ PETS : owns
    OWNERS ||--o{ TASKS : creates
    PETS ||--o{ TASKS : assigned_to
    TASKS ||--o{ SCHEDULED_TASKS : becomes
```

### SQL DDL (SQLite) with constraints

```sql
-- Owners
CREATE TABLE owners (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  name TEXT NOT NULL UNIQUE
);

-- Pets
CREATE TABLE pets (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  name TEXT NOT NULL,
  species TEXT,
  owner_id INTEGER NOT NULL,
  FOREIGN KEY(owner_id) REFERENCES owners(id) ON DELETE CASCADE
);

-- Tasks
CREATE TABLE tasks (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  title TEXT NOT NULL,
  owner_id INTEGER NOT NULL,
  pet_id INTEGER,
  duration_minutes INTEGER NOT NULL CHECK(duration_minutes > 0),
  priority TEXT NOT NULL CHECK(priority IN ('low','medium','high')),
  FOREIGN KEY(owner_id) REFERENCES owners(id) ON DELETE CASCADE,
  FOREIGN KEY(pet_id) REFERENCES pets(id) ON DELETE SET NULL
);

-- Scheduled tasks
CREATE TABLE scheduled_tasks (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  task_id INTEGER NOT NULL UNIQUE,
  start_time DATETIME NOT NULL,
  end_time DATETIME NOT NULL,
  reason TEXT,
  FOREIGN KEY(task_id) REFERENCES tasks(id) ON DELETE CASCADE,
  CHECK(end_time > start_time)
);
```

### Notes

- The current repository stores tasks in `st.session_state` as simple dicts. The diagrams above map these dicts to concrete models and an optional SQLite schema.
- The `Scheduler` class is a design-time component: implement `schedule_tasks()` to consume `Task` objects and produce `ScheduledTask` entries that satisfy constraints (time windows, priorities).
 - The Python implementation uses `dataclasses` for `Owner`, `Pet`, `Task`, and `ScheduledTask` (see `pawpal_system.py`).
 - `ScheduledTask.to_dict()` should serialize fields for UI/DB; `ScheduledTask.validate()` should ensure `end_time > start_time` and may raise `ValueError` on invalid ranges.
 - Method stubs exist in `pawpal_system.py` for: `Owner.add_pet()`, `Owner.get_availability()`, `Pet.describe()`, `Task.estimate_end()`, `ScheduledTask.to_dict()`, `Scheduler.schedule_tasks()`, and `Scheduler.explain_schedule()`.

If you want, I can also add a `schema.sql` file, stub Python class files for `Owner`, `Pet`, `Task`, and `Scheduler`, and simple unit tests next.
