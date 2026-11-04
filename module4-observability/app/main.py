"""
SAIV Instructor Dashboard, module 4.

Streamlit reruns this whole file on every interaction, so the structure is
deliberately flat: authenticate, load what the sidebar needs, dispatch to
one view. State that has to survive a rerun lives in st.session_state.
"""
from __future__ import annotations

import streamlit as st

from app import api, theme

st.set_page_config(
    page_title="SAIV Dashboard",
    page_icon="📋",
    layout="wide",
    initial_sidebar_state="expanded",
)
st.markdown(theme.CSS, unsafe_allow_html=True)

# Roles that have any business here. A student hitting this URL is not an
# attacker, they are lost, so say where to go rather than just refusing.
STAFF_ROLES = {"ta", "instructor", "admin"}


def login_screen() -> None:
    left, middle, right = st.columns([1, 1.2, 1])
    with middle:
        st.markdown("## SAIV")
        st.caption("Instructor dashboard")

        with st.form("login"):
            email = st.text_input("Email", placeholder="you@ntu.edu.sg")
            password = st.text_input("Password", type="password")
            submitted = st.form_submit_button("Sign in", use_container_width=True,
                                              type="primary")
        if not submitted:
            return

        try:
            user = api.login(email.strip(), password)
        except api.ApiError as exc:
            st.error(exc.detail)
            return

        if user["role"] not in STAFF_ROLES:
            api.logout()
            st.error("This dashboard is for teaching staff. Students check in "
                     "through the student app.")
            return
        st.rerun()


def sidebar(user: dict) -> str:
    with st.sidebar:
        st.markdown("### SAIV")
        st.caption("Instructor dashboard")
        st.markdown(f"**{user['full_name']}**  \n"
                    f"<span style='color:{theme.INK_MUTED};font-size:0.8rem'>"
                    f"{user['role']}</span>", unsafe_allow_html=True)
        st.divider()

        choice = st.radio(
            "Go to",
            ["Overview", "Sessions", "Review", "Analytics", "Export"],
            label_visibility="collapsed", key="nav",
        )

        st.divider()
        if st.button("Refresh data", use_container_width=True):
            st.cache_data.clear()
            st.rerun()
        if st.button("Sign out", use_container_width=True):
            api.logout()
            st.rerun()
        return choice


def main() -> None:
    if not st.session_state.get("access_token"):
        login_screen()
        return

    user = st.session_state.get("user")
    if not user or user["role"] not in STAFF_ROLES:
        api.logout()
        st.rerun()
        return

    # Loaded once per rerun and shared by every view, so switching tabs does
    # not re-fetch the course list five times.
    try:
        st.session_state["courses"] = api.courses()
    except api.ApiError as exc:
        if exc.status == 401:
            st.rerun()
            return
        st.error(exc.detail)
        st.session_state["courses"] = []

    choice = sidebar(user)

    from app.views import analytics, export, overview, review, sessions
    view = {
        "Overview": overview.render,
        "Sessions": sessions.render,
        "Review": review.render,
        "Analytics": analytics.render,
        "Export": export.render,
    }[choice]

    try:
        view()
    except api.ApiError as exc:
        if exc.status == 401:
            st.warning(exc.detail)
            st.rerun()
        else:
            st.error(exc.detail)


main()
