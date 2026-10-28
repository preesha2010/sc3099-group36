"""Harness tests do not require a backend checkout or a fetched branch."""

from pathlib import Path
import sys
from types import SimpleNamespace

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import check_backend_contract as contract
import release_check


def test_source_loader_only_stubs_backend_settings():
    source = '''
import httpx
from app.core.config import get_settings
class FaceClient:
    def __init__(self):
        self.base_url = get_settings().FACE_SERVICE_URL
        self.httpx_version = httpx.__version__
'''
    instance = contract.client_class(source)()
    assert instance.base_url == "http://127.0.0.1:8001"
    import httpx
    assert instance.httpx_version == httpx.__version__


def test_http_fault_harness_observes_actual_network_responses():
    # Minimal diagnostic client, not a copy of Module 2 implementation. The
    # end-to-end command separately loads and checks the real Git source.
    import httpx

    class Probe:
        def __init__(self, base_url, timeout):
            self.base_url, self.timeout = base_url, timeout

        def verify(self, image, reference):
            try:
                response = httpx.post(self.base_url + "/face/verify", json={}, timeout=self.timeout)
                status = response.status_code
                kind = ("unavailable" if status >= 500 else "client_error" if status >= 400 else
                        "ok" if self.base_url.endswith("/valid_negative") else "malformed")
            except httpx.HTTPError:
                status, kind = None, "unavailable"
            return SimpleNamespace(status=status, kind=kind, ok=kind == "ok", data={})

        @staticmethod
        def is_success(data):
            return data.ok

    rows, observation = contract.failure_checks(Probe)
    assert len(rows) == 12 and all(row["passed"] for row in rows)
    assert all(row["client_timeout_seconds"] == (.03 if row["check"] == "timeout" else 5.) for row in rows)
    assert all(row["request_body_consumed"] for row in rows)
    assert observation == {"non_json_200_status_only": False, "non_json_200_is_success": False}


def test_postponed_dataclass_annotations_work_without_mutating_backend_modules():
    source = '''
from __future__ import annotations
from dataclasses import dataclass
@dataclass
class Result:
    ok: bool = True
class FaceClient:
    def response(self):
        return Result()
'''
    cls = contract.client_class(source)
    assert cls().response().ok is True
    assert contract.client_class(source) is cls


def test_ref_is_resolved_to_immutable_commit_before_reading_source(monkeypatch):
    calls = []

    def run(command, **_):
        calls.append(command)
        return SimpleNamespace(stdout=(b"a" * 40 + b"\n") if len(calls) == 1 else b"source")

    monkeypatch.setattr(contract.subprocess, "run", run)
    assert contract.backend_source("origin/module2-backend") == ("a" * 40, "source")
    assert calls[0][1:4] == ["rev-parse", "--verify", "--end-of-options"]
    assert calls[1] == ["git", "show", "a" * 40 + ":" + contract.CLIENT_PATH]


def test_bad_resolved_revision_is_not_executed(monkeypatch):
    monkeypatch.setattr(contract.subprocess, "run", lambda *_, **__: SimpleNamespace(stdout=b"not-a-commit"))
    with pytest.raises(ValueError):
        contract.backend_source("ref")


def test_contract_failure_report_never_echoes_payload_or_exception(monkeypatch):
    class BrokenClient:
        def __getattr__(self, _):
            raise RuntimeError("private image / template / key must never be reported")

    rows = []
    contract.run_checks(BrokenClient(), "sha256", rows)
    assert len(rows) == 14 and all(not row["passed"] for row in rows)
    assert "private image" not in str(rows)
    assert all(set(row) == {"check", "passed", "failure_type"} for row in rows)


def test_release_checks_backend_boundary_before_accuracy_gate(monkeypatch):
    commands = []
    results = iter([0, 0, 1])

    def run(command, **_):
        commands.append(command)
        return SimpleNamespace(returncode=next(results))

    monkeypatch.setattr(release_check.subprocess, "run", run)
    assert release_check.main(["--backend-ref", "origin/module2-backend"]) == 1
    assert len(commands) == 3
    assert commands[-1][-2:] == ["--backend-ref", "origin/module2-backend"]
    assert commands[-1][1].endswith("check_backend_contract.py")


def test_full_local_release_pipeline_still_propagates_classification_block(monkeypatch):
    commands, results = [], iter([0, 0, 0, 0, 2])

    def run(command, **_):
        commands.append(command)
        return SimpleNamespace(returncode=next(results))

    monkeypatch.setattr(release_check.subprocess, "run", run)
    assert release_check.main(["--transport", "--backend-ref", "origin/module2-backend"]) == 2
    assert [Path(command[1]).name for command in commands] == [
        "verify.py", "check_risk_contract.py", "check_transport.py", "check_backend_contract.py", "evaluate_robustness.py"]
