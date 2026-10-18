"""Run standalone Module 3 regression tests and the shared public HTTP tests.

Usage (from module3-face-recognition): python scripts/verify.py
Uses an isolated loopback port; requires no backend, Redis, or PostgreSQL.
"""

import base64
from concurrent.futures import ThreadPoolExecutor
import os
from pathlib import Path
import socket
import subprocess
import sys
import time

import httpx


MODULE = Path(__file__).resolve().parents[1]
REPO = MODULE.parent


def main():
    # A caller's enhanced-mode environment must not accidentally turn this
    # compatibility verification into a different test profile.
    baseline = os.environ.copy()
    baseline.update(FACE_TEMPLATE_MODE="sha256", LIVENESS_BACKEND="heuristic",
                    FACE_MODEL_WORKERS="4", FACE_NATIVE_THREADS="1", INFERENCE_CONCURRENCY="8",
                    INFERENCE_PENDING="32", INFERENCE_QUEUE_SECONDS="2", OPENBLAS_NUM_THREADS="1",
                    OMP_NUM_THREADS="1", GLOG_minloglevel="2", TF_CPP_MIN_LOG_LEVEL="2")
    local = subprocess.run(
        [sys.executable, "-m", "pytest", "--confcutdir=tests", "tests", "-q"], cwd=MODULE, env=baseline,
    )
    if local.returncode:
        return local.returncode

    with socket.socket() as listener:
        listener.bind(("127.0.0.1", 0))
        port = listener.getsockname()[1]
    base_url = f"http://127.0.0.1:{port}"
    server = subprocess.Popen(
        [sys.executable, "-m", "uvicorn", "app.main:app", "--host", "127.0.0.1", "--port", str(port)],
        cwd=MODULE, env=baseline, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
    )
    try:
        deadline = time.monotonic() + 60
        with httpx.Client(base_url=base_url, timeout=10) as client:
            while time.monotonic() < deadline:
                if server.poll() is not None:
                    raise RuntimeError("Module 3 server exited before startup")
                try:
                    if client.get("/health").status_code == 200:
                        break
                except httpx.HTTPError:
                    pass
                time.sleep(.2)
            else:
                raise RuntimeError("Module 3 server startup timed out")

            environment = baseline.copy()
            environment["TEST_FACE_URL"] = base_url
            public = subprocess.run(
                [sys.executable, "-m", "pytest", "tests/public/test_face_recognition.py", "-q"],
                cwd=REPO, env=environment,
            )
            if public.returncode:
                return public.returncode

            # Report the important limitation that the public suite does not test:
            # identity matching across different images of the same person.
            samples = REPO / "sample_images"
            def image(name):
                return base64.b64encode((samples / name).read_bytes()).decode("ascii")

            enrollment = client.post("/face/enroll", json={
                "user_id": "diagnostic-user", "image": image("obama.jpg"), "camera_consent": True,
            })
            enrollment.raise_for_status()
            reference = enrollment.json()["face_template_hash"]
            print("Matching diagnostic (not covered by public score):", flush=True)
            for name in ("obama.jpg", "obama2.jpg", "obama3.jpg", "biden.jpg"):
                result = client.post("/face/verify", json={"image": image(name), "reference_template_hash": reference})
                result.raise_for_status()
                payload = result.json()
                print(f"  {name}: passed={payload['match_passed']}, score={payload['match_score']}", flush=True)

            photo = image("obama.jpg")
            def verify_request(_):
                started = time.monotonic()
                result = client.post("/face/verify", json={"image": photo, "reference_template_hash": reference})
                result.raise_for_status()
                if not result.json()["match_passed"]:
                    raise RuntimeError("Same-image verification failed under concurrent requests")
                return time.monotonic() - started

            with ThreadPoolExecutor(max_workers=10) as workers:
                tasks = [workers.submit(verify_request, index) for index in range(10)]
                health_start = time.monotonic()
                health = client.get("/health")
                health.raise_for_status()
                health_elapsed = time.monotonic() - health_start
                latencies = sorted(task.result() for task in tasks)
            print(f"10 concurrent verifications: 10/10 passed; max latency={latencies[-1]:.3f}s; "
                  f"health latency={health_elapsed:.3f}s (local measurement only)", flush=True)
        return 0
    finally:
        server.terminate()
        try:
            server.wait(timeout=10)
        except subprocess.TimeoutExpired:
            server.kill()
            server.wait(timeout=5)


if __name__ == "__main__":
    sys.exit(main())
