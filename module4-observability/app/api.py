"""
Backend client.

Streamlit reruns the whole script on every interaction, so anything that
survives a rerun has to live in st.session_state. The access token does; the
requests.Session does not, because Streamlit's rerun model makes its
lifetime hard to reason about and the connection reuse is not worth the
confusion.
"""
from __future__ import annotations

import os
from typing import Any, Dict, List, Optional

import requests
import streamlit as st

BASE = os.getenv("BACKEND_URL", "http://localhost:8000").rstrip("/")
TIMEOUT = 15


class ApiError(Exception):
    def __init__(self, status: int, detail: str):
        super().__init__(detail)
        self.status = status
        self.detail = detail


def _headers() -> Dict[str, str]:
    token = st.session_state.get("access_token")
    return {"Authorization": f"Bearer {token}"} if token else {}


def _detail(payload: Any, status: int) -> str:
    detail = payload.get("detail") if isinstance(payload, dict) else None
    if isinstance(detail, str):
        return detail
    if isinstance(detail, list) and detail:
        first = detail[0]
        return str(first.get("msg", "Invalid input")) if isinstance(first, dict) else str(first)
    return f"Request failed ({status})"


def _request(method: str, path: str, *, json: Any = None,
             params: Any = None, auth: bool = True, raw: bool = False):
    try:
        response = requests.request(
            method, f"{BASE}{path}", json=json, params=params,
            headers=_headers() if auth else {}, timeout=TIMEOUT,
        )
    except requests.RequestException as exc:
        raise ApiError(0, f"Cannot reach the backend at {BASE}: {exc}")

    if response.status_code == 401 and auth:
        # Only a call that CARRIED a token can have an expired one. The login
        # call goes out with auth=False, so its 401 means the email or the
        # password is wrong, and it falls through to the normal error path
        # keeping whatever the backend actually said.
        #
        # The dashboard has no refresh flow: an instructor sitting in front
        # of it can simply sign in again, and a silent refresh would hide
        # the fact that their session expired.
        st.session_state.pop("access_token", None)
        st.session_state.pop("user", None)
        raise ApiError(401, "Session expired. Please sign in again.")

    if raw:
        if not response.ok:
            raise ApiError(response.status_code, f"Export failed ({response.status_code})")
        return response

    if response.status_code == 204:
        return None

    try:
        payload = response.json()
    except ValueError:
        payload = None

    if not response.ok:
        raise ApiError(response.status_code, _detail(payload, response.status_code))
    return payload


# --- Auth -----------------------------------------------------------------

def login(email: str, password: str) -> Dict[str, Any]:
    data = _request("POST", "/api/v1/auth/login",
                    json={"email": email, "password": password}, auth=False)
    st.session_state["access_token"] = data["access_token"]
    st.session_state["user"] = data["user"]
    return data["user"]


def logout() -> None:
    try:
        _request("POST", "/api/v1/auth/logout")
    except ApiError:
        pass
    st.session_state.pop("access_token", None)
    st.session_state.pop("user", None)


def health() -> Dict[str, Any]:
    return _request("GET", "/health", auth=False)


# --- Reads ----------------------------------------------------------------

def courses() -> List[Dict[str, Any]]:
    return _request("GET", "/api/v1/courses/", params={"limit": 100})["items"]


def sessions(**params) -> Dict[str, Any]:
    return _request("GET", "/api/v1/sessions/", params={"limit": 100, **params})


def session(session_id: str) -> Dict[str, Any]:
    return _request("GET", f"/api/v1/sessions/{session_id}")


def create_session(payload: Dict[str, Any]) -> Dict[str, Any]:
    return _request("POST", "/api/v1/sessions/", json=payload)


def set_session_status(session_id: str, status: str,
                       force: bool = False) -> Dict[str, Any]:
    """
    Move a session to a new status.

    Normal moves use PATCH /sessions/{id}, which follows the workflow
    (scheduled -> active -> closed, or cancelled) and is open to the
    course's instructor. Only `force=True` uses the admin override, for
    reopening or restoring out of order. That route requires the admin
    role, so an instructor calling it gets a 403.
    """
    if force:
        return _request("PATCH", f"/api/v1/admin/sessions/{session_id}/status",
                        json={"status": status})
    return _request("PATCH", f"/api/v1/sessions/{session_id}",
                    json={"status": status})


def patch_session(session_id: str, payload: Dict[str, Any]) -> Dict[str, Any]:
    return _request("PATCH", f"/api/v1/sessions/{session_id}", json=payload)


def stats_overview(**params) -> Dict[str, Any]:
    return _request("GET", "/api/v1/stats/overview", params=params)


def stats_session(session_id: str) -> Dict[str, Any]:
    return _request("GET", f"/api/v1/stats/sessions/{session_id}")


def stats_course(course_id: str) -> Dict[str, Any]:
    return _request("GET", f"/api/v1/stats/courses/{course_id}")


def stats_student(student_id: str) -> Dict[str, Any]:
    return _request("GET", f"/api/v1/stats/students/{student_id}")


def session_checkins(session_id: str) -> List[Dict[str, Any]]:
    return _request("GET", f"/api/v1/checkins/session/{session_id}")


def flagged(**params) -> Dict[str, Any]:
    """
    The review queue, paginated. Returns the whole page object, so the
    caller can show "showing 50 of 213" rather than guessing whether a full
    page means there is more behind it.
    """
    return _request("GET", "/api/v1/checkins/flagged", params=params)


def review(checkin_id: str, status: str, notes: str = "") -> Dict[str, Any]:
    return _request("POST", f"/api/v1/checkins/{checkin_id}/review",
                    json={"status": status, "review_notes": notes or None})


def roster(course_id: str) -> Dict[str, Any]:
    return _request("GET", f"/api/v1/enrollments/course/{course_id}")


def audit_summary(days: int = 7) -> Dict[str, Any]:
    return _request("GET", "/api/v1/audit/summary", params={"days": days})


def export_session(session_id: str, fmt: str) -> bytes:
    return _request("GET", f"/api/v1/export/session/{session_id}",
                    params={"format": fmt}, raw=True).content


def export_course(course_id: str, fmt: str) -> bytes:
    return _request("GET", f"/api/v1/export/attendance/{course_id}",
                    params={"format": fmt}, raw=True).content
