import base64

import pytest
from cryptography.hazmat.primitives.asymmetric import ed25519
from cryptography.hazmat.primitives.serialization import Encoding, PublicFormat


def test_arbitrary_device_fields_cannot_create_trust(client):
    result = client.post("/risk/assess", json={"device_signature": "not-a-signature", "device_public_key": "not-a-key"})
    assert result.status_code == 200
    assert result.json()["signal_breakdown"]["device"] == pytest.approx(0.2)


def test_well_formed_but_unverified_device_stays_uncertain(client):
    key = ed25519.Ed25519PrivateKey.generate()
    signature = base64.b64encode(key.sign(b"arbitrary message")).decode()
    pem = key.public_key().public_bytes(Encoding.PEM, PublicFormat.SubjectPublicKeyInfo).decode()
    result = client.post("/risk/assess", json={"device_signature": signature, "device_public_key": pem}).json()
    assert result["signal_breakdown"]["device"] == pytest.approx(0.1)


@pytest.mark.parametrize("signals,expected", [
    ({}, 0.075),
    ({"ip_address": "10.0.0.1"}, 0.105),
    ({"ip_address": "8.8.8.8", "user_agent": "NordVPN"}, 0.12),
    ({"user_agent": "secure-Tunnel"}, 0.12),
    ({"user_agent": "Motorola browser"}, 0.12),
    ({"ip_address": "10.0.0.1", "user_agent": "proxy"}, 0.12),
])
def test_network_matches_course_reference(client, signals, expected):
    response = client.post("/risk/assess", json=signals).json()
    assert response["signal_breakdown"]["network"] == pytest.approx(expected)
    if expected > 0.075:
        assert "Disable VPN for check-in" in response["recommendations"]


@pytest.mark.parametrize("signals", [{}, {"liveness_score": .95, "face_match_score": .95}, {"liveness_score": .1, "face_match_score": .2, "device_signature": "bad"}])
def test_breakdown_adds_up_and_threshold_is_consistent(client, signals):
    response = client.post("/risk/assess", json=signals).json()
    assert sum(response["signal_breakdown"].values()) == pytest.approx(response["risk_score"])
    assert response["pass_threshold"] == (response["risk_score"] < .5)
    assert 0 <= response["risk_score"] <= 1


@pytest.mark.parametrize("signals,expected_score,level,passed", [
    ({"liveness_score": 1, "face_match_score": .8}, .3, "MEDIUM", True),
    ({"liveness_score": 0, "face_match_score": 1}, .5, "HIGH", False),
    ({"liveness_score": 0, "face_match_score": .2}, .7, "CRITICAL", False),
])
def test_exact_risk_boundaries(client, signals, expected_score, level, passed):
    result = client.post("/risk/assess", json=signals).json()
    assert result["risk_score"] == expected_score
    assert result["risk_level"] == level
    assert result["pass_threshold"] is passed
