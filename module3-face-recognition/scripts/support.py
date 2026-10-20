"""Module-local HTTP test utilities. Own only the subprocess created here."""

from contextlib import contextmanager
import json
import os
from pathlib import Path
import socket
import subprocess
import sys
import time
import tempfile

import httpx

MODULE = Path(__file__).resolve().parents[1]


def report_target(value):
    path = (MODULE / value).resolve()
    if not path.is_relative_to(MODULE):
        raise ValueError("Report must stay inside Module 3")
    if path.suffix != ".json" or path.parent != MODULE / "evaluation":
        raise ValueError("Report must be a JSON file directly inside evaluation/")
    return path


def save_report(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    content = json.dumps(data, indent=2, allow_nan=False)
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", dir=path.parent,
                                         prefix=path.stem + "-", suffix=".tmp", delete=False) as stream:
            temporary = Path(stream.name)
            stream.write(content)
        os.replace(temporary, path)
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)


@contextmanager
def local_service(profile="sha256", overrides=None):
    environment = os.environ.copy()
    environment.update(FACE_TEMPLATE_MODE="simhash" if profile == "enhanced" else "sha256",
                       LIVENESS_BACKEND="minifasnet" if profile == "enhanced" else "heuristic",
                       REQUEST_BODY_SECONDS="3", OTEL_EXPORTER_OTLP_ENDPOINT="",
                       OPENBLAS_NUM_THREADS="1", OMP_NUM_THREADS="1", GLOG_minloglevel="2", TF_CPP_MIN_LOG_LEVEL="2")
    environment.update(overrides or {})
    with socket.socket() as listener:
        listener.bind(("127.0.0.1", 0))
        port = listener.getsockname()[1]
    server = subprocess.Popen(
        [sys.executable, "-m", "uvicorn", "app.main:app", "--host", "127.0.0.1", "--port", str(port),
         "--timeout-keep-alive", "60", "--no-access-log"],
        cwd=MODULE, env=environment, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    try:
        with httpx.Client(base_url=f"http://127.0.0.1:{port}", timeout=5,
                          limits=httpx.Limits(max_connections=128, max_keepalive_connections=128, keepalive_expiry=60)) as client:
            deadline = time.monotonic() + 60
            while time.monotonic() < deadline:
                if server.poll() is not None:
                    raise RuntimeError("Local service failed startup preflight")
                try:
                    if client.get("/ready").status_code == 200:
                        break
                except httpx.HTTPError:
                    pass
                time.sleep(.1)
            else:
                raise RuntimeError("Local service did not become ready")
            yield client
    finally:
        server.terminate()
        try:
            server.wait(timeout=10)
        except subprocess.TimeoutExpired:
            server.kill()
            server.wait(timeout=5)


def metric_value(text, name):
    for line in text.splitlines():
        if line.startswith(name + " "):
            return float(line.split()[-1])
    return None


def checked(client, path, payload, expected=200):
    result = client.post(path, json=payload)
    if result.status_code != expected:
        raise RuntimeError(f"HTTP contract check failed: {path} expected {expected}, got {result.status_code}")
    return result.json()
