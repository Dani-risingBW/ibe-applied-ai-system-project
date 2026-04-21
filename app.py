import os
import glob as _glob

import streamlit as st
from dotenv import load_dotenv
from booking_engine import BookingEngine, User, RoomFilters
from adapters import load_libraries
from datetime import date, datetime
import google_calendar_integration as gcal
import ai_assistant

load_dotenv()

st.set_page_config(page_title="Library Room Booking", page_icon="📚", layout="wide")

# ── Startup validation ─────────────────────────────────────────────────────────
def _startup_check() -> bool:
    """Return True if the environment looks good; otherwise render a setup guide and return False."""
    issues = []
    hints = []

    if not os.path.exists("libraries.json"):
        issues.append("`libraries.json` not found.")
        hints.append("Create a `libraries.json` file (see the README for the format).")

    if not _glob.glob("client_secret_*.json"):
        hints.append(
            "No `client_secret_*.json` found — Google Calendar will be unavailable. "
            "Download OAuth credentials from Google Cloud Console to enable it."
        )

    if not (os.environ.get("GEMINI_API_KEY") or os.environ.get("GOOGLE_API_KEY")):
        hints.append(
            "No `GEMINI_API_KEY` or `GOOGLE_API_KEY` set — AI Search will be unavailable. "
            "Add one of them to your `.env` file (see `.env.example`)."
        )

    if issues:
        st.error("**Setup incomplete — the app cannot start.**")
        for issue in issues:
            st.error(f"- {issue}")
        with st.expander("Setup guide", expanded=True):
            st.markdown(
                "1. Copy `.env.example` to `.env` and fill in your keys.\n"
                "2. Ensure `libraries.json` exists in the project root.\n"
                "3. See `README.md` for full setup instructions."
            )
        if hints:
            st.info("\n\n".join(hints))
        return False

    if hints:
        for hint in hints:
            st.sidebar.info(hint)
    return True

if not _startup_check():
    st.stop()

# ── Session state init ─────────────────────────────────────────────────────────
if "engine" not in st.session_state:
    engine = BookingEngine(db_path="bookings.db")
    try:
        libraries = load_libraries(engine, "libraries.json")
    except FileNotFoundError:
        libraries = {}
        st.warning("libraries.json not found — no libraries loaded.")
    st.session_state.engine = engine
    st.session_state.libraries = libraries

for _k, _v in [
    ("current_user", None), ("available_slots", []), ("search_executed", False),
    ("selected_slot", None), ("gcal_service", None), ("last_gcal_link", None),
    ("ai_parsed", {}),
]:
    if _k not in st.session_state:
        st.session_state[_k] = _v

engine: BookingEngine = st.session_state.engine
libraries: dict = st.session_state.libraries

_AMENITY_ICONS = {
    "Whiteboard": "🖊",
    "Display/TV": "📺",
    "Video conferencing": "📹",
    "Phone": "📞",
    "Accessible": "♿",
}


# ── Step progress bar ──────────────────────────────────────────────────────────

def _current_step() -> int:
    if st.session_state.current_user is None:
        return 0
    if not st.session_state.available_slots:
        return 1
    if st.session_state.selected_slot is None:
        return 2
    return 3


def _step_bar():
    labels = ["Your Info", "Search", "Pick a Room", "Review & Book"]
    step = _current_step()
    cols = st.columns(len(labels))
    for i, (col, label) in enumerate(zip(cols, labels)):
        if i < step:
            col.markdown(
                f"<p style='text-align:center;color:#21c55d;font-size:0.8rem;margin:0'>✓ {label}</p>",
                unsafe_allow_html=True,
            )
        elif i == step:
            col.markdown(
                f"<p style='text-align:center;font-weight:700;font-size:0.85rem;margin:0'>● {label}</p>",
                unsafe_allow_html=True,
            )
        else:
            col.markdown(
                f"<p style='text-align:center;color:#94a3b8;font-size:0.8rem;margin:0'>{label}</p>",
                unsafe_allow_html=True,
            )
    st.markdown("<hr style='margin:0.4rem 0 1.2rem'/>", unsafe_allow_html=True)


# ── Sidebar ────────────────────────────────────────────────────────────────────
with st.sidebar:
    st.header("Google Calendar")
    if st.session_state.gcal_service is None:
        st.caption("Connect to check scheduling conflicts and auto-sync bookings.")
        if st.button("Connect Google Calendar", use_container_width=True):
            try:
                with st.spinner("Opening browser for sign-in…"):
                    st.session_state.gcal_service = gcal.authenticate()
                st.success("Connected!")
                st.rerun()
            except Exception as e:
                st.error(f"Connection failed: {e}")
    else:
        gcal_col, disc_col = st.columns([3, 1])
        gcal_col.success("Connected")
        if disc_col.button("✕", help="Disconnect Google Calendar"):
            st.session_state.gcal_service = None
            st.rerun()
        st.markdown("**Today's events**")
        try:
            today_events = gcal.fetch_gcal_events(st.session_state.gcal_service)
            if today_events:
                for ev in today_events:
                    start = (ev.get("start") or {}).get("dateTime") or \
                            (ev.get("start") or {}).get("date", "")
                    label = start[11:16] if "T" in start else start
                    st.markdown(f"- **{label}** {ev.get('summary', 'Untitled')}")
            else:
                st.caption("No events today.")
        except Exception as e:
            st.warning(f"Could not load events: {e}")

    st.divider()
    st.subheader("My Bookings")
    if st.session_state.current_user:
        user_bookings = sorted(
            engine.get_user_bookings(st.session_state.current_user.id),
            key=lambda x: x.start_time,
            reverse=True,
        )
        if user_bookings:
            now = datetime.now()
            for b in user_bookings:
                lib = libraries.get(b.library_id)
                lib_name = lib.name if lib else b.library_id
                is_future = b.start_time >= now
                can_cancel = b.status == "confirmed" and is_future
                with st.container(border=True):
                    col_info, col_cancel = st.columns([5, 1])
                    with col_info:
                        st.markdown(
                            f"**{b.start_time.strftime('%b %d · %H:%M')}**  \n"
                            f"{b.purpose}"
                        )
                        st.caption(f"{lib_name}  \n`{b.confirmation_code or b.id}`")
                        if b.status == "confirmed":
                            st.caption("Status: Confirmed")
                        elif b.status == "cancelled":
                            st.caption("Status: Cancelled")
                        else:
                            st.caption(f"Status: {b.status.title()}")
                        if b.gcal_event_id:
                            st.caption("📅 In Google Calendar")
                    with col_cancel:
                        if can_cancel:
                            if st.button("✕", key=f"cancel_{b.id}", help="Cancel booking"):
                                if b.id:
                                    engine.cancel_booking(b.id, reason="User cancelled via app")
                                    if b.gcal_event_id and st.session_state.gcal_service:
                                        gcal.cancel_gcal_event(
                                            st.session_state.gcal_service, b.gcal_event_id
                                        )
                                st.rerun()
        else:
            st.caption("No bookings yet.")
    else:
        st.caption("Sign in to see your bookings.")


# ── Header ─────────────────────────────────────────────────────────────────────
st.title("📚 Library Room Booking")
st.caption("Reserve study rooms across campus libraries.")
_step_bar()


# ── Step 0: User identity ──────────────────────────────────────────────────────
with st.expander("Your Info", expanded=st.session_state.current_user is None):
    if st.session_state.current_user:
        u = st.session_state.current_user
        c1, c2 = st.columns([4, 1])
        c1.success(f"Signed in as **{u.name}** ({u.email})")
        if c2.button("Change", use_container_width=True):
            st.session_state.current_user = None
            st.session_state.available_slots = []
            st.session_state.search_executed = False
            st.session_state.selected_slot = None
            st.rerun()
    else:
        col_n, col_e = st.columns(2)
        user_name = col_n.text_input("Full name")
        user_email = col_e.text_input("Email")
        if st.button("Continue", type="primary"):
            if user_name and user_email:
                st.session_state.current_user = User(
                    id=user_email, name=user_name, email=user_email
                )
                st.rerun()
            else:
                st.warning("Enter your name and email to continue.")

if st.session_state.current_user is None:
    st.stop()


# ── Step 1: Library, date & preferences ───────────────────────────────────────
if not libraries:
    st.error("No libraries configured. Check libraries.json.")
    st.stop()

st.subheader("Search for a Room")

# ── AI natural-language search ─────────────────────────────────────────────────
with st.expander("✨ Describe what you need (AI Search)", expanded=False):
    ai_col, btn_col = st.columns([5, 1])
    ai_query = ai_col.text_input(
        "Tell me what you're looking for",
        placeholder="e.g. quiet room for 4 people tomorrow afternoon, needs a whiteboard",
        label_visibility="collapsed",
    )
    if btn_col.button("Parse", type="primary", use_container_width=True):
        with st.spinner("Thinking…"):
            _parsed, _err = ai_assistant.parse_booking_request(
                ai_query, today=date.today()
            )
        if _err:
            st.warning(f"AI: {_err}")
        elif not _parsed:
            help_msg = ai_assistant.suggest_booking_prompt(ai_query)
            st.info(help_msg)
        else:
            st.session_state.ai_parsed = _parsed
            st.success("Filters updated from your description — adjust below if needed.")
            st.rerun()

_ai = st.session_state.ai_parsed

left_col, right_col = st.columns([2, 3], gap="large")

with left_col:
    lib_names = [lib.name for lib in libraries.values()]
    selected_lib_name = st.selectbox("Library", lib_names)
    selected_library = next(lib for lib in libraries.values() if lib.name == selected_lib_name)

    with st.container(border=True):
        m1, m2, m3 = st.columns(3)
        m1.metric("Opens", selected_library.open_time)
        m2.metric("Closes", selected_library.close_time)
        m3.metric("Max", f"{selected_library.max_booking_duration_hours}h")
        open_days_str = " · ".join(selected_library.open_days)
        st.caption(
            f"📍 {selected_library.building} · {selected_library.campus} campus  \n"
            f"Open: {open_days_str}  \n"
            f"Book up to {selected_library.max_booking_days_ahead} days ahead · "
            f"Max {selected_library.max_bookings_per_user_per_day} booking(s)/day"
        )

with right_col:
    from datetime import timedelta as _td, time as _time

    # AI-suggested defaults (fall back to plain defaults when not set)
    _ai_date = (
        date.today() + _td(days=_ai["date_offset_days"])
        if "date_offset_days" in _ai else date.today()
    )
    _ai_capacity = int(_ai.get("min_capacity", 1))
    _open_h = int(selected_library.open_time.split(":")[0])
    _ai_start_h = int(_ai.get("earliest_start_hour", _open_h))

    dc1, dc2, dc3 = st.columns(3)
    with dc1:
        booking_date = st.date_input(
            "Date", value=_ai_date, min_value=date.today()
        )
    with dc2:
        max_h = selected_library.max_booking_duration_hours
        duration_opts = {
            f"{h}h" if h == int(h) else f"{h:.1f}h": int(h * 60)
            for h in [x * 0.5 for x in range(2, max_h * 2 + 1)]
        }
        _ai_dur = _ai.get("duration_minutes")
        _ai_dur_label = next(
            (lbl for lbl, mins in duration_opts.items() if mins == _ai_dur),
            list(duration_opts.keys())[0],
        )
        duration_label = st.selectbox(
            "Duration", list(duration_opts.keys()),
            index=list(duration_opts.keys()).index(_ai_dur_label),
        )
        duration_minutes = duration_opts[duration_label]
    with dc3:
        min_capacity = st.number_input(
            "Min seats", min_value=1, max_value=20, value=max(1, _ai_capacity)
        )

    tc1, tc2 = st.columns([1, 2])
    with tc1:
        earliest_start = st.time_input(
            "Earliest start time",
            value=_time(_ai_start_h, 0),
            step=1800,
        )
    with tc2:
        _amenity_choices = [f"{icon} {name}" for name, icon in _AMENITY_ICONS.items()]
        _ai_amenity_labels = [
            f"{_AMENITY_ICONS[a]} {a}"
            for a in _ai.get("amenities", [])
            if a in _AMENITY_ICONS
        ]
        amenity_labels = st.multiselect(
            "Required amenities", _amenity_choices, default=_ai_amenity_labels
        )
        amenity_options = [label.split(" ", 1)[1] for label in amenity_labels]
    filters = RoomFilters(
        min_capacity=min_capacity,
        duration_minutes=duration_minutes,
        amenities=amenity_options,
        accessible_only="Accessible" in amenity_options,
    )

    if st.button("Search Rooms", type="primary", use_container_width=True):
        with st.spinner(f"Checking availability at {selected_library.name}…"):
            try:
                st.session_state.available_slots = engine.fetch_availability(
                    selected_library.id, booking_date, filters
                )
                st.session_state.search_executed = True
                st.session_state.selected_slot = None
                st.session_state.last_gcal_link = None
            except Exception as e:
                st.error(f"Could not fetch availability: {e}")
                st.session_state.available_slots = []
                st.session_state.search_executed = True


# ── Step 2: Slot picker grouped by room ───────────────────────────────────────
if st.session_state.available_slots:
    from collections import defaultdict as _dd

    slots = [
        s for s in st.session_state.available_slots
        if s.start_time.time() >= earliest_start
    ]
    total_before_filter = len(st.session_state.available_slots)

    st.subheader(
        f"Available Rooms — {booking_date.strftime('%A, %b %d')}"
        + (f"  ·  from {earliest_start.strftime('%H:%M')}" if slots else "")
    )
    if total_before_filter > len(slots):
        st.caption(
            f"{total_before_filter - len(slots)} earlier slot(s) hidden — "
            "adjust 'Earliest start time' to see them."
        )
    if not slots:
        st.info("No slots from this time. Adjust 'Earliest start time' or pick a different date.")
    else:
        st.caption("Click a time button to select that slot.")
        rooms_map: dict = _dd(list)
        for s in slots:
            rooms_map[s.room_id].append(s)

        MAX_TIMES = 8  # buttons shown per room before overflow

        for room_id, room_slots in rooms_map.items():
            meta = room_slots[0].metadata
            room_num = room_id.split("-")[-1]
            capacity   = meta.get("capacity", "?")
            accessible = meta.get("accessible", False)
            floor      = meta.get("floor", "?")
            room_type  = meta.get("room_type", "study_room").replace("_", " ").title()
            amenities  = meta.get("amenities", [])
            amenity_icons = "  ".join(
                _AMENITY_ICONS[a] for a in amenities if a in _AMENITY_ICONS
            )
            dur_label = (
                f"{room_slots[0].duration_minutes // 60}h"
                if room_slots[0].duration_minutes % 60 == 0
                else f"{room_slots[0].duration_minutes} min"
            )

            sel_in_room = (
                st.session_state.selected_slot is not None
                and st.session_state.selected_slot.room_id == room_id
            )
            border = "#16a34a" if sel_in_room else "#e2e8f0"
            bg     = "#f0fdf4" if sel_in_room else "#f8fafc"

            # Room header
            st.markdown(
                f"<div style='border:2px solid {border};border-radius:10px;"
                f"padding:0.65rem 1rem 0.35rem;background:{bg};margin-bottom:0.15rem'>"
                f"<span style='font-weight:700;font-size:1rem;color:#000000'>Room {room_num}"
                f"{'&ensp;♿' if accessible else ''}</span>"
                f"<span style='color:#64748b;font-size:0.82rem;margin-left:0.6rem'>"
                f"{room_type}&nbsp;·&nbsp;Floor {floor}&nbsp;·&nbsp;{capacity} seats"
                f"&nbsp;·&nbsp;{dur_label} slots"
                f"{'&ensp;' + amenity_icons if amenity_icons else ''}"
                f"</span>"
                f"</div>",
                unsafe_allow_html=True,
            )

            # Time buttons
            display = room_slots[:MAX_TIMES]
            overflow = len(room_slots) - len(display)
            n_cols = len(display) + (1 if overflow else 0)
            time_cols = st.columns(n_cols)

            for tc, s in zip(time_cols, display):
                is_sel = (
                    st.session_state.selected_slot is not None
                    and st.session_state.selected_slot.id == s.id
                )
                end_str   = s.end_time.strftime("%H:%M")
                start_str = s.start_time.strftime("%H:%M")
                btn_label = f"✓ {start_str}" if is_sel else start_str
                if tc.button(
                    btn_label,
                    key=f"slot_{s.id}",
                    type="primary" if is_sel else "secondary",
                    use_container_width=True,
                    help=f"{start_str} – {end_str}  ({s.duration_minutes} min)",
                ):
                    st.session_state.selected_slot = s
                    st.rerun()

            if overflow:
                time_cols[-1].caption(f"+{overflow} more\n(adjust start time)")

            st.markdown("<div style='margin-bottom:0.5rem'></div>", unsafe_allow_html=True)

elif st.session_state.search_executed:
    st.info(
        "No rooms match your filters. Try a different date, duration, "
        "an earlier start time, or fewer amenity requirements."
    )


# ── Step 3: Review & Book ──────────────────────────────────────────────────────
if st.session_state.selected_slot:
    slot = st.session_state.selected_slot
    st.divider()
    st.subheader("Review & Book")

    # Conflict check
    gcal_events: list = []
    if st.session_state.gcal_service:
        try:
            gcal_events = gcal.fetch_gcal_events(
                st.session_state.gcal_service, target_date=slot.start_time.date()
            )
        except Exception:
            pass
    else:
        st.caption("Connect Google Calendar (sidebar) to check for scheduling conflicts.")

    conflict = engine.check_conflicts(
        slot, gcal_events, selected_library,
        user_id=st.session_state.current_user.id,
    )
    for blocker in conflict.blockers:
        st.error(f"Blocked: {blocker}")
    for warning in conflict.warnings:
        st.warning(warning)

    if conflict.blockers and st.session_state.available_slots:
        with st.spinner("Finding alternatives…"):
            suggestion = ai_assistant.suggest_alternative(
                conflict.blockers,
                st.session_state.available_slots,
                selected_library.name,
            )
        if suggestion:
            st.info(f"✨ **AI Suggestion:** {suggestion}")

    if not conflict.blockers:
        meta = slot.metadata
        room_num = slot.room_id.split("-")[-1]
        amenities = meta.get("amenities", [])
        amenity_str = "  ".join(
            f"{_AMENITY_ICONS.get(a, '')} {a}" for a in amenities
        ) or "None"

        # Summary card
        with st.container(border=True):
            sc1, sc2 = st.columns(2)
            with sc1:
                st.markdown("**Booking Summary**")
                st.markdown(
                    f"**Room:** Room {room_num}  \n"
                    f"**Library:** {selected_library.name}  \n"
                    f"**Building:** {selected_library.building}  \n"
                    f"**Floor:** {meta.get('floor', '?')}  \n"
                    f"**Capacity:** {meta.get('capacity', '?')} seats"
                )
            with sc2:
                st.markdown("&nbsp;", unsafe_allow_html=True)
                st.markdown(
                    f"**Date:** {slot.start_time.strftime('%A, %B %d %Y')}  \n"
                    f"**Time:** {slot.start_time.strftime('%H:%M')} – {slot.end_time.strftime('%H:%M')}  \n"
                    f"**Duration:** {slot.duration_minutes} min  \n"
                    f"**Amenities:** {amenity_str}"
                )

        purpose = st.text_input("Purpose (e.g. group project, solo study)")
        notes = st.text_area("Notes (optional)", height=70)

        btn_col, dry_col = st.columns([3, 1])
        with dry_col:
            dry_run = st.checkbox("Dry run", help="Validate without submitting")
        with btn_col:
            if st.button("Confirm Booking", type="primary", use_container_width=True):
                with st.spinner("Submitting booking…"):
                    result, booking = engine.book_room(
                        slot,
                        st.session_state.current_user,
                        purpose=purpose or "Study",
                        notes=notes or None,
                        dry_run=dry_run,
                    )

                if result.success:
                    if dry_run:
                        st.info("Dry run passed — booking would succeed.")
                    else:
                        st.success(
                            f"Room booked! Confirmation: `{result.confirmation_code}`"
                        )
                        if st.session_state.gcal_service and booking:
                            with st.spinner("Syncing to Google Calendar…"):
                                cal_link = gcal.sync_booking_to_gcal(
                                    st.session_state.gcal_service,
                                    booking,
                                    selected_library,
                                )
                            if cal_link:
                                st.session_state.last_gcal_link = cal_link
                                if booking.id and booking.gcal_event_id:
                                    engine.update_gcal_event_id(booking.id, booking.gcal_event_id)
                                st.success(f"[📅 View in Google Calendar]({cal_link})")
                            else:
                                st.warning(
                                    "Booking confirmed but Google Calendar sync failed. "
                                    "Check your connection and try reconnecting."
                                )
                        else:
                            st.info(
                                "Connect Google Calendar (sidebar) to sync this booking "
                                "to your calendar."
                            )
                        st.session_state.selected_slot = None
                        st.session_state.available_slots = []
                        st.session_state.search_executed = False
                        st.rerun()
                else:
                    st.error(
                        f"Booking failed: {result.message} (code: {result.error_code})"
                    )
