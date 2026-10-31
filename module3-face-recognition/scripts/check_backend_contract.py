"""Exercise Module 2's UNMODIFIED FaceClient against a local Module 3 server.

Only the settings import is isolated (the backend's Settings needs unrelated
database/config dependencies). The source comes from a resolved local Git ref;
no checkout, backend service, database, remote write or production data is used.
This proves the client/service boundary, NOT the complete attendance workflow.
"""

import argparse
import base64
import builtins
from datetime import datetime, timezone
import hashlib
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from io import BytesIO
import math
import re
import subprocess
import sys
from threading import Thread
import time
from types import SimpleNamespace
from types import ModuleType
import json

from PIL import Image

from support import MODULE, local_service, report_target, save_report
from check_risk_contract import corpus as risk_corpus, check_cases as risk_case_checks, agrees

CLIENT_PATH = "module2-backend/app/integrations/face_client.py"


def backend_source(reference):
    def git(*arguments):
        return subprocess.run(["git", *arguments], cwd=MODULE.parent, check=True,
                              capture_output=True).stdout.decode("utf-8")

    commit = git("rev-parse", "--verify", "--end-of-options", reference + "^{commit}").strip()
    if not re.fullmatch(r"[0-9a-f]{40,64}", commit):
        raise ValueError("Backend ref must resolve to a commit")
    return commit, git("show", f"{commit}:{CLIENT_PATH}")


def client_class(source):
    """Keep every byte of the upstream client; stub only its config dependency."""
    settings = SimpleNamespace(get_settings=lambda: SimpleNamespace(FACE_SERVICE_URL="http://127.0.0.1:8001"))

    def imports(name, globals=None, locals=None, fromlist=(), level=0):
        if name == "app.core.config" and level == 0:
            return settings
        return builtins.__import__(name, globals, locals, fromlist, level)

    name = "_module3_boundary_" + hashlib.sha256(source.encode()).hexdigest()[:16]
    if name in sys.modules:
        return sys.modules[name].FaceClient
    module = ModuleType(name)
    module.__dict__["__builtins__"] = {**vars(builtins), "__import__": imports}
    # Dataclasses with postponed annotations need their real module registered.
    # Do not mutate app.core.config or any actual backend module in sys.modules.
    sys.modules[name] = module
    try:
        exec(compile(source, CLIENT_PATH, "exec"), module.__dict__)
    except BaseException:
        sys.modules.pop(name, None)
        raise
    return module.FaceClient


def require(condition):
    if not condition:
        raise AssertionError("Contract expectation failed")


def outcome(result):
    """Observe old dict and new FaceCall returns; never modify caller behavior."""
    if result is None:
        return None, {}, False, "unavailable"
    if isinstance(result, dict):
        status = int(result.get("_status") or 200)
        return status, result, status < 400, "legacy_dict"
    return result.status, result.data, result.ok, result.kind


def risk_projection_agrees(data, raw):
    """Check caller-visible fields against the complete independent wire result."""
    if not isinstance(data, dict) or not isinstance(raw, dict) or "risk_threshold" not in raw:
        return False
    # New FaceCall intentionally omits risk_threshold. If a legacy client returns
    # it, verify that value too; never overwrite a caller-supplied bad threshold.
    projected = dict(data)
    projected.setdefault("risk_threshold", raw["risk_threshold"])
    try:
        return agrees(raw, raw) and agrees(projected, raw)
    except (KeyError, TypeError, ValueError):
        return False


def failure_checks(cls):
    """Real local HTTP faults; only this tiny diagnostic server is controlled."""
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *_):
            pass

        def do_POST(self):
            fault = self.path.split("/")[1]
            # Consume the small synthetic request BEFORE replying/closing.
            # On Windows, closing with an unread POST body can reset TCP and
            # hide an otherwise valid HTTP response from the real caller.
            length = int(self.headers.get("Content-Length", "0"))
            if not 0 <= length <= 4096:
                self.send_error(413)
                return
            consumed = len(self.rfile.read(length)) == length
            if consumed:
                server.consumed.add(fault)
            if fault == "timeout":
                time.sleep(.2)
            status = {"unavailable": 503, "error": 500, "schema": 422, "upload": 408}.get(fault, 200)
            valid = {"match_passed": False, "match_score": 0., "face_detected": False, "current_template_hash": ""}
            risk = {"risk_score": .4, "risk_level": "MEDIUM", "pass_threshold": True, "risk_threshold": .5,
                    "signal_breakdown": {"liveness": .1, "face_match": .1, "device": .1, "network": .05, "geolocation": .05}}
            bodies = {"empty": {}, "boolean_score": {**valid, "match_score": True},
                      "string_boolean": {**valid, "match_passed": "false"},
                      "nan_score": {**valid, "match_score": float("nan")},
                      "bad_hash": {**valid, "current_template_hash": "invalid"}, "valid_negative": valid,
                      "risk_bad_sum": {**risk, "signal_breakdown": dict.fromkeys(risk["signal_breakdown"], 0.)},
                      "risk_bad_pass": {**risk, "pass_threshold": False},
                      "risk_bad_level": {**risk, "risk_level": "LOW"}}
            body = b"not-json" if fault == "malformed" else json.dumps(bodies.get(fault, {"detail": "diagnostic"})).encode()
            self.send_response(status)
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            try:
                self.wfile.write(body)
            except (BrokenPipeError, ConnectionResetError, ConnectionAbortedError):
                pass

    rows = []
    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    server.consumed = set()
    worker = Thread(target=server.serve_forever, daemon=True)
    worker.start()
    try:
        base = f"http://127.0.0.1:{server.server_port}"
        for fault, expected in (("unavailable", 503), ("error", 500), ("schema", 422), ("upload", 408),
                                ("timeout", None), ("malformed", 200), ("empty", 200), ("boolean_score", 200),
                                ("string_boolean", 200), ("nan_score", 200), ("bad_hash", 200), ("valid_negative", 200)):
            # Keep the caller's real five-second budget for normal responses.
            # A one-second diagnostic-only budget was too short under host load.
            timeout = .03 if fault == "timeout" else 5.
            client = cls(base_url=base + "/" + fault, timeout=timeout)
            response = client.verify("synthetic-marker", "a" * 64)
            status, data, ok, kind = outcome(response)
            valid = ok if fault == "valid_negative" else not ok
            valid = valid and (status == expected or expected in {500, 503} and response is None)
            valid = valid and fault in server.consumed
            rows.append({"check": fault, "passed": valid, "outcome_kind": kind,
                         "http_status": status, "client_timeout_seconds": timeout,
                         "request_body_consumed": fault in server.consumed})
            if fault == "malformed":
                observation = {"non_json_200_status_only": response == {"_status": 200},
                               "non_json_200_is_success": client.is_success(response)}
        if callable(getattr(cls, "assess_risk", None)):
            observed = []
            for fault in ("unavailable", "malformed", "empty", "risk_bad_sum", "risk_bad_pass", "risk_bad_level"):
                response = cls(base_url=base + "/" + fault, timeout=5.).assess_risk({})
                status, body, ok, kind = outcome(response)
                observed.append({"probe": fault, "outcome_kind": kind, "http_status": status,
                                 "transport_success": ok,
                                 "required_score_present": "risk_score" in body})
            observation["risk_method_outcomes"] = observed
            observation["risk_outage_distinguished_from_non_json"] = (
                (observed[0]["outcome_kind"], observed[0]["http_status"])
                != (observed[1]["outcome_kind"], observed[1]["http_status"]))
            observation["risk_empty_object_rejected"] = not observed[2]["transport_success"]
            observation["risk_inconsistent_response_accepted"] = any(item["transport_success"] for item in observed[3:])
    finally:
        server.shutdown()
        server.server_close()
        worker.join(timeout=2)
    # An HTTP status alone is not valid biometric evidence. Expose this caller
    # behavior explicitly; never count it as safe attendance authorization.
    return rows, observation


def run_checks(face, profile, record, wire=None):
    """No image, user ID, reference, individual score or HTTP body is reported."""
    def check(name, operation):
        try:
            operation()
            record.append({"check": name, "passed": True})
        except Exception as exc:
            record.append({"check": name, "passed": False, "failure_type": type(exc).__name__})

    photo = base64.b64encode((MODULE.parent / "sample_images" / "obama.jpg").read_bytes()).decode("ascii")
    buffer = BytesIO()
    Image.new("RGB", (256, 256), "gray").save(buffer, format="PNG")
    blank = base64.b64encode(buffer.getvalue()).decode("ascii")
    reference = None

    def enrollment():
        nonlocal reference
        status, data, ok, _ = outcome(face.enroll("module3-contract-probe", "data:image/jpeg;base64," + photo, True))
        require(ok and status == 201 and data["enrollment_successful"] is True)
        reference = data["face_template_hash"]
        require(bool(re.fullmatch(r"[0-9a-f]{64}", reference)))
        require(0 <= data["quality_score"] <= 1)
        if wire is not None:
            info = wire.get("/").json()
            require(info["template_mode"] == ("simhash" if profile == "enhanced" else "sha256"))
            require(info["match_score_policy"] == ("gaussian_query_margin_agreement_v3" if profile == "enhanced"
                                                   else "exact_sha256_v1"))
            require(info["template_format"] == ("sface_simhash64_signed_v1" if profile == "enhanced"
                                                 else "sha256_normalized_face_pixels_v1"))

    check("enroll_data_url_and_64_hex_template", enrollment)

    def score_result(result, prefix, threshold):
        status, data, ok, _ = outcome(result)
        require(ok and status == 200)
        score = data[prefix + "_score"]
        require(type(data[prefix + "_passed"]) is bool and math.isfinite(score) and 0 <= score <= 1)
        require(data[prefix + "_passed"] == (score >= threshold))
        return data

    def verification():
        require(reference is not None)
        data = score_result(face.verify("data:image/jpeg;base64," + photo, reference), "match", .7)
        require(data["match_passed"] is True and data["current_template_hash"] == reference)
        require(data["face_detected"] is True)
        if wire is not None:
            require(wire.post("/face/verify", json={"image": photo, "reference_template_hash": reference}).json()["match_threshold"] == .7)

    check("verify_stored_template_round_trip", verification)

    def liveness():
        data = score_result(face.liveness("data:image/jpeg;base64," + photo), "liveness", .6)
        require(data["face_embedding_hash"] == reference)
        if wire is not None:
            raw = wire.post("/liveness/check", json={"challenge_response": photo}).json()
            require(raw["challenge_type"] == "passive" and raw["liveness_threshold"] == .6 and raw["details"]["motion_verified"] is False)

    check("passive_liveness_fields_and_same_template", liveness)

    def risk():
        payload = {"face_match_score": .85, "liveness_score": .92}
        status, data, ok, _ = outcome(face.assess_risk(payload))
        require(ok and status == 200 and math.isfinite(data["risk_score"]))
        if wire is not None:
            response = wire.post("/risk/assess", json=payload)
            require(response.status_code == 200)
            raw = response.json()
            require(raw["risk_threshold"] == .5 and risk_projection_agrees(data, raw))
        else:
            require(data.get("risk_threshold") == .5)
        require(0 <= data["risk_score"] <= 1)
        require(data["pass_threshold"] == (data["risk_score"] < .5))
        require(abs(sum(data["signal_breakdown"].values()) - data["risk_score"]) < 1e-9)

    check("risk_weighted_contributions", risk)

    for name, call, status in (
        ("consent_false", lambda: face.enroll("contract-probe", photo, False), 400),
        ("consent_string_not_boolean", lambda: face.enroll("contract-probe", photo, "true"), 422),
        ("invalid_image", lambda: face.enroll("contract-probe", "not-an-image", True), 400),
        ("blank_enrollment", lambda: face.enroll("contract-probe", blank, True), 400),
        ("invalid_reference", lambda: face.verify(photo, "invalid"), 422),
        ("unsupported_blink", lambda: face.liveness(photo, "blink"), 400),
        ("unsupported_head_turn", lambda: face.liveness(photo, "head_turn"), 400),
        ("invalid_risk_score", lambda: face.assess_risk({"face_match_score": 1.1}), 422),
    ):
        def error(operation=call, expected=status):
            status, _, ok, _ = outcome(operation())
            require(status == expected and not ok)
        check(name, error)

    def blank_verify():
        require(reference is not None)
        data = score_result(face.verify(blank, reference), "match", .7)
        require(data["match_passed"] is False and data["face_detected"] is False and data["current_template_hash"] == "")

    def blank_live():
        data = score_result(face.liveness(blank), "liveness", .6)
        require(data["liveness_passed"] is False and data["face_embedding_hash"] == "")

    check("no_face_verify_negative_not_transport_failure", blank_verify)
    check("no_face_liveness_negative_not_transport_failure", blank_live)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--backend-ref", default="origin/module2-backend")
    parser.add_argument("--profile", choices=("sha256", "enhanced", "both"), default="both")
    parser.add_argument("--report", default="evaluation/backend-contract.json")
    args = parser.parse_args(argv)
    target = report_target(args.report)
    report = {"timestamp_utc": datetime.now(timezone.utc).isoformat(), "completed": False, "passed": False,
              "profiles": {}, "risk_corpus": {}, "backend_modified": False,
              "limitations": ["Only the actual FaceClient/Module 3 HTTP boundary; not backend auth, DB or attendance decisions.",
                              "Only the backend settings import is stubbed, not client methods or HTTP responses.",
                              "The M2 local risk calculator, fallback and final attendance policy are not validated.",
                              "M3 raw threshold is verified over HTTP; newer FaceCall strips this field.",
                              "Classification correctness and deployment capacity are separate release gates."]}
    try:
        commit, source = backend_source(args.backend_ref)
        report.update(backend_commit=commit, backend_client_sha256=hashlib.sha256(source.encode()).hexdigest())
        cls = client_class(source)
        faults, observation = failure_checks(cls)
        report.update(fault_checks=faults, caller_observations=observation)
        if observation.get("risk_outage_distinguished_from_non_json") is False or observation.get("risk_empty_object_rejected") is False:
            report.setdefault("integration_pending", []).extend([
                "M2 assess_risk still conflates unavailable/non-JSON results or accepts missing score fields.",
                "Classify and validate risk outcomes before enabling fallback; this report does not enable or verify M2 fallback."])
        if observation.get("risk_inconsistent_response_accepted") is True:
            report.setdefault("integration_pending", []).append(
                "M2 risk parser accepts at least one inconsistent synthetic response; verify score, decision and breakdown consistency before using it for attendance.")
        if observation["non_json_200_is_success"]:
            report["caller_warnings"] = ["FaceClient.is_success accepts a non-JSON 200 based on status alone; validate required typed fields before using biometric evidence."]
        for profile in (("sha256", "enhanced") if args.profile == "both" else (args.profile,)):
            checks = report["profiles"][profile] = []
            with local_service(profile, {"FACE_MODEL_WORKERS": "4", "FACE_NATIVE_THREADS": "1",
                                        "INFERENCE_CONCURRENCY": "8", "INFERENCE_PENDING": "32",
                                        "INFERENCE_QUEUE_SECONDS": "2"}) as service:
                run_checks(cls(base_url=str(service.base_url), timeout=5.), profile, checks, wire=service)
                caller = cls(base_url=str(service.base_url), timeout=5.)

                def risk_call(payload):
                    status, body, ok, _ = outcome(caller.assess_risk(payload))
                    if ok != (status == 200):
                        raise ValueError("Unexpected risk outcome classification")
                    wire_response = service.post("/risk/assess", json=payload)
                    require(wire_response.status_code == status)
                    raw = wire_response.json()
                    if status == 200:
                        require(risk_projection_agrees(body, raw))
                    return status, raw

                manifest, digest, vectors = risk_corpus()
                report["risk_policy_id"], report["risk_policy_sha256"] = manifest["policy_id"], digest
                report["risk_corpus"][profile] = risk_case_checks(vectors, risk_call)
            print(f"{profile}: {sum(row['passed'] for row in checks)}/{len(checks)} client boundary checks passed", flush=True)
            save_report(target, report)
        report["completed"] = True
        report["passed"] = all(row["passed"] for row in faults) and all(
            rows and all(row["passed"] for row in rows)
            for group in ("profiles", "risk_corpus") for rows in report[group].values())
    except Exception as exc:
        report["failure_type"] = type(exc).__name__
    finally:
        save_report(target, report)
    print(f"Backend contract passed={report['passed']}; report={target}", flush=True)
    return 0 if report["passed"] else 1


if __name__ == "__main__":
    sys.exit(main())
