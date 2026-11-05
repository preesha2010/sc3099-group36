"""
The review queue.

This is the screen the whole risk-scoring pipeline exists to feed. A flagged
check-in is not an accusation, it is a request for a human decision, so the
job here is to show *why* it was flagged clearly enough that the decision
takes seconds.
"""
from __future__ import annotations

from html import escape

import pandas as pd
import streamlit as st

from app import api, clock, tables, theme

# Plain-English readings of the risk signal types the backend emits.
EXPLAIN = {
    "geo_out_of_bounds": "Outside the venue geofence",
    "geo_accuracy_low": "Location fix was imprecise or missing",
    "impossible_travel": "Moved further than physically possible since the last check-in",
    "device_unknown": "Device not registered to this student",
    "device_emulator": "Device looks like an emulator",
    "device_rooted": "Device is rooted or jailbroken",
    "rapid_succession": "Another check-in seconds earlier",
    "liveness_failed": "Liveness check failed",
    "liveness_low_confidence": "Liveness was not performed",
    "face_match_failed": "Face did not match the enrolled template",
    "face_match_low_confidence": "Face match was borderline",
    "vpn_detected": "Connection looks like a VPN",
    "proxy_detected": "Connection looks like a proxy",
}

SEVERITY_COLOR = {
    "low": theme.NEUTRAL, "medium": theme.WARNING,
    "high": theme.CRITICAL, "critical": theme.CRITICAL,
}


def render() -> None:
    st.subheader("Review")

    courses = st.session_state.get("courses", [])
    labels = ["All courses"] + [f"{c['code']} · {c['name']}" for c in courses]
    choice = st.selectbox("Course", labels, key="rev_course")
    params = {}
    if choice != "All courses":
        params["course_id"] = courses[labels.index(choice) - 1]["id"]

    page = api.flagged(**params)
    queue = _complete(page["items"], courses)
    total = page["total"] - (len(page["items"]) - len(queue))
    if not queue:
        st.success("Nothing waiting. Every check-in has been decided.")
        return

    if total > len(queue):
        st.caption(f"Showing the {len(queue)} highest risk of {total} awaiting "
                   "a decision.")
    else:
        st.caption(f"{total} awaiting a decision, highest risk first.")

    _queue_table(queue)

    for item in queue:
        _card(item)


def _queue_table(queue: list) -> None:
    """The whole queue on one screen, with the same badge colours as the cards."""
    frame = pd.DataFrame([{
        "Student": item.get("student_name") or "Unknown student",
        "Session": item.get("session_name") or "",
        "Course": item.get("course_code") or "",
        "Time": clock.fmt(item.get("checked_in_at")),
        "Risk": f"{item['risk_score']:.2f}",
        "Risk band": _level_text((item.get("risk_level") or "HIGH").upper()),
        "Status": theme.status_label(item["status"]),
    } for item in queue])
    styled = (frame.style
              .map(theme.checkin_cell_style, subset=["Status"])
              .map(_band_cell_style, subset=["Risk band"]))
    tables.show(styled)


def _band_cell_style(value: str) -> str:
    word = str(value).split(" ")[1].upper() if " " in str(value) else ""
    fill, ink, _ = theme.TONE[theme.RISK_LEVEL_TONE.get(word, "neutral")]
    return f"background-color: {fill}; color: {ink}; font-weight: 600"


def _card(item: dict) -> None:
    with st.container(border=True):
        head, score = st.columns([4, 1])
        with head:
            st.markdown(
                f"**{escape(item.get('student_name') or 'Unknown student')}**  \n"
                f"<span style='color:{theme.INK_MUTED};font-size:0.82rem'>"
                f"{escape(item.get('student_email') or '')}</span>  \n"
                f"<span style='color:{theme.INK_SECONDARY};font-size:0.82rem'>"
                f"{escape(item.get('session_name') or 'Session')} · "
                f"{item.get('course_code') or ''} · "
                f"{clock.fmt(item.get('checked_in_at'))}</span>",
                unsafe_allow_html=True)
        with score:
            level = (item.get("risk_level") or "HIGH").upper()
            tone = theme.RISK_LEVEL_TONE.get(level, "warning")
            st.markdown(
                f"<div style='text-align:right'>"
                f"<div style='font-size:1.5rem;font-weight:700;"
                f"color:{theme.TONE[tone][1]}'>{item['risk_score']:.2f}</div>"
                f"<div style='font-size:0.72rem;color:{theme.INK_MUTED}'>risk score</div>"
                f"</div>", unsafe_allow_html=True)

        # Status and risk band as badges, so the state reads at a glance and
        # never by colour alone (each badge carries an icon and a word).
        st.markdown(
            f"<div style='display:flex;gap:6px;flex-wrap:wrap;margin:2px 0 6px'>"
            f"{theme.checkin_badge(item['status'])}"
            f"{theme.badge(_level_text(level), tone)}</div>",
            unsafe_allow_html=True)

        # Why it was flagged. Without this the instructor is guessing, and a
        # queue you have to guess at is a queue nobody clears.
        factors = item.get("risk_factors") or []
        if factors:
            st.markdown("<div style='margin:6px 0 2px'>", unsafe_allow_html=True)
            for factor in factors:
                colour = SEVERITY_COLOR.get(factor.get("severity", "medium"),
                                            theme.WARNING)
                st.markdown(
                    f"<div style='font-size:0.82rem;color:{theme.INK_SECONDARY};"
                    f"padding:1px 0'>"
                    f"<span style='color:{colour};font-weight:700'>▪</span> "
                    f"{EXPLAIN.get(factor['type'], factor['type'].replace('_', ' '))}"
                    f"<span style='color:{theme.INK_MUTED}'> "
                    f"({factor.get('severity', '')}, weight "
                    f"{factor.get('weight', 0):.2f})</span></div>",
                    unsafe_allow_html=True)
            st.markdown("</div>", unsafe_allow_html=True)

        evidence = st.columns(3)
        evidence[0].metric("Distance",
                           f"{item['distance_from_venue_meters']:.0f} m"
                           if item.get("distance_from_venue_meters") is not None else "—")
        evidence[1].metric("Liveness",
                           "passed" if item.get("liveness_passed")
                           else "failed" if item.get("liveness_passed") is False else "—")
        evidence[2].metric("Face match",
                           "matched" if item.get("face_match_passed")
                           else "no match" if item.get("face_match_passed") is False else "—")

        if item.get("appeal_reason"):
            st.info(f"**Student's appeal:** {item['appeal_reason']}")

        notes = st.text_input("Note (optional)", key=f"note-{item['id']}",
                              placeholder="What decided it")
        approve, reject = st.columns(2)
        if approve.button("Approve", key=f"ok-{item['id']}",
                          use_container_width=True, type="primary"):
            _decide(item, "approved", notes)
        if reject.button("Reject", key=f"no-{item['id']}", use_container_width=True):
            _decide(item, "rejected", notes)


def _complete(items: list, courses: list) -> list:
    """
    Bring every queue item up to what the cards show, and keep only the
    courses this user can act on.

    The API spec's flagged items carry course_code, student_email,
    risk_level and the evidence (distance, liveness, face match). Backends
    that return a slimmer item get the evidence filled from the check-in
    detail endpoint, the course from the session list, and the risk band
    from the score.

    Items from courses outside the user's list are dropped. The review
    itself is refused by the backend for those anyway, so showing them only
    offers buttons that fail, and it shows student names and appeal text to
    staff who do not teach that course.
    """
    if not items:
        return items
    allowed = {c["id"] for c in courses}
    by_session = {s["id"]: s for s in api.sessions()["items"]}

    kept = []
    for item in items:
        session = by_session.get(item.get("session_id"))
        if session is not None and session.get("course_id") not in allowed:
            continue
        if session is not None:
            item.setdefault("course_code", session.get("course_code"))
        if not item.get("risk_level"):
            # A critical or high factor outranks the score: the backend
            # rejects on a critical factor (say, 2 km from the venue) even
            # when the weighted score is small, and calling that "low risk"
            # would invite the wrong decision.
            severities = {f.get("severity") for f in item.get("risk_factors") or []}
            score = item.get("risk_score") or 0.0
            if "critical" in severities:
                item["risk_level"] = "CRITICAL"
            elif "high" in severities or score >= 0.5:
                item["risk_level"] = "HIGH"
            else:
                item["risk_level"] = "MEDIUM" if score >= 0.3 else "LOW"
        if "distance_from_venue_meters" not in item:
            try:
                detail = api.checkin(item["id"])
            except api.ApiError:
                detail = {}
            for key in ("distance_from_venue_meters", "liveness_passed",
                        "face_match_passed"):
                item.setdefault(key, detail.get(key))
        kept.append(item)
    return kept


def _level_text(level: str) -> str:
    icon = {"LOW": "✓", "MEDIUM": "!", "HIGH": "✕", "CRITICAL": "✕"}.get(level, "!")
    return f"{icon} {level.capitalize()} risk"


def _decide(item: dict, status: str, notes: str) -> None:
    try:
        api.review(item["id"], status, notes)
        st.toast(f"{item.get('student_name', 'Check-in')} {status}")
        st.rerun()
    except api.ApiError as exc:
        st.error(exc.detail)
