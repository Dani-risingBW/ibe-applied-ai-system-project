import streamlit as st
from pawpal_system import Owner, Pet, Task, ScheduledTask, Scheduler, Priority
from datetime import time, date, datetime as dt
import datetime
# gcal_service is None until the user authenticates via the sidebar
import google_calendar_integration as gcal

st.set_page_config(page_title="PawPal+", page_icon="🐾", layout="centered")

# ── Sidebar: Google Calendar connection ────────────────────────────────────────
# Sidebar persists across reruns; gcal_service is stored in session_state
with st.sidebar:
    st.header("Google Calendar")

    # Initialize connection state on first load
    if "gcal_service" not in st.session_state:
        st.session_state.gcal_service = None

    if st.session_state.gcal_service is None:
        st.info("Not connected.")
        # Clicking this button opens the OAuth browser flow
        if st.button("Connect Google Calendar", use_container_width=True):
            try:
                with st.spinner("Opening browser for sign-in…"):
                    st.session_state.gcal_service = gcal.authenticate()
                st.success("Connected!")
                st.rerun()
            except Exception as e:
                st.error(f"Connection failed: {e}")
    else:
        st.success("Connected")
        # Clearing the service forces re-authentication on next connect
        if st.button("Disconnect", use_container_width=True):
            st.session_state.gcal_service = None
            st.rerun()

        # Show today's events as a quick reference without leaving the app
        st.markdown("**Today's Google Calendar events**")
        try:
            gcal_events = gcal.fetch_gcal_events(st.session_state.gcal_service)
            if gcal_events:
                for ev in gcal_events:
                    start = (ev.get("start") or {}).get("dateTime") or (ev.get("start") or {}).get("date", "")
                    summary = ev.get("summary", "Untitled")
                    # Slice HH:MM from the ISO dateTime string
                    time_label = start[11:16] if "T" in start else start
                    st.markdown(f"- **{time_label}** {summary}")
            else:
                st.caption("No events today.")
        except Exception as e:
            st.warning(f"Could not load events: {e}")

# ── Main app ───────────────────────────────────────────────────────────────────
st.title("🐾 PawPal+")

st.markdown(
    """
Welcome to the PawPal+ starter app.

This file is intentionally thin. It gives you a working Streamlit app so you can start quickly,
but **it does not implement the project logic**. Your job is to design the system and build it.

Use this app as your interactive demo once your backend classes/functions exist.
"""
)

with st.expander("Scenario", expanded=True):
    st.markdown(
        """
**PawPal+** is a pet care planning assistant. It helps a pet owner plan care tasks
for their pet(s) based on constraints like time, priority, and preferences.

You will design and implement the scheduling logic and connect it to this Streamlit UI.
"""
    )

with st.expander("What you need to build", expanded=True):
    st.markdown(
        """
At minimum, your system should:
- Represent pet care tasks (what needs to happen, how long it takes, priority)
- Represent the pet and the owner (basic info and preferences)
- Build a plan/schedule for a day that chooses and orders tasks based on constraints
- Explain the plan (why each task was chosen and when it happens)
"""
    )

st.divider()

st.subheader("Quick Demo Inputs (UI only)")
owner_name = st.text_input("Owner name", value="Jordan")
pet_name = st.text_input("Pet name", value="Mochi")
species = st.selectbox("Species", ["dog", "cat", "other"])

st.markdown("### Owner Availability")
av_col1, av_col2 = st.columns(2)
with av_col1:
    avail_start = st.time_input("Available start", value=time(hour=8, minute=0), key="avail_start")
with av_col2:
    avail_end = st.time_input("Available end", value=time(hour=18, minute=0), key="avail_end")

# Initialize owner, pet, and scheduler once per session
if "owner" not in st.session_state:
    st.session_state.owner = Owner(id=None, name=owner_name)
if "pet" not in st.session_state:
    st.session_state.pet = Pet(id=None, name=pet_name, species=species)
if "scheduler" not in st.session_state:
    st.session_state.scheduler = Scheduler()

owner = st.session_state.owner
pet = st.session_state.pet
scheduler = st.session_state.scheduler

# Keep owner/pet fields in sync with the current widget values
owner.name = owner_name
pet.name = pet_name
pet.species = species
if pet not in owner.pets:
    owner.add_pet(pet)
owner.preferences["availability"] = {
    "start": avail_start.strftime("%H:%M"),
    "end": avail_end.strftime("%H:%M"),
}

st.markdown("### Tasks")
st.caption("Add a few tasks. In your final version, these should feed into your scheduler.")

col1, col2, col3 = st.columns(3)
with col1:
    task_title = st.text_input("Task title", value="Morning walk")
with col2:
    duration = st.number_input("Duration (minutes)", min_value=1, max_value=240, value=20)
with col3:
    priority = st.selectbox("Priority", ["low", "medium", "high"], index=2)
    set_task_time = st.checkbox("Set task start time", value=False)
    task_time = st.time_input(
        "Task start time",
        value=time(hour=9, minute=0),
        disabled=not set_task_time,
        key="task_start_time",
    )
    recurrence = st.selectbox("Recurrence", ["none", "daily", "weekly"], index=0)

if st.button("Add task"):
    # Only set scheduled_time if the user explicitly checked the box
    scheduled_time = (
        dt.combine(date.today(), task_time) if set_task_time else None
    )
    recurrence_value = None if recurrence == "none" else recurrence
    task = Task(
        id=None,
        title=task_title,
        duration_minutes=int(duration),
        priority=Priority.from_str(priority),
        scheduled_time=scheduled_time,
        recurrence=recurrence_value,
    )
    pet.add_task(task)

if pet.tasks:
    sorted_tasks = scheduler.sort_by_time(pet.tasks)
    st.success("Tasks ready for scheduling.")
    st.table(
        [
            {
                "title": t.title,
                "scheduled_time": t.scheduled_time.strftime("%Y-%m-%d %H:%M") if t.scheduled_time else "-",
                "duration_minutes": t.duration_minutes,
                "priority": t.priority.value,
                "recurrence": t.recurrence or "-",
                "completed": "yes" if t.completed else "no",
            }
            for t in sorted_tasks
        ]
    )
    st.markdown("### Complete Task")
    incomplete_tasks = [t for t in sorted_tasks if not t.completed]
    if incomplete_tasks:
        labels = [f"{t.title} ({t.priority.value})" for t in incomplete_tasks]
        selected_label = st.selectbox("Select a task", labels, key="complete_task_select")
        if st.button("Complete selected task"):
            selected_index = labels.index(selected_label)
            selected_task = incomplete_tasks[selected_index]
            new_task = scheduler.complete_task(selected_task, owner=owner)
            if new_task:
                st.success(f"Completed '{selected_task.title}'. Next {new_task.recurrence} task added.")
            else:
                st.success(f"Completed '{selected_task.title}'.")
    else:
        st.info("No incomplete tasks to complete.")
else:
    st.info("No tasks yet. Add one above.")

st.divider()

st.subheader("Build Schedule")
st.caption("This button should call your scheduling logic once you implement it.")

use_availability = st.checkbox("Use owner availability for schedule start", value=True)
start_dt = None
if not use_availability:
    start_time_input = st.time_input("Schedule start time", value=time(hour=8, minute=0))
    start_dt = dt.combine(date.today(), start_time_input)

# Persisted in session_state so the GCal section can access it after the button reruns the page
if "last_schedule" not in st.session_state:
    st.session_state.last_schedule = []

if st.button("Generate schedule"):
    scheduled = scheduler.schedule_tasks(owner=owner, start_time=start_dt)
    # Store result so GCal conflict check and export can access it on the next rerun
    st.session_state.last_schedule = scheduled

    if scheduled:
        st.success(f"Built schedule with {len(scheduled)} tasks.")
        ordered = sorted(scheduled, key=lambda s: s.start_time)
        st.table(
            [
                {
                    "title": s.task.title,
                    "start_time": s.start_time.strftime("%Y-%m-%d %H:%M"),
                    "end_time": s.end_time.strftime("%H:%M"),
                    "priority": s.task.priority.value,
                }
                for s in ordered
            ]
        )
        # Show PawPal-only conflicts before the GCal check runs below
        if scheduler.last_warnings:
            st.warning("PawPal scheduling conflicts detected:")
            for w in scheduler.last_warnings:
                st.write(f"- {w}")
        st.markdown("### Explanation")
        for line in scheduler.explain_schedule(ordered):
            st.write(f"- {line}")
    else:
        st.info("No tasks available to schedule.")

# ── Google Calendar section ────────────────────────────────────────────────────
# Only shown when a schedule exists and the user is connected to Google Calendar
if st.session_state.last_schedule and st.session_state.gcal_service:
    st.divider()
    st.subheader("Google Calendar")

    # Combined check merges GCal events with PawPal tasks and runs detect_conflicts
    with st.spinner("Checking conflicts with Google Calendar…"):
        try:
            combined_warnings = gcal.check_gcal_conflicts(
                st.session_state.gcal_service,
                st.session_state.last_schedule,
                owner=owner,
            )
            if combined_warnings:
                st.warning("Conflicts with your Google Calendar:")
                for w in combined_warnings:
                    st.write(f"- {w}")
            else:
                st.success("No conflicts with your Google Calendar today.")
        except Exception as e:
            st.warning(f"Could not check Google Calendar conflicts: {e}")

    if st.button("Export schedule to Google Calendar"):
        exported, errors = 0, []
        for s in st.session_state.last_schedule:
            # Tasks without a scheduled_time have no dateTime to send — skip and warn
            if s.task.scheduled_time is None:
                errors.append(f"'{s.task.title}' has no start time — skipped.")
                continue
            try:
                gcal.push_task_to_gcal(st.session_state.gcal_service, s.task)
                exported += 1
            except Exception as e:
                errors.append(f"'{s.task.title}': {e}")

        if exported:
            st.success(f"Exported {exported} task(s) to Google Calendar.")
        for err in errors:
            st.warning(err)

elif st.session_state.last_schedule and st.session_state.gcal_service is None:
    # Nudge the user to connect if they have a schedule but no GCal session
    st.info("Connect Google Calendar (sidebar) to check conflicts and export your schedule.")
