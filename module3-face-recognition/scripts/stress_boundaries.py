"""Bounded mixed-image HTTP soak using existing samples and synthetic inputs.

Includes exactly 12MP face/blank frames, over-limit headers/dimensions/base64,
corrupt images and normal input. Nothing is written except aggregate evidence.
This is input/resource verification, NOT additional identity/PAD accuracy data.
"""

import argparse
import base64
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from http.client import HTTPResponse
from io import BytesIO
import socket
import time
from urllib.parse import urlsplit

from PIL import Image, ImageOps

from support import MODULE, local_service, metric_value, report_target, save_report
from acceptance import memory_summary


def jpeg(image):
    buffer = BytesIO()
    image.save(buffer, format="JPEG", quality=85)
    return base64.b64encode(buffer.getvalue()).decode("ascii")


def cases():
    original = (MODULE.parent / "sample_images" / "obama.jpg").read_bytes()
    with Image.open(BytesIO(original)) as source:
        enlarged = ImageOps.pad(ImageOps.exif_transpose(source).convert("RGB"), (3000, 4000),
                               method=Image.Resampling.LANCZOS, color=(128, 128, 128))
        large_face = jpeg(enlarged)
    return [
        ("normal", base64.b64encode(original).decode(), 200),
        ("face_exactly_12mp", large_face, 200),
        ("blank_exactly_12mp", jpeg(Image.new("RGB", (3000, 4000), "gray")), 200),
        ("pixels_over_limit", jpeg(Image.new("RGB", (3001, 4000), "gray")), 413),
        ("side_over_limit", jpeg(Image.new("RGB", (4097, 32), "gray")), 413),
        ("below_minimum", jpeg(Image.new("RGB", (31, 32), "gray")), 400),
        ("corrupt", base64.b64encode(b"not-an-image").decode(), 400),
        ("base64_over_limit", base64.b64encode(b"x" * (6 * 1024 * 1024 + 1)).decode(), 413),
    ]


def header_limit(client):
    address = urlsplit(str(client.base_url))
    with socket.create_connection((address.hostname, address.port), timeout=3) as connection:
        connection.settimeout(3)
        connection.sendall(b"POST /face/verify HTTP/1.1\r\nHost: localhost\r\nContent-Length: 10485761\r\n\r\n")
        response = HTTPResponse(connection)
        response.begin()
        return response.status == 413


def request(client, endpoint, case, reference):
    name, image, expected = case
    payload = ({"image": image, "reference_template_hash": reference} if endpoint == "/face/verify"
               else {"challenge_response": image})
    started = time.monotonic()
    response = client.post(endpoint, json=payload)
    duration = time.monotonic() - started
    valid = response.status_code == expected
    if valid and expected == 200:
        data = response.json()
        prefix = "match" if endpoint == "/face/verify" else "liveness"
        valid = (type(data[prefix + "_passed"]) is bool and 0 <= data[prefix + "_score"] <= 1
                 and data[prefix + "_passed"] == (data[prefix + "_score"] >= (.7 if prefix == "match" else .6)))
        if name == "blank_exactly_12mp":
            valid = valid and data[prefix + "_passed"] is False and data[prefix + "_score"] == 0
        if name in {"normal", "face_exactly_12mp"}:
            detected = data.get("face_detected") if prefix == "match" else data.get("details", {}).get("face_detected")
            current = data.get("current_template_hash") if prefix == "match" else data.get("face_embedding_hash")
            valid = valid and detected is True and isinstance(current, str) and len(current) == 64
    return endpoint, name, str(response.status_code), duration, valid


def assignment(wave, index, inputs):
    endpoints = ("/face/verify", "/liveness/check")
    return endpoints[(wave // len(inputs) + index) % 2], inputs[(wave + index) % len(inputs)]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--seconds", type=int, default=120, choices=range(1, 1801))
    parser.add_argument("--clients", type=int, default=4, choices=range(1, 9))
    parser.add_argument("--report", default="evaluation/boundaries.json")
    args = parser.parse_args()
    target = report_target(args.report)
    record = {"timestamp_utc": datetime.now(timezone.utc).isoformat(), "state": "running", "passed": False,
              "profile": "enhanced", "clients": args.clients, "requested_seconds": args.seconds,
              "counts": {}, "health_failures": 0, "maximum_seconds": 0.,
              "limitations": ["Existing sample upscaling/synthetic images are not new authorized accuracy data.",
                              "All workload cases are warmed before memory baseline; allocator high-watermark is not a leak proof.",
                              "Local finite stress, not Docker/full-system or universal deployment capacity validation."]}
    try:
        inputs = cases()
        with local_service("enhanced", {"FACE_MODEL_WORKERS": "4", "FACE_NATIVE_THREADS": "1",
                                        "INFERENCE_CONCURRENCY": "8", "INFERENCE_PENDING": "32",
                                        "INFERENCE_QUEUE_SECONDS": "2"}) as client, ThreadPoolExecutor(args.clients) as workers:
            record["declared_body_over_limit_rejected"] = header_limit(client)
            enrollment = client.post("/face/enroll", json={"user_id": "boundary-probe", "camera_consent": True,
                                                          "image": inputs[0][1]})
            if enrollment.status_code != 201:
                raise RuntimeError("Boundary reference enrollment failed")
            reference = enrollment.json()["face_template_hash"]
            endpoints = ("/face/verify", "/liveness/check")
            # Warm each worst-case combination at the selected concurrency.
            for endpoint in endpoints:
                for case in inputs:
                    results = list(workers.map(lambda _: request(client, endpoint, case, reference), range(args.clients)))
                    if not all(row[-1] for row in results):
                        raise RuntimeError("Boundary warmup contract failed")
            start = checkpoint = time.monotonic()
            memory = []
            waves = 0
            while True:
                metrics = client.get("/metrics").text
                memory.append({"elapsed_seconds": time.monotonic() - start,
                               "rss_bytes": metric_value(metrics, "module3_process_resident_bytes")})
                tasks = [workers.submit(request, client, *assignment(waves, index, inputs), reference)
                         for index in range(args.clients)]
                while not all(task.done() for task in tasks):
                    if client.get("/health").status_code != 200:
                        record["health_failures"] += 1
                    time.sleep(.01)
                for task in tasks:
                    endpoint, name, status, latency, valid = task.result()
                    counter = record["counts"].setdefault(endpoint, {}).setdefault(name, {"requests": 0, "valid": 0, "statuses": {}})
                    counter["requests"] += 1
                    counter["valid"] += valid
                    counter["statuses"][status] = counter["statuses"].get(status, 0) + 1
                    record["maximum_seconds"] = max(record["maximum_seconds"], latency)
                    if not valid:
                        raise RuntimeError("Mixed boundary HTTP contract failed")
                waves += 1
                record["elapsed_seconds"] = round(time.monotonic() - start, 3)
                record["memory"] = memory_summary(memory, 128)
                if time.monotonic() - checkpoint >= 30:
                    save_report(target, record)
                    print(f"Mixed boundary soak: {record['elapsed_seconds']:.0f}s; waves={waves}", flush=True)
                    checkpoint = time.monotonic()
                if time.monotonic() - start >= args.seconds:
                    break
            # Include the final observation, not only pre-wave samples.
            memory.append({"elapsed_seconds": time.monotonic() - start,
                           "rss_bytes": metric_value(client.get("/metrics").text, "module3_process_resident_bytes")})
            record["memory"] = memory_summary(memory, 128)
            record["maximum_seconds"] = round(record["maximum_seconds"], 4)
            record["local_five_second_target_met"] = record["maximum_seconds"] <= 5
            record["all_cases_per_endpoint_observed"] = all(
                len(record["counts"].get(endpoint, {})) == len(inputs) for endpoint in endpoints)
            record["recovery_ready"] = client.get("/ready").status_code == 200
            record["passed"] = (record["declared_body_over_limit_rejected"] and record["recovery_ready"]
                                and record["all_cases_per_endpoint_observed"]
                                and record["memory"].get("growth_within_budget", False)
                                and record["health_failures"] == 0 and record["local_five_second_target_met"])
            record["state"] = "complete"
    except Exception as exc:
        record["state"] = "failed"
        record["failure_type"] = type(exc).__name__
    finally:
        save_report(target, record)
    print(f"Mixed boundary checks passed={record['passed']}; report={target}")
    return 0 if record["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
