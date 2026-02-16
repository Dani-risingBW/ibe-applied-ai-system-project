import pytest
import sys
from pathlib import Path

# Add parent directory to path so we can import pawpal
sys.path.insert(0, str(Path(__file__).parent.parent))

from pawpal_system import Pet, Task, Priority

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
