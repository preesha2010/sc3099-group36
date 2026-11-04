"""Shared synthetic golden vectors; never derive expected values from the engine."""

from copy import deepcopy
import hashlib
import json
from pathlib import Path
import sys
from types import SimpleNamespace

import pytest
from pydantic import ValidationError

from app.risk_policy import RISK_POLICY_ID, RISK_POLICY_SHA256, assess_payload, policy_document

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import check_risk_contract as contract

MANIFEST, DIGEST, CASES = contract.corpus()


@pytest.mark.parametrize("case", CASES, ids=lambda case: case["id"])
def test_http_matches_independently_specified_corpus(client, case):
    response = client.post("/risk/assess", json=case["input"])
    assert response.status_code == case["status"]
    if case["status"] == 200:
        assert contract.agrees(response.json(), case["expected"])
        assert response.headers["X-Risk-Policy-ID"] == RISK_POLICY_ID
        assert response.headers["X-Risk-Policy-SHA256"] == DIGEST


@pytest.mark.parametrize("case", CASES, ids=lambda case: case["id"])
def test_pure_reference_matches_same_corpus(case):
    original = deepcopy(case["input"])
    if case["status"] == 422:
        with pytest.raises(ValidationError):
            assess_payload(case["input"])
    else:
        assert contract.agrees(assess_payload(case["input"]), case["expected"])
    assert case["input"] == original


def test_manifest_is_discoverable_and_fingerprint_covers_canonical_document(client):
    response = client.get("/risk/policy")
    assert response.status_code == 200
    assert response.json() == policy_document()
    assert DIGEST == RISK_POLICY_SHA256 == hashlib.sha256(json.dumps(
        MANIFEST, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()).hexdigest()
    root = client.get("/").json()
    assert "/risk/policy" in root["endpoints"]
    assert root["risk_policy_id"] == RISK_POLICY_ID and root["risk_policy_sha256"] == DIGEST
    mutated = policy_document()
    mutated["manifest"]["weights"]["face_match"] = 100
    assert policy_document()["manifest"]["weights"]["face_match"] == .25
    assert "route=\"/risk/policy\"" in client.get("/metrics").text


@pytest.mark.parametrize("mutation", [
    {"risk_score": True}, {"risk_score": float("nan")}, {"risk_score": float("inf")},
    {"risk_score": 1.1}, {"risk_score": "0.5"}, {"risk_level": "LOW"},
    {"pass_threshold": 0}, {"pass_threshold": True}, {"risk_threshold": .6},
    {"signal_breakdown": {}}, {"signal_breakdown": {"extra": .5}},
])
def test_comparator_rejects_unsafe_or_semantically_different_outputs(mutation):
    assert not contract.agrees({**CASES[0]["expected"], **mutation}, CASES[0]["expected"])


def test_comparator_rejects_bool_even_when_numeric_value_would_equal_expected():
    expected = next(case["expected"] for case in CASES if case["id"] == "normal")
    changed = deepcopy(expected)
    changed["signal_breakdown"]["network"] = False
    assert not contract.agrees(changed, expected)


def test_bad_candidate_does_not_modify_corpus_and_report_never_echoes_errors():
    cases = deepcopy(CASES)

    def broken(payload):
        payload["private-marker"] = "private-marker"
        raise RuntimeError("private-marker")

    rows = contract.check_cases(cases, contract.candidate_operation(broken))
    assert all(not row["passed"] for row in rows) and cases == CASES
    assert "private-marker" not in json.dumps(rows)
    assert all(row["failure_type"] == "RuntimeError" for row in rows)


def test_candidate_validation_error_is_rejection_not_zero_risk():
    rows = contract.check_cases(
        [{"id": "invalid", "input": {}, "status": 422}],
        contract.candidate_operation(lambda _: (_ for _ in ()).throw(ValueError("private-marker"))))
    assert rows == [{"case": "invalid", "passed": True}]


def test_full_http_harness_can_check_actual_app(client):
    rows = contract.http_checks(client, MANIFEST, DIGEST, CASES)
    assert len(rows) == len(CASES) + 1 and all(row["passed"] for row in rows)


def test_policy_header_mismatch_cannot_pass_even_if_score_matches(client, monkeypatch):
    original = client.post

    def wrong(*args, **kwargs):
        response = original(*args, **kwargs)
        response.headers["X-Risk-Policy-SHA256"] = "wrong"
        return response

    monkeypatch.setattr(client, "post", wrong)
    rows = contract.http_checks(client, MANIFEST, DIGEST, [CASES[0]])
    assert rows[0]["passed"] and not rows[1]["passed"]


def test_wrong_candidate_policy_identity_fails_and_cli_returns_nonzero(monkeypatch):
    records = []
    monkeypatch.setattr(contract.importlib, "import_module", lambda _: SimpleNamespace(
        RISK_POLICY_ID="wrong", RISK_POLICY_SHA256=DIGEST, calculate=assess_payload))
    monkeypatch.setattr(contract, "save_report", lambda _, value: records.append(value))
    assert contract.main(["--candidate", "fixture_module:calculate"]) == 1
    assert not records[0]["passed"] and not records[0]["checks"][0]["passed"]


def test_risk_gate_failure_stops_release_before_any_other_integration(monkeypatch):
    import release_check
    commands = []
    statuses = iter([0, 1])

    def run(command, **_):
        commands.append(command)
        return SimpleNamespace(returncode=next(statuses))

    monkeypatch.setattr(release_check.subprocess, "run", run)
    assert release_check.main(["--transport", "--backend-ref", "origin/module2-backend"]) == 1
    assert [Path(command[1]).name for command in commands] == ["verify.py", "check_risk_contract.py"]
