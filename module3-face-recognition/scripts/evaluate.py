"""Real HTTP identity/PAD evaluation and 10/50/100-client load measurements.

Run after bootstrap_models.py --pad. Report contains only labels, scores and
timings. Publisher demonstration images are fetched into memory, never saved.
"""

import argparse
import base64
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
import hashlib
import json
import math
import os
from pathlib import Path
import platform
import socket
import subprocess
import sys
import time

import cv2
import httpx

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app.model_assets import FAS
from app.evaluation import summarize
from support import report_target

MODULE = Path(__file__).resolve().parents[1]
REPO = MODULE.parent
PAD_SAMPLES = {
    "image_F1.jpg": (False, "4b11b5d7a8a8e4a88f5f16a5426a0a7692e39e5bb45bb03b4ebe5e1606336860"),
    "image_F2.jpg": (False, "fbbea73450ae9d9bb555c8ccac77bf39d234261fe3be4190e3ed2999690c485f"),
    "image_T1.jpg": (True, "f4455149f488f76205fdee5499ec5261d08ef6279a1cff7b778ea85405331e94"),
}


def percentile(values, quantile):
    return sorted(values)[max(0, math.ceil(len(values) * quantile) - 1)]


def load_measurement(client, path, payload, count, expected_field):
    def request(_):
        start = time.monotonic()
        try:
            result = client.post(path, json=payload)
            valid = result.status_code == 200 and result.json().get(expected_field) is True
            return time.monotonic() - start, valid, str(result.status_code)
        except httpx.HTTPError as exc:
            return time.monotonic() - start, False, type(exc).__name__

    started = time.monotonic()
    with ThreadPoolExecutor(max_workers=count) as pool:
        tasks = [pool.submit(request, i) for i in range(count)]
        health_times = []
        health_failed = 0
        # Observe health repeatedly while the inference requests are outstanding.
        while not all(task.done() for task in tasks):
            begin = time.monotonic()
            try:
                client.get("/health").raise_for_status()
            except httpx.HTTPError:
                health_failed += 1
            health_times.append(time.monotonic() - begin)
            time.sleep(.05)
        results = [task.result() for task in tasks]
    latencies = [item[0] for item in results]
    measured = {
        "clients": count, "successful": sum(item[1] for item in results),
        "http_status_counts": {status: sum(item[2] == status for item in results) for status in sorted(set(item[2] for item in results))},
        "elapsed_seconds": round(time.monotonic() - started, 4),
        "p50_seconds": round(percentile(latencies, .50), 4),
        "p95_seconds": round(percentile(latencies, .95), 4),
        "maximum_seconds": round(max(latencies), 4),
        "health_maximum_seconds": round(max(health_times, default=0), 4),
        "health_failures": health_failed,
    }
    print(f"{path} {count} clients: {measured}", flush=True)
    return measured


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--report", default="evaluation/latest.json")
    parser.add_argument("--workers", type=int, default=4, choices=range(1, 9))
    parser.add_argument("--clients", type=int, nargs="+", default=[10, 50, 100])
    parser.add_argument("--pending", type=int, default=128, choices=range(129), help="Queue capacity for the all-success throughput experiment; production default is 32")
    parser.add_argument("--queue-seconds", type=float, default=30, help="Queue deadline for throughput comparison; production default is 2 seconds")
    args = parser.parse_args()
    if not all(1 <= count <= 100 for count in args.clients):
        parser.error("Client counts must be between 1 and 100")
    if not .01 <= args.queue_seconds <= 30:
        parser.error("Queue deadline must be between 0.01 and 30")
    try:
        report_path = report_target(args.report)
    except ValueError as exc:
        parser.error(str(exc))
    with httpx.Client(timeout=60, follow_redirects=True) as fetch:
        pad_images = {}
        for name, (_, expected) in PAD_SAMPLES.items():
            data = fetch.get(f"{FAS}/images/sample/{name}")
            data.raise_for_status()
            if hashlib.sha256(data.content).hexdigest() != expected:
                raise RuntimeError("Publisher sample checksum mismatch")
            pad_images[name] = base64.b64encode(data.content).decode("ascii")
    environment = os.environ.copy()
    environment.update(FACE_TEMPLATE_MODE="simhash", LIVENESS_BACKEND="minifasnet", FACE_MODEL_WORKERS=str(args.workers),
                       INFERENCE_PENDING=str(args.pending), INFERENCE_QUEUE_SECONDS=str(args.queue_seconds),
                       OPENBLAS_NUM_THREADS="1", OMP_NUM_THREADS="1", GLOG_minloglevel="2", TF_CPP_MIN_LOG_LEVEL="2")
    with socket.socket() as listener:
        listener.bind(("127.0.0.1", 0))
        port = listener.getsockname()[1]
    url = f"http://127.0.0.1:{port}"
    report_path.parent.mkdir(parents=True, exist_ok=True)
    log_path = report_path.parent / "server.log"
    log = log_path.open("w", encoding="utf-8")
    server = subprocess.Popen(
        [sys.executable, "-m", "uvicorn", "app.main:app", "--host", "127.0.0.1", "--port", str(port), "--timeout-keep-alive", "60", "--no-access-log"],
        cwd=MODULE, env=environment, stdout=log, stderr=log,
    )
    record = {
        "timestamp_utc": datetime.now(timezone.utc).isoformat(), "python": platform.python_version(),
        "platform": platform.system(), "opencv": cv2.__version__, "model_workers": args.workers,
        "template_mode": "simhash", "liveness_backend": "minifasnet", "identity": [], "pad": [], "load": {},
        "inference_pending": args.pending, "inference_queue_seconds": args.queue_seconds,
        "limitations": ["Identity corpus has only two people; no general FAR/FRR claim.",
                        "PAD samples are three publisher demos, not independent camera/attack validation.",
                        "These are local process timings, not Docker or full-system performance."],
    }
    try:
        with httpx.Client(base_url=url, timeout=90, limits=httpx.Limits(max_connections=120, max_keepalive_connections=120, keepalive_expiry=60)) as client:
            deadline = time.monotonic() + 60
            while time.monotonic() < deadline:
                if server.poll() is not None:
                    raise RuntimeError("Evaluation server failed to start")
                try:
                    if client.get("/ready").status_code == 200:
                        break
                except httpx.HTTPError:
                    pass
                time.sleep(.2)
            else:
                raise RuntimeError("Evaluation server startup timed out")
            def photo(name):
                return base64.b64encode((REPO / "sample_images" / name).read_bytes()).decode("ascii")

            enrollment = client.post("/face/enroll", json={"user_id": "evaluation", "image": photo("obama.jpg"), "camera_consent": True})
            enrollment.raise_for_status()
            reference = enrollment.json()["face_template_hash"]
            for name, expected in (("obama.jpg", True), ("obama2.jpg", True), ("obama3.jpg", True), ("biden.jpg", False)):
                result = client.post("/face/verify", json={"image": photo(name), "reference_template_hash": reference})
                result.raise_for_status()
                data = result.json()
                record["identity"].append({"image": name, "expected_match": expected,
                                          "actual_match": data["match_passed"], "score": data["match_score"]})
                print(f"Identity: {record['identity'][-1]}", flush=True)
            for name, (expected, _) in PAD_SAMPLES.items():
                result = client.post("/liveness/check", json={"challenge_response": pad_images[name]})
                result.raise_for_status()
                data = result.json()
                record["pad"].append({"image": name, "expected_live": expected, "actual_live": data["liveness_passed"],
                                      "score": data["liveness_score"], "neural_score": data["details"]["anti_spoof_real_score"]})
                print(f"PAD: {record['pad'][-1]}", flush=True)
            environment["TEST_FACE_URL"] = url
            public = subprocess.run([sys.executable, "-m", "pytest", "tests/public/test_face_recognition.py", "-q"], cwd=REPO, env=environment)
            record["public_test_exit_code"] = public.returncode
            for path, payload, field in (
                ("/face/verify", {"image": photo("obama.jpg"), "reference_template_hash": reference}, "match_passed"),
                ("/liveness/check", {"challenge_response": pad_images["image_T1.jpg"]}, "liveness_passed"),
            ):
                record["load"][path] = [load_measurement(client, path, payload, count, field) for count in args.clients]
            record["final_metrics"] = client.get("/metrics").text
            record["identity_statistics"] = summarize([(row["expected_match"], row["score"], True) for row in record["identity"]], .7, "identity")
            record["pad_statistics"] = summarize([(row["expected_live"], row["score"], True) for row in record["pad"]], .6, "pad")
        success = (not record["public_test_exit_code"]
                   and all(row["actual_match"] == row["expected_match"] for row in record["identity"])
                   and all(row["actual_live"] == row["expected_live"] for row in record["pad"])
                   and all(row["successful"] == row["clients"] and row["health_failures"] == 0
                           for rows in record["load"].values() for row in rows))
        record["functional_checks_passed"] = success
        report_path.parent.mkdir(parents=True, exist_ok=True)
        report_path.write_text(json.dumps(record, indent=2), encoding="utf-8")
        print(f"Saved scores/timings only: {report_path}", flush=True)
        return 0 if success else 1
    finally:
        record["server_exit_before_cleanup"] = server.poll()
        server.terminate()
        try:
            server.wait(timeout=10)
        except subprocess.TimeoutExpired:
            server.kill()
            server.wait(timeout=5)
        log.close()
        report_path.write_text(json.dumps(record, indent=2), encoding="utf-8")


if __name__ == "__main__":
    sys.exit(main())
