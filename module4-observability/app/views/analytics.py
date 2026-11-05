"""Course and session analytics."""
from __future__ import annotations

import pandas as pd
import streamlit as st

from app import api, clock, tables, theme
from app.views import charts

LOW_ATTENDANCE = 0.6


def render() -> None:
    st.subheader("Analytics")
    courses = st.session_state.get("courses", [])
    if not courses:
        st.info("No courses assigned to you yet. An admin assigns instructors to courses.")
        return

    labels = [f"{c['code']} · {c['name']}" for c in courses]
    course = courses[labels.index(st.selectbox("Course", labels, key="an_course"))]

    tab_course, tab_session = st.tabs(["Course", "Session"])
    with tab_course:
        _course_view(course)
    with tab_session:
        _session_view(course)


def _course_view(course: dict) -> None:
    data = api.stats_course(course["id"])

    columns = st.columns(4)
    columns[0].metric("Enrolled", data["total_enrolled"])
    columns[1].metric("Sessions held", data["total_sessions"])
    columns[2].metric("Attendance", f"{data['average_attendance_rate']:.0%}")
    columns[3].metric("Flagged", data["flagged_checkins"])

    st.divider()
    charts.attendance_bars(data["sessions"], "Attendance by session",
                           "Share of enrolled students who checked in")

    alerts = data["low_attendance_alerts"]
    st.markdown('<p class="saiv-chart-title">Students needing attention</p>'
                f'<p class="saiv-chart-sub">Below {LOW_ATTENDANCE:.0%} attendance</p>',
                unsafe_allow_html=True)
    if not alerts:
        st.success("Every enrolled student is above the threshold.")
    else:
        frame = pd.DataFrame(alerts)
        frame["attendance_rate"] = frame["attendance_rate"].map(lambda v: f"{v:.0%}")
        tables.show(frame.rename(columns={
            "student_name": "Student", "attendance_rate": "Attendance",
            "sessions_missed": "Sessions missed", "student_id": "ID",
        })[["Student", "Attendance", "Sessions missed"]])

    with st.expander("Every student"):
        frame = pd.DataFrame(data["student_attendance"])
        if len(frame):
            frame["attendance_rate"] = frame["attendance_rate"].map(lambda v: f"{v:.0%}")
            frame["average_risk_score"] = frame["average_risk_score"].map(lambda v: f"{v:.2f}")
            tables.show(frame.rename(columns={
                "student_name": "Student", "sessions_attended": "Attended",
                "attendance_rate": "Attendance", "average_risk_score": "Avg risk",
            })[["Student", "Attended", "Attendance", "Avg risk"]])


def _session_view(course: dict) -> None:
    listing = api.sessions(course_id=course["id"])["items"]
    if not listing:
        st.info("This course has no sessions yet.")
        return

    labels = [f"{s['name']} · {clock.fmt(s['scheduled_start'], '%Y-%m-%d')} · {s['status']}"
              for s in listing]
    session = listing[labels.index(st.selectbox("Session", labels, key="an_session"))]
    data = api.stats_session(session["id"])
    rows = api.session_checkins(session["id"])
    _fill_session_stats(data, rows, session)

    columns = st.columns(4)
    columns[0].metric("Enrolled", data["total_enrolled"])
    columns[1].metric("Checked in", data["checked_in_count"])
    columns[2].metric("Attendance", f"{data['attendance_rate']:.0%}")
    columns[3].metric("Average risk", f"{data['average_risk_score']:.2f}")

    st.divider()
    charts.status_composition(data["by_status"], "Check-in outcomes",
                              f"{data['checked_in_count']} of "
                              f"{data['total_enrolled']} enrolled")

    left, right = st.columns(2)
    with left:
        charts.risk_bars(data["risk_distribution"], "Risk distribution",
                         "How many check-ins fell in each band")
    with right:
        charts.arrival_timeline(data["checkin_timeline"], "When people arrived",
                                _average_arrival(data["average_checkin_time_minutes"]))

    st.markdown('<p class="saiv-chart-title">Who checked in</p>',
                unsafe_allow_html=True)
    if not rows:
        st.caption("Nobody has checked in yet.")
        return
    frame = pd.DataFrame([{
        "Student": r.get("student_name"),
        "Email": r.get("student_email"),
        "Status": theme.status_label(r["status"]),
        "Time": clock.fmt(r["checked_in_at"], "%H:%M"),
        "Distance": (f"{r['distance_from_venue_meters']:.0f} m"
                     if r.get("distance_from_venue_meters") is not None else "—"),
        "Liveness": ("passed" if r.get("liveness_passed")
                     else "failed" if r.get("liveness_passed") is False else "—"),
        "Face": ("matched" if r.get("face_match_passed")
                 else "no match" if r.get("face_match_passed") is False else "—"),
        "Risk": f"{r['risk_score']:.2f}",
    } for r in rows])
    tables.show(frame.style.map(theme.checkin_cell_style, subset=["Status"]))


def _fill_session_stats(data: dict, rows: list, session: dict) -> None:
    """
    Fill in whatever the session stats endpoint leaves out, from the
    check-in rows the view loads anyway.

    The API spec's session stats carry risk_distribution, checkin_timeline
    and average_checkin_time_minutes; not every backend returns them, and
    by_status may leave out "appealed". Computed here from the same rows the
    table shows, so the charts and the table can never disagree.
    """
    by_status = {}
    for row in rows:
        by_status[row["status"]] = by_status.get(row["status"], 0) + 1
    if rows or not data.get("by_status"):
        data["by_status"] = by_status

    if "risk_distribution" not in data:
        bands = {"low": 0, "medium": 0, "high": 0}
        for row in rows:
            score = row.get("risk_score") or 0.0
            bands["low" if score < 0.3 else "medium" if score < 0.5 else "high"] += 1
        data["risk_distribution"] = bands

    if "checkin_timeline" not in data or "average_checkin_time_minutes" not in data:
        # Same convention as the backend: minutes from the scheduled start,
        # negative for early arrivals, five minute buckets by floor, so a
        # check-in 3 minutes early lands in the -5 bucket.
        start = clock.parse(session.get("scheduled_start"))
        minutes = []
        for row in rows:
            at = clock.parse(row.get("checked_in_at"))
            if start and at:
                minutes.append((at - start).total_seconds() / 60)
        buckets = {}
        for m in minutes:
            key = int(m // 5) * 5
            buckets[key] = buckets.get(key, 0) + 1
        data.setdefault("checkin_timeline",
                        [{"minute": k, "count": v} for k, v in sorted(buckets.items())])
        data.setdefault("average_checkin_time_minutes",
                        sum(minutes) / len(minutes) if minutes else 0.0)

    data.setdefault("checked_in_count", data.get("checked_in", len(rows)))
    data.setdefault("average_risk_score", 0.0)


def _average_arrival(minutes: float) -> str:
    """Average arrival relative to the scheduled start, in words."""
    whole = round(minutes or 0)
    if whole < 0:
        return f"On average {-whole} min early"
    if whole == 0:
        return "On average right on time"
    return f"On average {whole} min after the start"
