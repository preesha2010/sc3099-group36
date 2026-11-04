"""
Landing view.

Information hierarchy, per the module 4 design guidance: the numbers that
demand action sit top-left and read at a glance, trends sit below them, and
the detail is one click further down. An instructor opening this between
lectures should get the answer to "is anything wrong" without scrolling.
"""
from __future__ import annotations

from datetime import datetime, time, timedelta
from html import escape

import streamlit as st

from app import api, clock, theme
from app.views import charts

# Colour thresholds for the headline cards. Kept here, in one place, so the
# group can argue about the numbers without touching the rendering.
APPROVAL_GOOD = 0.80        # at or above: green
APPROVAL_WARN = 0.60        # at or above: amber; below: red
REVIEW_RED_AT = 5           # 1 to 4 waiting: amber; this many or more: red


def render() -> None:
    st.subheader("Overview")

    courses = st.session_state.get("courses", [])
    labels = ["All courses"] + [f"{c['code']} · {c['name']}" for c in courses]
    pick_course, pick_days = st.columns([3, 1])
    choice = pick_course.selectbox("Course", labels, key="overview_course")
    course_id = None if choice == "All courses" else courses[labels.index(choice) - 1]["id"]

    # A dropdown, not a slider: three fixed choices read better as a list,
    # and the slider's end labels crowded the cards underneath it.
    days = pick_days.selectbox("Trend window", [7, 14, 30], index=0,
                               format_func=lambda d: f"Last {d} days",
                               key="overview_days")

    params = {"days": days}
    if course_id:
        params["course_id"] = course_id
    data = api.stats_overview(**params)

    # --- The four numbers that matter -------------------------------------
    flagged = data["flagged_pending"]
    window_total = sum(p.get("count", 0) for p in data["trends"]["checkins_by_day"])
    st.markdown(theme.kpi_grid([
        {"label": "Active sessions", "value": data["active_sessions"],
         "foot": "open for check-in now"},
        {"label": "Check-ins today", "value": data["today_checkins"],
         "foot": "all courses" if not course_id else "this course"},
        _review_card(flagged),
        _approval_card(data["approval_rate"], window_total),
    ]), unsafe_allow_html=True)

    if flagged >= REVIEW_RED_AT:
        st.error(f"**{flagged}** check-ins waiting on a decision. "
                 "Open **Review** to clear the queue.")
    elif flagged:
        st.warning(
            f"**{flagged}** check-in{'s' if flagged != 1 else ''} "
            "waiting on a decision. Open **Review** to clear the queue."
        )

    st.divider()

    left, right = st.columns([3, 2])
    with left:
        charts.trend_line(
            data["trends"]["checkins_by_day"],
            "Check-ins per day",
            f"Last {days} days" + ("" if course_id else ", all courses"),
        )
    with right:
        _today_sessions(course_id)

    st.markdown('<p class="saiv-chart-title">System</p>'
                '<p class="saiv-chart-sub">Averages across the window</p>',
                unsafe_allow_html=True)
    st.markdown(theme.kpi_grid([
        {"label": "Average risk score", "value": f"{data['average_risk_score']:.2f}",
         "foot": "0 is clean, 1 is certain fraud"},
        {"label": "High risk today", "value": data["high_risk_checkins_today"],
         "foot": "risk score 0.5 or above"},
        {"label": "Sessions", "value": data["total_sessions"], "foot": "all time"},
        {"label": "Students", "value": data["total_students"], "foot": "enrolled"},
    ]).replace('class="saiv-kpis"', 'class="saiv-kpis compact"'),
        unsafe_allow_html=True)

    st.divider()
    _service_health()


def _review_card(flagged: int) -> dict:
    """Green when the queue is empty, amber when it is not, red when it piles up."""
    if flagged == 0:
        return {"label": "Needs review", "value": 0,
                "foot": "✓ All clear", "tone": "good"}
    if flagged >= REVIEW_RED_AT:
        return {"label": "Needs review", "value": flagged,
                "foot": "✕ Backlog building", "tone": "critical"}
    return {"label": "Needs review", "value": flagged,
            "foot": "! Action required", "tone": "warning"}


def _approval_card(rate: float, window_total: int) -> dict:
    """
    Green when most check-ins pass. With no check-ins in the window the rate
    is meaningless, so it stays uncoloured rather than reading as a red 0%.
    """
    if not window_total:
        return {"label": "Approval rate", "value": "—",
                "foot": "no check-ins in this window"}
    value = f"{rate:.0%}"
    if rate >= APPROVAL_GOOD:
        return {"label": "Approval rate", "value": value,
                "foot": "✓ Healthy", "tone": "good"}
    if rate >= APPROVAL_WARN:
        return {"label": "Approval rate", "value": value,
                "foot": f"! Below {APPROVAL_GOOD:.0%}", "tone": "warning"}
    return {"label": "Approval rate", "value": value,
            "foot": f"✕ Below {APPROVAL_WARN:.0%}", "tone": "critical"}


def _today_sessions(course_id: str | None) -> None:
    """
    What is on today, by name and time, not just a count.

    "Today" is the local day in SAIV_TZ, the same clock the Create session
    form uses, converted to the UTC range the API filters on.
    """
    today = clock.now().date()
    start = datetime.combine(today, time.min)
    end = start + timedelta(days=1) - timedelta(seconds=1)

    params = {"start_date": clock.to_api(start), "end_date": clock.to_api(end)}
    if course_id:
        params["course_id"] = course_id
    try:
        listing = api.sessions(**params)["items"]
    except api.ApiError as exc:
        st.error(f"Could not load today's sessions: {exc.detail}")
        return

    listing.sort(key=lambda s: s["scheduled_start"])
    st.markdown(
        '<p class="saiv-chart-title">Today\'s sessions</p>'
        f'<p class="saiv-chart-sub">{today:%a %d %b} ({clock.ZONE_NAME}) · {len(listing)} '
        f'session{"s" if len(listing) != 1 else ""}</p>',
        unsafe_allow_html=True)

    if not listing:
        st.caption("Nothing scheduled today.")
        return

    rows = []
    for s in listing:
        begins, ends = clock.parse(s["scheduled_start"]), clock.parse(s["scheduled_end"])
        meta = " · ".join(escape(x) for x in
                          (s.get("course_code"), s.get("venue_name")) if x)
        rows.append(
            "<li>"
            f'<div><div class="t">{begins:%H:%M} to {ends:%H:%M}</div>'
            f'<div class="n">{escape(s["name"])}</div>'
            f'<div class="m">{meta}</div></div>'
            f'<div class="r">{theme.session_badge(s["status"])}'
            f'<div class="c">{s.get("checked_in_count") or 0} of '
            f'{s.get("total_enrolled") or 0} in</div></div>'
            "</li>")
    st.markdown(f'<div class="saiv-card" style="padding:6px 16px">'
                f'<ul class="saiv-today">{"".join(rows)}</ul></div>',
                unsafe_allow_html=True)


def _service_health() -> None:
    """
    Whether the pieces behind the dashboard are actually up.

    Worth surfacing: if the face service is down, check-ins still succeed
    but liveness and face match come back unknown, so attendance quietly
    starts looking riskier than it is. An instructor seeing a spike in
    flagged check-ins should be able to tell that apart from a spike in
    actual fraud.
    """
    st.markdown('<p class="saiv-chart-title">Service health</p>',
                unsafe_allow_html=True)
    try:
        health = api.health()
    except api.ApiError as exc:
        st.error(f"Backend unreachable: {exc.detail}")
        return

    columns = st.columns(4)
    for column, (label, key) in zip(columns, [
        ("API", "api"), ("Database", "database"),
        ("Cache", "redis"), ("Face service", "face_service"),
    ]):
        value = str(health.get(key, "unknown"))
        up = value in ("ok", "connected")
        column.markdown(
            f'<div class="saiv-card" style="text-align:center">'
            f'<div style="font-size:1.1rem;color:'
            f'{theme.GOOD if up else theme.WARNING}">{"✓" if up else "!"}</div>'
            f'<div style="font-size:0.75rem;color:{theme.INK_SECONDARY}">{label}</div>'
            f'<div style="font-size:0.7rem;color:{theme.INK_MUTED}">{value}</div>'
            f'</div>', unsafe_allow_html=True)

    if health.get("face_service") != "connected":
        st.info(
            "The face service is not answering. Check-ins still work, but "
            "liveness and face match come back unknown, which pushes risk "
            "scores up and will flag more check-ins than usual."
        )
