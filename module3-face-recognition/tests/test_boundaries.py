from pathlib import Path
import sys
from types import SimpleNamespace

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from stress_boundaries import assignment, request


@pytest.mark.parametrize("clients", [1, 4, 8])
def test_mixed_workload_visits_every_case_on_both_endpoints(clients):
    cases = tuple(range(8))
    seen = {assignment(wave, index, cases) for wave in range(16) for index in range(clients)}
    assert seen == {(endpoint, case) for endpoint in ("/face/verify", "/liveness/check") for case in cases}


def test_boundary_checker_requires_strict_booleans_and_correct_blank_negative():
    class Client:
        def post(self, *_args, **_kwargs):
            return SimpleNamespace(status_code=200, json=lambda: {"match_passed": "false", "match_score": 0})

    assert request(Client(), "/face/verify", ("blank_exactly_12mp", "unused", 200), "reference")[-1] is False


def test_large_face_case_cannot_pass_merely_by_returning_no_face():
    class Client:
        def post(self, *_args, **_kwargs):
            return SimpleNamespace(status_code=200, json=lambda: {"match_passed": False, "match_score": 0,
                                                                 "face_detected": False, "current_template_hash": ""})

    assert request(Client(), "/face/verify", ("face_exactly_12mp", "unused", 200), "reference")[-1] is False
