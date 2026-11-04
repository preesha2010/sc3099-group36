"""Backend-independent real HTTP workflow, restart, overload and soak checks.

No database, frontend, Redis, Docker or external inference service is used.
Only aggregate status/timing/memory data is written; templates stay in memory.
"""

import argparse
import base64
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from io import BytesIO
import math
import os
import platform
import sys
import time
import traceback

from PIL import Image
import httpx
import cv2

from support import MODULE, checked, local_service, metric_value, report_target, save_report


def accumulate(summary, wave_result):
    summary["waves"] = summary.get("waves", 0) + 1
    summary["requests"] = summary.get("requests", 0) + wave_result["clients"]
    summary["successful_200"] = summary.get("successful_200", 0) + wave_result["successful_200"]
    summary["health_failures"] = summary.get("health_failures", 0) + wave_result["health_failures"]
    summary["maximum_seconds"] = max(summary.get("maximum_seconds", 0), wave_result["maximum_seconds"])
    summary["worst_wave_p95_seconds"] = max(summary.get("worst_wave_p95_seconds", 0), wave_result["p95_all_seconds"])
    summary["status_counts"] = counts = summary.get("status_counts", {})
    for status, count in wave_result["status_counts"].items():
        counts[status] = counts.get(status, 0) + count


def memory_summary(samples, budget):
    values = [sample["rss_bytes"] for sample in samples if sample["rss_bytes"] is not None]
    if not values:
        return {"available": False}
    size = min(10, max(1, len(values) // 4))
    start_mean = sum(values[:size]) / size
    end_mean = sum(values[-size:]) / size
    return {"available": True, "sample_count": len(values), "window_samples": size,
            "initial_bytes": values[0], "final_bytes": values[-1], "peak_bytes": max(values),
            "end_minus_initial_mib": round((values[-1] - values[0]) / 1024 ** 2, 3),
            "window_growth_mib": round((end_mean - start_mean) / 1024 ** 2, 3),
            "growth_within_budget": max(values[-1] - values[0], end_mean - start_mean) <= budget * 1024 ** 2}


def percentile(values, q):
    return sorted(values)[max(0, math.ceil(len(values) * q) - 1)] if values else None


def wave(client, path, payload, clients):
    def call(_):
        start = time.monotonic()
        try:
            response = client.post(path, json=payload)
            valid = False
            if response.status_code == 200:
                data = response.json()
                valid = (data.get("match_passed") is True if path == "/face/verify" else
                         isinstance(data.get("liveness_passed"), bool) and
                         data["liveness_passed"] == (data["liveness_score"] >= .6))
            elif response.status_code == 503:
                valid = response.headers.get("retry-after") == "1"
            return str(response.status_code), time.monotonic() - start, valid
        except (httpx.HTTPError, ValueError):
            return "transport_or_json_error", time.monotonic() - start, False

    health_times, health_failures = [], 0
    with ThreadPoolExecutor(clients) as pool:
        futures = [pool.submit(call, index) for index in range(clients)]
        while not all(item.done() for item in futures):
            start = time.monotonic()
            try:
                client.get("/health").raise_for_status()
            except httpx.HTTPError:
                health_failures += 1
            health_times.append(time.monotonic() - start)
            time.sleep(.02)
        rows = [item.result() for item in futures]
    ok = [seconds for status, seconds, valid in rows if status == "200" and valid]
    return {
        "clients": clients, "status_counts": {status: sum(row[0] == status for row in rows) for status in sorted({row[0] for row in rows})},
        "successful_200": len(ok), "all_responses_contract_valid": all(row[2] for row in rows),
        "p95_all_seconds": round(percentile([row[1] for row in rows], .95), 4),
        "p95_successful_seconds": round(percentile(ok, .95), 4) if ok else None,
        "maximum_seconds": round(max(row[1] for row in rows), 4),
        "health_maximum_seconds": round(max(health_times, default=0), 4), "health_failures": health_failures,
    }


def workflow(client, photo, previous_reference=None):
    enrollment = checked(client, "/face/enroll", {"user_id": "module3-local-contract", "image": photo, "camera_consent": True}, 201)
    reference = enrollment["face_template_hash"]
    assert len(reference) == 64 and all(c in "0123456789abcdef" for c in reference)
    verify_payload = {"image": photo, "reference_template_hash": reference}
    matched = checked(client, "/face/verify", verify_payload)
    assert matched["match_passed"] is True and matched["match_score"] >= matched["match_threshold"]
    if previous_reference is not None:
        assert checked(client, "/face/verify", {**verify_payload, "reference_template_hash": previous_reference})["match_passed"]
    legacy = checked(client, "/face/match", {"image": photo, "reference_hash": reference})
    assert legacy["match_passed"] is True and len(legacy["face_embedding_hash"]) == 64
    live = checked(client, "/liveness/check", {"challenge_response": photo})
    assert live["liveness_passed"] == (live["liveness_score"] >= .6)
    assert live["details"]["motion_verified"] is False
    risk = checked(client, "/risk/assess", {"liveness_score": live["liveness_score"], "face_match_score": matched["match_score"]})
    assert abs(sum(risk["signal_breakdown"].values()) - risk["risk_score"]) < 1e-8
    assert risk["pass_threshold"] == (risk["risk_score"] < .5)
    worse = checked(client, "/risk/assess", {"liveness_score": 0, "face_match_score": 0})
    assert worse["risk_score"] >= risk["risk_score"]
    checked(client, "/face/enroll", {"user_id": "test", "image": photo, "camera_consent": False}, 400)
    checked(client, "/face/verify", {**verify_payload, "reference_template_hash": "invalid"}, 422)
    checked(client, "/face/verify", {**verify_payload, "image": "not-base64"}, 400)
    checked(client, "/liveness/check", {"challenge_response": photo, "challenge_type": "blink"}, 400)
    checked(client, "/risk/assess", {"face_match_score": 1.1}, 422)
    buffer = BytesIO()
    Image.new("RGB", (256, 256), "gray").save(buffer, format="PNG")
    blank = base64.b64encode(buffer.getvalue()).decode("ascii")
    assert checked(client, "/face/verify", {**verify_payload, "image": blank})["face_detected"] is False
    assert checked(client, "/liveness/check", {"challenge_response": blank})["liveness_passed"] is False
    assert client.get("/ready").status_code == 200
    return reference


def run(args, report):
    photo = base64.b64encode((MODULE.parent / "sample_images" / "obama.jpg").read_bytes()).decode("ascii")
    carry_reference = None
    for _ in range(args.restarts):
        with local_service(args.profile) as client:
            carry_reference = workflow(client, photo, carry_reference)
            report["restart_workflows_passed"] += 1
    with local_service(args.profile) as client:
        reference = workflow(client, photo, carry_reference)
        payloads = {"/face/verify": {"image": photo, "reference_template_hash": reference},
                    "/liveness/check": {"challenge_response": photo}}
        # Warm complete pipelines before the RSS baseline (not just weights).
        for path, payload in payloads.items():
            warm = wave(client, path, payload, args.clients)
            assert warm["successful_200"] == args.clients
        samples = []
        def snapshot():
            text = client.get("/metrics").text
            rss = metric_value(text, "module3_process_resident_bytes")
            samples.append({"elapsed_seconds": round(time.monotonic() - start, 3), "rss_bytes": rss})
            return text
        start = time.monotonic()
        snapshot()
        last_checkpoint = start
        while True:
            for path, payload in payloads.items():
                measured = wave(client, path, payload, args.clients)
                accumulate(report["sustained"][path], measured)
                assert measured["successful_200"] == args.clients and measured["health_failures"] == 0
            snapshot()
            # Keep checkpoints bounded: at most one memory sample per five seconds
            # in the report; all samples still contribute to summary calculations.
            report["soak_actual_seconds"] = round(time.monotonic() - start, 3)
            if time.monotonic() - last_checkpoint >= 30:
                report["memory"] = memory_summary(samples, args.max_rss_growth_mib)
                report["state"] = "soaking"
                save_report(report_target(args.report), report)
                print(f"Soak {args.profile}: {report['soak_actual_seconds']:.0f}s; "
                      f"verify={report['sustained']['/face/verify']['successful_200']}; "
                      f"live={report['sustained']['/liveness/check']['successful_200']}", flush=True)
                last_checkpoint = time.monotonic()
            if time.monotonic() - start >= args.soak_seconds:
                break
        report["soak_actual_seconds"] = round(time.monotonic() - start, 3)
        report["memory"] = memory_summary(samples, args.max_rss_growth_mib)
        report["memory_samples"] = [sample for index, sample in enumerate(samples)
                                    if index == 0 or index == len(samples) - 1
                                    or sample["elapsed_seconds"] // 5 != samples[index - 1]["elapsed_seconds"] // 5]
        if report["memory"]["available"]:
            assert report["memory"]["growth_within_budget"]
        for path, payload in payloads.items():
            burst = wave(client, path, payload, args.burst)
            report["burst"][path] = burst
            assert burst["all_responses_contract_valid"] and burst["health_failures"] == 0
            # A rejection is NOT counted as a successful inference.
            assert set(burst["status_counts"]) <= {"200", "503"}
        for path, payload in payloads.items():
            checked(client, path, payload)
        assert client.get("/ready").status_code == 200
        metrics_text = client.get("/metrics").text
        assert metric_value(metrics_text, "module3_inference_active") == 0
        assert metric_value(metrics_text, "module3_inference_pending") == 0
        report["overload_rejections_total"] = metric_value(metrics_text, "module3_overload_rejections_total")
        # Contains fixed labels, numeric aggregates and memory only.
        report["final_metrics"] = metrics_text
    report["five_second_sustained_target_met"] = all(
        summary["maximum_seconds"] < 5 for summary in report["sustained"].values())


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--profile", choices=["sha256", "enhanced"], default="sha256")
    parser.add_argument("--soak-seconds", type=int, default=120)
    parser.add_argument("--clients", type=int, default=4)
    parser.add_argument("--burst", type=int, default=100)
    parser.add_argument("--restarts", type=int, default=2)
    parser.add_argument("--max-rss-growth-mib", type=int, default=128)
    parser.add_argument("--report", default="evaluation/acceptance.json")
    args = parser.parse_args()
    if not (0 <= args.soak_seconds <= 3600 and 1 <= args.clients <= 16 and 1 <= args.burst <= 100
            and 1 <= args.restarts <= 5 and args.max_rss_growth_mib > 0):
        parser.error("Invalid soak duration, client count, restart count or memory budget")
    target = report_target(args.report)
    record = {"timestamp_utc": datetime.now(timezone.utc).isoformat(), "profile": args.profile,
              "format_version": 2, "python": platform.python_version(), "platform": platform.system(),
              "opencv": cv2.__version__, "configuration": {
                  name: os.getenv(name, default) for name, default in {
                      "FACE_MODEL_WORKERS": "4", "FACE_NATIVE_THREADS": "1", "INFERENCE_CONCURRENCY": "8",
                      "INFERENCE_PENDING": "32", "INFERENCE_QUEUE_SECONDS": "2"}.items()},
              "requested_soak_seconds": args.soak_seconds, "clients": args.clients,
              "rss_growth_budget_mib": args.max_rss_growth_mib, "restart_workflows_passed": 0,
              "sustained": {"/face/verify": {}, "/liveness/check": {}}, "burst": {}, "passed": False,
              "limitations": ["Local process only; not Docker/full-system validation.",
                              "Successful overload rejection does not mean 100-client inference latency meets a target.",
                              "Finite RSS observation is not proof of absence of memory leaks.",
                              "Liveness workflow validates score propagation, not general anti-spoof accuracy."]}
    try:
        run(args, record)
        record["passed"] = record["five_second_sustained_target_met"]
        record["state"] = "complete"
    except Exception as exc:
        # Never stringify HTTP exceptions/tracebacks that might contain input.
        record["failure_type"] = type(exc).__name__
        record["state"] = "failed"
        last = traceback.extract_tb(exc.__traceback__)[-1]
        record["failure_location"] = {"function": last.name, "line": last.lineno}
    finally:
        save_report(target, record)
    print(f"Acceptance passed={record['passed']}; report={target}", flush=True)
    return 0 if record["passed"] else 1


if __name__ == "__main__":
    sys.exit(main())
