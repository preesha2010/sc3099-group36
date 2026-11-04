"""Session management: create, open, close, cancel."""
from __future__ import annotations

from datetime import datetime, time, timedelta

import pandas as pd
import streamlit as st

from app import api, clock, theme

# Moves offered from each state: (target, label, forced).
#
# Normal moves follow the backend workflow (scheduled -> active -> closed,
# or cancelled) and go through PATCH /sessions/{id}, which the course's
# instructor is allowed to call. Forced moves (reopen, restore) break that
# workflow on purpose, so they go through the admin override and are only
# shown to admins. Offering them to an instructor would just produce a 403.
NEXT_STATES = {
    "scheduled": [("active", "Open check-in", False), ("cancelled", "Cancel", False)],
    "active": [("closed", "Close check-in", False), ("cancelled", "Cancel", False)],
    "closed": [("active", "Reopen", True)],
    "cancelled": [("scheduled", "Restore", True)],
}


def render() -> None:
    st.subheader("Sessions")
    courses = st.session_state.get("courses", [])
    if not courses:
        st.info("No courses yet. An admin creates courses.")
        return

    labels = [f"{c['code']} · {c['name']}" for c in courses]
    course = courses[labels.index(st.selectbox("Course", labels, key="sess_course"))]

    tab_manage, tab_create = st.tabs(["Manage", "Create"])
    with tab_manage:
        _manage(course)
    with tab_create:
        _create(course)


def _manage(course: dict) -> None:
    listing = api.sessions(course_id=course["id"])["items"]
    if not listing:
        st.info("No sessions for this course yet. Create one in the next tab.")
        return

    open_now = [s for s in listing if s["status"] == "active"]
    if open_now:
        st.success(f"{len(open_now)} session"
                   f"{'s are' if len(open_now) != 1 else ' is'} open for check-in.")

    for session in listing:
        with st.container(border=True):
            head, actions = st.columns([3, 2])
            with head:
                st.markdown(
                    f"**{session['name']}**  \n"
                    f"<span style='color:{theme.INK_MUTED};font-size:0.82rem'>"
                    f"{clock.fmt(session['scheduled_start'])} · "
                    f"{session.get('venue_name') or 'no venue'}</span>  \n"
                    f"{theme.session_badge(session['status'])}"
                    f"<span style='color:{theme.INK_MUTED};font-size:0.82rem'> · "
                    f"{session.get('checked_in_count') or 0} of "
                    f"{session.get('total_enrolled') or 0} checked in</span>",
                    unsafe_allow_html=True)
            with actions:
                is_admin = (st.session_state.get("user") or {}).get("role") == "admin"
                moves = [m for m in NEXT_STATES.get(session["status"], [])
                         if is_admin or not m[2]]
                if not moves:
                    st.caption("No further changes. An admin can reopen it.")
                for column, (target, label, forced) in zip(st.columns(len(moves) or 1), moves):
                    if column.button(label, key=f"mv-{session['id']}-{target}",
                                     use_container_width=True):
                        try:
                            api.set_session_status(session["id"], target, force=forced)
                            st.toast(f"{session['name']} is now {target}")
                            st.rerun()
                        except api.ApiError as exc:
                            st.error(exc.detail)

            window = (f"{clock.fmt(session['checkin_opens_at'], '%H:%M')} to "
                      f"{clock.fmt(session['checkin_closes_at'], '%H:%M')}")
            requires = []
            if session.get("require_liveness_check"):
                requires.append("liveness")
            if session.get("require_face_match"):
                requires.append("face match")
            st.caption(f"Check-in window {window}"
                       + (f" · requires {' and '.join(requires)}" if requires else ""))


def _create(course: dict) -> None:
    with st.form("create_session"):
        name = st.text_input("Session name", placeholder="Lecture 6: Testing")
        columns = st.columns(2)
        session_type = columns[0].selectbox("Type",
                                            ["lecture", "tutorial", "lab", "exam"])
        day = columns[1].date_input("Date", value=clock.now().date())

        columns = st.columns(2)
        starts = columns[0].time_input("Starts", value=time(9, 30))
        ends = columns[1].time_input("Ends", value=time(11, 20))
        st.caption(f"Times are in {clock.ZONE_NAME}.")

        columns = st.columns(2)
        open_before = columns[0].number_input("Check-in opens (min before)",
                                              0, 120, 15)
        close_after = columns[1].number_input("Check-in closes (min after start)",
                                              5, 180, 30)

        columns = st.columns(2)
        liveness = columns[0].checkbox("Require liveness check", value=True)
        face_match = columns[1].checkbox("Require face match", value=False)
        threshold = st.slider("Risk threshold", 0.0, 1.0, 0.5, 0.05,
                              help="Check-ins at or above this are flagged for review")

        submitted = st.form_submit_button("Create session", use_container_width=True)

    if not submitted:
        return
    if not name.strip():
        st.error("Give the session a name.")
        return

    # Typed times are local wall-clock time in SAIV_TZ. The API stores UTC,
    # so clock.to_api converts them rather than sending them as-is and
    # landing hours off.
    start = datetime.combine(day, starts)
    end = datetime.combine(day, ends)
    if end <= start:
        st.error("The end time has to be after the start time.")
        return

    stamp = clock.to_api
    try:
        created = api.create_session({
            "course_id": course["id"],
            "name": name.strip(),
            "session_type": session_type,
            "scheduled_start": stamp(start),
            "scheduled_end": stamp(end),
            "checkin_opens_at": stamp(start - timedelta(minutes=int(open_before))),
            "checkin_closes_at": stamp(start + timedelta(minutes=int(close_after))),
            "require_liveness_check": liveness,
            "require_face_match": face_match,
            "risk_threshold": threshold,
        })
        st.success(f"Created **{created['name']}**. It starts as *scheduled*; "
                   "open check-in from the Manage tab when the class begins.")
    except api.ApiError as exc:
        st.error(exc.detail)
