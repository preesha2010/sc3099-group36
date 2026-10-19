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

from PIL import Image

from support import MODULE, local_service, report_target, save_report

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

    namespace = {"__name__": "module2_client_contract", "__builtins__": {**vars(builtins), "__import__": imports}}
    exec(compile(source, CLIENT_PATH, "exec"), namespace)
    return namespace["FaceClient"]


def require(condition):
    if not condition:
        raise AssertionError("Contract expectation failed")


def failure_checks(cls):
    """Real local HTTP faults; only this tiny diagnostic server is controlled."""
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *_):
            pass

        def do_POST(self):
            if self.path == "/timeout":
                time.sleep(.2)
            status = {"/unavailable": 503, "/error": 500, "/schema": 422}.get(self.path, 200)
            body = b"not-json" if self.path == "/malformed" else b'{"detail":"diagnostic"}'
            self.send_response(status)
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            try:
                self.wfile.write(body)
            except (BrokenPipeError, ConnectionResetError, ConnectionAbortedError):
                pass

    rows = []
    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    worker = Thread(target=server.serve_forever, daemon=True)
    worker.start()
    try:
        client = cls(base_url=f"http://127.0.0.1:{server.server_port}", timeout=1.)
        for path, expected in (("/unavailable", None), ("/error", None), ("/schema", 422)):
            response = client._post(path, {})
            rows.append({"check": path[1:], "passed": not client.is_success(response) and
                         (response is None if expected is None else response["_status"] == expected)})
        timed = cls(base_url=client.base_url, timeout=.03)
        response = timed._post("/timeout", {})
        rows.append({"check": "timeout", "passed": response is None and not timed.is_success(response)})
        response = client._post("/malformed", {})
        observation = {"non_json_200_status_only": response == {"_status": 200},
                       "non_json_200_is_success": client.is_success(response)}
    finally:
        server.shutdown()
        server.server_close()
        worker.join(timeout=2)
    # An HTTP status alone is not valid biometric evidence. Expose this caller
    # behavior explicitly; never count it as safe attendance authorization.
    return rows, observation


def run_checks(face, profile, record):
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
        data = face.enroll("module3-contract-probe", "data:image/jpeg;base64," + photo, True)
        require(face.is_success(data) and data["_status"] == 201 and data["enrollment_successful"] is True)
        reference = data["face_template_hash"]
        require(bool(re.fullmatch(r"[0-9a-f]{64}", reference)))
        require(0 <= data["quality_score"] <= 1 and data["details"]["template_mode"] ==
                ("simhash" if profile == "enhanced" else "sha256"))

    check("enroll_data_url_and_64_hex_template", enrollment)

    def score_result(data, prefix, threshold):
        require(face.is_success(data) and data["_status"] == 200)
        score = data[prefix + "_score"]
        require(type(data[prefix + "_passed"]) is bool and math.isfinite(score) and 0 <= score <= 1)
        require(data[prefix + "_passed"] == (score >= threshold))

    def verification():
        require(reference is not None)
        data = face.verify("data:image/jpeg;base64," + photo, reference)
        score_result(data, "match", .7)
        require(data["match_passed"] is True and data["current_template_hash"] == reference)
        require(data["match_threshold"] == .7 and data["face_detected"] is True)

    check("verify_stored_template_round_trip", verification)

    def liveness():
        data = face.liveness("data:image/jpeg;base64," + photo)
        score_result(data, "liveness", .6)
        require(data["challenge_type"] == "passive" and data["liveness_threshold"] == .6)
        require(data["details"]["motion_verified"] is False and data["face_embedding_hash"] == reference)

    check("passive_liveness_fields_and_same_template", liveness)

    def risk():
        data = face.assess_risk({"face_match_score": .85, "liveness_score": .92})
        require(face.is_success(data) and math.isfinite(data["risk_score"]))
        require(0 <= data["risk_score"] <= 1 and data["risk_threshold"] == .5)
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
            result = operation()
            require(result is not None and result["_status"] == expected and not face.is_success(result))
        check(name, error)

    def blank_verify():
        require(reference is not None)
        data = face.verify(blank, reference)
        score_result(data, "match", .7)
        require(data["match_passed"] is False and data["face_detected"] is False and data["current_template_hash"] == "")

    def blank_live():
        data = face.liveness(blank)
        score_result(data, "liveness", .6)
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
              "profiles": {}, "backend_modified": False,
              "limitations": ["Only the actual FaceClient/Module 3 HTTP boundary; not backend auth, DB or attendance decisions.",
                              "Only the backend settings import is stubbed, not client methods or HTTP responses.",
                              "Classification correctness and deployment capacity are separate release gates."]}
    try:
        commit, source = backend_source(args.backend_ref)
        report.update(backend_commit=commit, backend_client_sha256=hashlib.sha256(source.encode()).hexdigest())
        cls = client_class(source)
        faults, observation = failure_checks(cls)
        report.update(fault_checks=faults, caller_observations=observation)
        if observation["non_json_200_is_success"]:
            report["caller_warnings"] = ["FaceClient.is_success accepts a non-JSON 200 based on status alone; validate required typed fields before using biometric evidence."]
        for profile in (("sha256", "enhanced") if args.profile == "both" else (args.profile,)):
            checks = report["profiles"][profile] = []
            with local_service(profile, {"FACE_MODEL_WORKERS": "4", "FACE_NATIVE_THREADS": "1",
                                        "INFERENCE_CONCURRENCY": "8", "INFERENCE_PENDING": "32",
                                        "INFERENCE_QUEUE_SECONDS": "2"}) as service:
                run_checks(cls(base_url=str(service.base_url), timeout=5.), profile, checks)
            print(f"{profile}: {sum(row['passed'] for row in checks)}/{len(checks)} client boundary checks passed", flush=True)
            save_report(target, report)
        report["completed"] = True
        report["passed"] = all(row["passed"] for row in faults) and all(
            rows and all(row["passed"] for row in rows) for rows in report["profiles"].values())
    except Exception as exc:
        report["failure_type"] = type(exc).__name__
    finally:
        save_report(target, report)
    print(f"Backend contract passed={report['passed']}; report={target}", flush=True)
    return 0 if report["passed"] else 1


if __name__ == "__main__":
    sys.exit(main())
