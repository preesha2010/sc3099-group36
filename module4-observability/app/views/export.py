"""
Export for the gradebook.

The bytes come straight from the backend's export endpoints rather than
being rebuilt here from JSON. Two reasons: the backend already writes the
CSV with a proper writer and a UTF-8 BOM so Excel on Windows does not
mangle names, and every export it serves writes a `data_exported` audit
row. Assembling the file in the dashboard would lose both.
"""
from __future__ import annotations

import json

import pandas as pd
import streamlit as st

from app import api, clock


def render() -> None:
    st.subheader("Export")
    st.caption("Attendance data for your gradebook. Every export is recorded "
               "in the audit log.")

    courses = st.session_state.get("courses", [])
    if not courses:
        st.info("No courses yet.")
        return

    labels = [f"{c['code']} · {c['name']}" for c in courses]
    course = courses[labels.index(st.selectbox("Course", labels, key="ex_course"))]

    scope = st.radio("Scope", ["Whole course", "One session"],
                     horizontal=True, key="ex_scope")

    session = None
    if scope == "One session":
        listing = api.sessions(course_id=course["id"])["items"]
        if not listing:
            st.info("This course has no sessions yet.")
            return
        session_labels = [f"{s['name']} · {clock.fmt(s['scheduled_start'], '%Y-%m-%d')}" for s in listing]
        session = listing[session_labels.index(
            st.selectbox("Session", session_labels, key="ex_session"))]

    fmt = st.radio("Format", ["CSV", "JSON"], horizontal=True, key="ex_fmt")
    lower = fmt.lower()
    stamp = clock.now().strftime("%Y%m%d")

    if st.button("Prepare export", use_container_width=True, type="primary"):
        try:
            if session:
                payload = api.export_session(session["id"], lower)
                filename = f"{course['code']}_{session['name']}_{stamp}.{lower}"
            else:
                payload = api.export_course(course["id"], lower)
                filename = f"{course['code']}_attendance_{stamp}.{lower}"
            filename = filename.replace(" ", "_").replace("/", "-")
            st.session_state["export_payload"] = payload
            st.session_state["export_name"] = filename
            st.session_state["export_fmt"] = lower
        except api.ApiError as exc:
            st.error(exc.detail)
            return

    payload = st.session_state.get("export_payload")
    if not payload:
        return

    name = st.session_state["export_name"]
    st.download_button(
        f"Download {name}", data=payload, file_name=name,
        mime="text/csv" if st.session_state["export_fmt"] == "csv" else "application/json",
        use_container_width=True,
    )

    st.markdown("**Preview**")
    try:
        if st.session_state["export_fmt"] == "csv":
            import io
            # Strip the BOM for the preview only. The downloaded bytes keep
            # it, because that is what Excel needs.
            text = payload.decode("utf-8-sig")
            frame = pd.read_csv(io.StringIO(text))
            st.caption(f"{len(frame)} rows, {len(frame.columns)} columns")
            st.dataframe(frame.head(50), use_container_width=True, hide_index=True)
        else:
            data = json.loads(payload)
            records = data.get("records", [])
            st.caption(f"{len(records)} records")
            if "summary" in data:
                st.json(data["summary"])
            if records:
                st.dataframe(pd.DataFrame(records).head(50),
                             use_container_width=True, hide_index=True)
    except Exception as exc:  # noqa: BLE001 - preview is best effort
        st.caption(f"Preview unavailable ({exc}). The download is still valid.")
