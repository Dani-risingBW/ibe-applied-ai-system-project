("""Simple runner to demonstrate pawpal_system scheduling.

Run: `python main.py`
""")

from datetime import datetime, timedelta

from pawpal_system import Owner, Pet, Task, Scheduler, Priority


def build_demo_data() -> tuple[Owner, Scheduler]:
	owner = Owner(id=1, name="Nkiru")

	# two pets
	dog = Pet(id=10, name="Rufus", species="dog", owner_id=owner.id)
	cat = Pet(id=11, name="Mittens", species="cat", owner_id=owner.id)
	owner.add_pet(dog)
	owner.add_pet(cat)

	# three tasks with different times/priorities
	now = datetime.now().replace(second=0, microsecond=0)

	walk = Task(id=101, title="Morning Walk", duration_minutes=30, priority=Priority.HIGH)
	walk.scheduled_time = now.replace(hour=8, minute=0)
	dog.add_task(walk)

	feed = Task(id=102, title="Feed Pets", duration_minutes=15, priority=Priority.MEDIUM)
	feed.scheduled_time = now.replace(hour=12, minute=0)
	owner.add_task(feed)  # owner-level task

	meds = Task(id=103, title="Give Medication", duration_minutes=5, priority=Priority.HIGH)
	# leave meds unscheduled so scheduler will place it after scheduled tasks
	cat.add_task(meds)

	scheduler = Scheduler()
	return owner, scheduler


def print_schedule(owner: Owner, scheduler: Scheduler) -> None:
	scheduled = scheduler.schedule_tasks(owner=owner)
	print("Today's schedule:")
	for s in scheduled:
		start = s.start_time.strftime("%Y-%m-%d %H:%M")
		end = s.end_time.strftime("%H:%M")
		print(f"- {start} to {end}: {s.task.title} (pet_id={s.task.pet_id}, priority={s.task.priority})")


if __name__ == "__main__":
	owner, scheduler = build_demo_data()
	print_schedule(owner, scheduler)

