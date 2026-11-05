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

        st.session_state["_switched"] = st.session_state.get("_page") not in (None, choice)
        st.session_state["_page"] = choice

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

    # The sidebar goes first: it needs only the user, and drawing it before
    # the course list loads means a page switch clears the old page at once.
    choice = sidebar(user)

    # Loaded once per rerun and shared by every view, so switching tabs does
    # not re-fetch the course list five times.
    try:
        st.session_state["courses"] = api.my_courses(user["role"])
    except api.ApiError as exc:
        if exc.status == 401:
            st.rerun()
            return
        st.error(exc.detail)
        st.session_state["courses"] = []

    from app.views import analytics, export, overview, review, sessions
    view = {
        "Overview": overview.render,
        "Sessions": sessions.render,
        "Review": review.render,
        "Analytics": analytics.render,
        "Export": export.render,
    }[choice]

    # Page switch without ghosting. Streamlit keeps the previous page on
    # screen, greyed out, until the new page has finished rendering, so for a
    # moment the new title sits on top of the old page's charts, tables and
    # expanders.
    #
    # The page renders into one of two slots. On a page change the slots
    # swap: the old page's slot becomes an empty placeholder, which removes
    # the old page from the browser straight away, and the new page draws
    # into the other slot. (Clearing and redrawing the same slot does not
    # work: Streamlit merges two updates to one position before sending, so
    # the clear never reaches the browser.) Same-page reruns keep their slot
    # and update in place as before, so nothing blinks while you work.
    slot = st.session_state.get("_slot", 0)
    if st.session_state.get("_switched"):
        slot = 1 - slot
        st.session_state["_slot"] = slot
    slots = [st.empty(), st.empty()]
    page = slots[slot].container()

    try:
        with page:
            view()
    except api.ApiError as exc:
        if exc.status == 401:
            st.warning(exc.detail)
            st.rerun()
        elif exc.status == 403:
            st.info("You do not have access to this. An instructor sees only "
                    "the courses an admin has assigned them to.")
        else:
            st.error(exc.detail)


main()
