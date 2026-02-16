import pytest
import sys
from pathlib import Path
from datetime import datetime, date, time, timedelta

# Add parent directory to path so we can import pawpal
sys.path.insert(0, str(Path(__file__).parent.parent))

from pawpal_system import Pet, Task, Priority, Owner, Scheduler

def test_mark_complete_changes_task_status():
    """Verify that calling mark_complete() changes the task's status to complete."""
    task = Task(id=1, title="Feed the dog", duration_minutes=30, priority=Priority.HIGH)
    assert task.completed is False
    task.mark_complete()
    assert task.completed is True


def test_adding_task_increases_pet_task_count():
    """Verify that adding a task to a Pet increases that pet's task count."""
    pet = Pet(id=1, name="Buddy", species="Golden Retriever")
    initial_count = len(pet.tasks)
    task = Task(id=2, title="Walk the dog", duration_minutes=45, priority=Priority.MEDIUM)
    pet.add_task(task)
    assert len(pet.tasks) == initial_count + 1


def test_schedule_single_task_default_start():
    """Verify default scheduling starts at 08:00 when no availability is provided."""
    scheduler = Scheduler()
    task = Task(id=1, title="Feed cat", duration_minutes=15, priority=Priority.MEDIUM)
    scheduled = scheduler.schedule_tasks(tasks=[task])
    assert len(scheduled) == 1
    assert scheduled[0].start_time.hour == 8
    assert scheduled[0].start_time.minute == 0


def test_schedule_uses_owner_availability_start():
    """Verify owner availability start time is used."""
    owner = Owner(id=1, name="Alex", preferences={"availability": {"start": "09:30"}})
    owner.add_task(Task(id=1, title="Morning walk", duration_minutes=30))
    scheduler = Scheduler()
    scheduled = scheduler.schedule_tasks(owner=owner)
    assert scheduled[0].start_time.hour == 9
    assert scheduled[0].start_time.minute == 30


def test_mixed_scheduled_and_unscheduled_ordering():
    """Verify scheduled tasks keep their time and unscheduled follow cursor."""
    base_date = date.today()
    t1 = Task(
        id=1,
        title="Vet appointment",
        duration_minutes=30,
        scheduled_time=datetime.combine(base_date, time(hour=10, minute=0)),
    )
    t2 = Task(id=2, title="Brush coat", duration_minutes=15)
    scheduler = Scheduler()
    scheduled = scheduler.schedule_tasks(
        tasks=[t2, t1],
        start_time=datetime.combine(base_date, time(hour=8, minute=0)),
    )
    assert scheduled[0].task is t1
    assert scheduled[1].task is t2
    assert scheduled[1].start_time == scheduled[0].end_time


def test_complete_task_creates_next_recurring_for_owner():
    """Verify recurring owner tasks spawn a new instance on completion."""
    base_time = datetime.combine(date.today(), time(hour=9, minute=0))
    owner = Owner(id=1, name="Alex")
    task = Task(
        id=1,
        title="Daily meds",
        duration_minutes=5,
        scheduled_time=base_time,
        recurrence="daily",
    )
    owner.add_task(task)
    scheduler = Scheduler()
    new_task = scheduler.complete_task(task, owner=owner)
    assert new_task is not None
    assert new_task.scheduled_time == base_time + timedelta(days=1)
    assert new_task in owner.tasks


def test_schedule_with_no_tasks_returns_empty_list():
    """Verify no tasks yields empty schedule and no warnings."""
    owner = Owner(id=1, name="Alex")
    scheduler = Scheduler()
    scheduled = scheduler.schedule_tasks(owner=owner)
    assert scheduled == []
    assert scheduler.last_warnings == []


def test_collision_warning_for_same_start_time():
    """Verify collision warning when tasks share the exact start time."""
    base_date = date.today()
    start = datetime.combine(base_date, time(hour=10, minute=0))
    t1 = Task(id=1, title="Grooming", duration_minutes=30, scheduled_time=start)
    t2 = Task(id=2, title="Playtime", duration_minutes=20, scheduled_time=start)
    scheduler = Scheduler()
    scheduler.schedule_tasks(tasks=[t1, t2], start_time=start)
    assert any("Collision" in w for w in scheduler.last_warnings)


def test_overlap_warning_for_overlapping_tasks():
    """Verify overlap warning for overlapping scheduled tasks."""
    base_date = date.today()
    t1 = Task(
        id=1,
        title="Training",
        duration_minutes=30,
        scheduled_time=datetime.combine(base_date, time(hour=10, minute=0)),
    )
    t2 = Task(
        id=2,
        title="Bath",
        duration_minutes=30,
        scheduled_time=datetime.combine(base_date, time(hour=10, minute=15)),
    )
    scheduler = Scheduler()
    scheduler.schedule_tasks(tasks=[t1, t2], start_time=t1.scheduled_time)
    assert any("Overlap" in w for w in scheduler.last_warnings)


def test_no_overlap_when_end_equals_next_start():
    """Verify no overlap warning when one task ends as the next starts."""
    base_date = date.today()
    t1 = Task(
        id=1,
        title="Fetch",
        duration_minutes=30,
        scheduled_time=datetime.combine(base_date, time(hour=10, minute=0)),
    )
    t2 = Task(
        id=2,
        title="Nap",
        duration_minutes=15,
        scheduled_time=datetime.combine(base_date, time(hour=10, minute=30)),
    )
    scheduler = Scheduler()
    scheduler.schedule_tasks(tasks=[t1, t2], start_time=t1.scheduled_time)
    assert not any("Overlap" in w for w in scheduler.last_warnings)


def test_invalid_duration_raises_value_error():
    """Verify invalid duration raises a validation error."""
    base_date = date.today()
    t1 = Task(
        id=1,
        title="Zero duration",
        duration_minutes=0,
        scheduled_time=datetime.combine(base_date, time(hour=9, minute=0)),
    )
    scheduler = Scheduler()
    with pytest.raises(ValueError):
        scheduler.schedule_tasks(tasks=[t1], start_time=t1.scheduled_time)


def test_availability_bounds_warnings():
    """Verify warnings when tasks are outside owner availability."""
    base_date = date.today()
    owner = Owner(
        id=1,
        name="Alex",
        preferences={"availability": {"start": "09:00", "end": "10:00"}},
    )
    t1 = Task(
        id=1,
        title="Early walk",
        duration_minutes=30,
        scheduled_time=datetime.combine(base_date, time(hour=8, minute=30)),
    )
    t2 = Task(
        id=2,
        title="Late feeding",
        duration_minutes=30,
        scheduled_time=datetime.combine(base_date, time(hour=9, minute=45)),
    )
    scheduler = Scheduler()
    scheduler.schedule_tasks(tasks=[t1, t2], owner=owner, start_time=t1.scheduled_time)
    outside = [w for w in scheduler.last_warnings if "Outside availability" in w]
    assert len(outside) >= 2


def test_recurring_task_without_scheduled_time_returns_none():
    """Verify recurring task without scheduled_time does not spawn a new task."""
    task = Task(
        id=1,
        title="Daily check",
        duration_minutes=5,
        recurrence="daily",
    )
    scheduler = Scheduler()
    new_task = scheduler.complete_task(task)
    assert new_task is None
    assert task.completed is True
