"""HTTP and SQL helpers for the isolated M2/M3 E2E suite."""
from __future__ import annotations

import psycopg2

from isolation import assert_isolated_database_name

NTU_LAT, NTU_LNG = 1.3483, 103.6831


def db_query(settings, sql: str, params: tuple = ()):
    conn = psycopg2.connect(settings.database_url)
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT current_database()")
            current = cur.fetchone()[0]
            assert_isolated_database_name(current)
            cur.execute(sql, params)
            if cur.description is None:
                return []
            cols = [col[0] for col in cur.description]
            return [dict(zip(cols, row)) for row in cur.fetchall()]
    finally:
        conn.close()


def login(m2, settings, email: str) -> str:
    response = m2.post(
        "/api/v1/auth/login",
        json={"email": email, "password": settings.password},
    )
    assert response.status_code == 200, response.text
    return response.json()["access_token"]


def auth_headers(m2, settings, email: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {login(m2, settings, email)}"}


def enroll(m2, settings, email: str, image: str):
    headers = auth_headers(m2, settings, email)
    consent = m2.put(
        "/api/v1/users/me",
        headers=headers,
        json={"camera_consent": True, "geolocation_consent": True},
    )
    assert consent.status_code == 200, consent.text
    return m2.post(
        "/api/v1/users/me/face/enroll",
        headers=headers,
        json={"image": image},
    )


def checkin(m2, settings, email: str, session_id: str, image: str | None):
    payload = {
        "session_id": session_id,
        "latitude": NTU_LAT,
        "longitude": NTU_LNG,
        "location_accuracy_meters": 8.0,
    }
    if image is not None:
        payload["liveness_challenge_response"] = image
    return m2.post(
        "/api/v1/checkins/",
        headers=auth_headers(m2, settings, email),
        json=payload,
    )


def checkins_for(settings, student_id: str) -> list[dict]:
    return db_query(
        settings,
        """
        SELECT id, session_id, student_id, status, liveness_passed, liveness_score,
               face_match_passed, face_match_score, risk_score, face_embedding_hash
        FROM checkins
        WHERE student_id = %s
        ORDER BY checked_in_at
        """,
        (student_id,),
    )


def user_row(settings, email: str) -> dict:
    rows = db_query(
        settings,
        """
        SELECT id, email, camera_consent, face_enrolled, face_embedding_hash
        FROM users
        WHERE email = %s
        """,
        (email,),
    )
    assert rows, f"missing fixture user {email}"
    return rows[0]
