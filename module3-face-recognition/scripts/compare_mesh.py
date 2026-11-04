"""ASGI algorithm comparison against the original 478-point attention mesh.

This is not a throughput benchmark. Monkeypatching is confined to this separate
diagnostic process; no running service is modified. No image/template is saved.
"""

import argparse
import base64
from datetime import datetime, timezone
import hashlib
import os
import sys

import httpx
import mediapipe as mp
from fastapi.testclient import TestClient

from support import MODULE, checked, report_target, save_report
from evaluate import PAD_SAMPLES
from evaluate_robustness import CONDITIONS, perturb

sys.path.insert(0, str(MODULE))
from app.model_assets import FAS
from app.main import app
from app.services import liveness


def original_attention_mesh(image):
    with mp.solutions.face_mesh.FaceMesh(static_image_mode=True, max_num_faces=1,
                                       refine_landmarks=True, min_detection_confidence=.5) as graph:
        return graph.process(image).multi_face_landmarks or []


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--report", default="evaluation/mesh-comparison.json")
    args = parser.parse_args()
    target = report_target(args.report)
    os.environ.update(FACE_TEMPLATE_MODE="simhash", LIVENESS_BACKEND="minifasnet", FACE_MODEL_WORKERS="4",
                      FACE_NATIVE_THREADS="1", OPENBLAS_NUM_THREADS="1", OMP_NUM_THREADS="1")
    report = {"timestamp_utc": datetime.now(timezone.utc).isoformat(), "conditions": {}, "completed": False,
              "limitations": ["Only three publisher demos and correlated perturbations; no population accuracy claim.",
                              "ASGI algorithm comparison, not real network throughput or production validation."]}
    original = liveness.landmarks_for_image
    try:
        samples = []
        with httpx.Client(timeout=60, follow_redirects=True) as fetch:
            for name, (expected, checksum) in PAD_SAMPLES.items():
                response = fetch.get(f"{FAS}/images/sample/{name}")
                response.raise_for_status()
                if hashlib.sha256(response.content).hexdigest() != checksum:
                    raise RuntimeError("Publisher sample checksum mismatch")
                samples.append((expected, response.content))
        with TestClient(app) as client:
            for condition in CONDITIONS:
                summary = {"comparisons": 0, "reference_errors": 0, "optimized_errors": 0,
                           "decision_disagreements": 0, "maximum_score_difference": 0.}
                for expected, image in samples:
                    payload = {"challenge_response": base64.b64encode(perturb(image, condition)).decode("ascii")}
                    liveness.landmarks_for_image = original_attention_mesh
                    reference = checked(client, "/liveness/check", payload)
                    liveness.landmarks_for_image = original
                    optimized = checked(client, "/liveness/check", payload)
                    summary["comparisons"] += 1
                    summary["reference_errors"] += reference["liveness_passed"] != expected
                    summary["optimized_errors"] += optimized["liveness_passed"] != expected
                    summary["decision_disagreements"] += reference["liveness_passed"] != optimized["liveness_passed"]
                    summary["maximum_score_difference"] = max(summary["maximum_score_difference"],
                        abs(reference["liveness_score"] - optimized["liveness_score"]))
                report["conditions"][condition] = summary
        report["completed"] = True
        report["all_decisions_agree"] = all(row["decision_disagreements"] == 0 for row in report["conditions"].values())
    except Exception as exc:
        report["failure_type"] = type(exc).__name__
    finally:
        liveness.landmarks_for_image = original
        save_report(target, report)
    print(f"Comparison completed={report['completed']}, decisions agree={report.get('all_decisions_agree', False)}")
    return 0 if report["completed"] and report["all_decisions_agree"] else 1


if __name__ == "__main__":
    sys.exit(main())
