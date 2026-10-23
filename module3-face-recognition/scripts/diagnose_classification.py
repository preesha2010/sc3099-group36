"""Separate identity projection errors from PAD/quality-gate counterexamples.

Diagnostic process only: existing samples, original weights/key and unchanged
operating thresholds. Transient vectors are compared in RAM and never reported
or persisted. This is attribution on correlated demos, NOT secure calibration.
"""

import argparse
import base64
from datetime import datetime, timezone
import hashlib
import math
import os
import sys

import httpx
import numpy as np
from fastapi.testclient import TestClient

from support import MODULE, report_target, save_report
from evaluate import PAD_SAMPLES
from evaluate_robustness import CONDITIONS, perturb

sys.path.insert(0, str(MODULE))
from app.main import app
from app.model_assets import FAS
from app.services.face import detect_face, extract_face_embedding, generate_face_hash
from app.services.image import decode_base64_image
from app.services.templates import decode_simhash, match_query_to_template, template_key, projection, SCORE_POLICY


def identity_observation(expected, raw_cosine, estimated_score):
    # Service v3 is normalized query-margin agreement, explicitly NOT raw
    # cosine .70. The equivalent raw-vector diagnostic operating point is .40.
    raw_pass = (1. + raw_cosine) / 2. >= .7
    template_pass = estimated_score >= .7
    return {"comparisons": 1, "raw_equivalent_false_accepts": int(not expected and raw_pass),
            "template_false_accepts": int(not expected and template_pass),
            "raw_equivalent_false_rejects": int(expected and not raw_pass),
            "template_false_rejects": int(expected and not template_pass),
            "projection_decision_disagreements": int(raw_pass != template_pass),
            "template_false_accepts_with_raw_rejection": int(not expected and template_pass and not raw_pass)}


def pad_observation(expected, response):
    if not response["details"]["face_detected"]:
        return {"comparisons": 1, "no_face": 1, "genuine_reject_no_face": int(expected),
                "reconstructed_score_disagreements": int(response["liveness_score"] != 0),
                "genuine_reject_quality_only": 0, "genuine_reject_pad_only": 0,
                "genuine_reject_both": 0, "attacks_accepted_by_both_stages": 0}
    details = response["details"]
    depth = 1. if details["depth_quality"] == "good" else .5 if details["depth_quality"] == "moderate" else 0.
    heuristic = round(.30 * depth + .25 * details["face_mesh_complete"]
                      + .25 * details["texture_analysis_score"] + .20 * details["color_distribution_score"], 3)
    if (details["quality_score"] < .5 or details["sharpness"] < 10.
            or not details["face_mesh_complete"] or details["depth_quality"] == "poor"):
        heuristic = min(heuristic, .49)
    learned = details["anti_spoof_real_score"] if details.get("anti_spoof_face_detected", True) else 0.
    # Report probability is rounded to six decimals like the final API score.
    agrees = abs(round(min(heuristic, learned), 6) - response["liveness_score"]) <= 1e-6
    weak, pad = heuristic >= .6, learned >= .6
    return {"comparisons": 1, "no_face": 0, "genuine_reject_no_face": 0,
            "reconstructed_score_disagreements": int(not agrees),
            "genuine_reject_quality_only": int(expected and not weak and pad),
            "genuine_reject_pad_only": int(expected and weak and not pad),
            "genuine_reject_both": int(expected and not weak and not pad),
            "attacks_accepted_by_both_stages": int(not expected and weak and pad)}


def add(target, values):
    for name, value in values.items():
        target[name] = target.get(name, 0) + value


def features(data):
    rgb = decode_base64_image(base64.b64encode(data).decode("ascii"))
    try:
        detection = detect_face(rgb)
        if detection is None:
            raise RuntimeError("Diagnostic identity input has no face")
        return extract_face_embedding(rgb, detection)
    finally:
        rgb.fill(0)


def orthogonal_planes(planes):
    q, r = np.linalg.qr(planes.T, mode="reduced")
    return (q * np.where(np.diag(r) < 0, -1., 1.)).T.astype(np.float32)


def projection_study_matrices():
    current = projection(template_key()).copy()
    seeded = [np.random.default_rng(seed).standard_normal((64, 128)).astype(np.float32) for seed in range(32)]
    return {"current_random64": [current], "current_orthogonal64": [orthogonal_planes(current)],
            "toy_seed_random64": seeded, "toy_seed_orthogonal64": [orthogonal_planes(item) for item in seeded]}


def diagnose(client, photos, presentations, record, study=False):
    references = {}
    matrices = projection_study_matrices() if study else {}
    if study:
        record["projection_study"] = {name: {"projections": len(values)} for name, values in matrices.items()}
    try:
        for target, name in (("a", "obama.jpg"), ("b", "biden.jpg")):
            vector = features(photos[name])
            references[target] = (vector, generate_face_hash(vector))
        pairs = (("a", "obama2.jpg", True), ("a", "obama3.jpg", True), ("b", "biden.jpg", True),
                 ("a", "biden.jpg", False), ("b", "obama2.jpg", False))
        for condition in CONDITIONS:
            identity, pad, errors, distances = {}, {}, [], {"genuine": [], "impostor": []}
            for target, name, expected in pairs:
                vector = features(perturb(photos[name], condition))
                try:
                    reference, template = references[target]
                    score = match_query_to_template(vector, template)
                    raw_cosine = float(np.clip(np.dot(reference, vector), -1, 1))
                    add(identity, identity_observation(expected, raw_cosine, score))
                    for name, values in matrices.items():
                        for planes in values:
                            left_bits = np.einsum("ij,j->i", planes, reference, optimize=False) >= 0
                            right_bits = np.einsum("ij,j->i", planes, vector, optimize=False) >= 0
                            count = int(np.count_nonzero(left_bits != right_bits))
                            candidate = (1. + math.cos(math.pi * count / 64)) / 2.
                            add(record["projection_study"][name], identity_observation(expected, raw_cosine, candidate))
                    left, right = decode_simhash(template, template_key()), decode_simhash(generate_face_hash(vector), template_key())
                    distance = (int.from_bytes(left, "big") ^ int.from_bytes(right, "big")).bit_count()
                    estimated_cosine = math.cos(math.pi * distance / 64.)
                    errors.append(abs(estimated_cosine - raw_cosine))
                    distances["genuine" if expected else "impostor"].append(distance)
                finally:
                    vector.fill(0)
            identity["historical_hamming_cosine_approximation_absolute_error"] = {
                "mean": round(float(np.mean(errors)), 6), "maximum": round(max(errors), 6)}
            identity["hamming_ranges"] = {label: {"minimum": min(values), "maximum": max(values)}
                                           for label, values in distances.items()}
            for expected, data in presentations:
                response = client.post("/liveness/check", json={
                    "challenge_response": base64.b64encode(perturb(data, condition)).decode("ascii")})
                if response.status_code != 200:
                    raise RuntimeError("PAD diagnostic failed its HTTP contract")
                add(pad, pad_observation(expected, response.json()))
            record["conditions"][condition] = {"identity": identity, "pad": pad}
            print(f"Layer diagnostics: {condition} completed", flush=True)
    finally:
        for vector, _ in references.values():
            vector.fill(0)
        references.clear()
        for values in matrices.values():
            for planes in values:
                planes.fill(0)
        matrices.clear()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--report", default="evaluation/classification-diagnosis.json")
    parser.add_argument("--projection-study", action="store_true", help="Diagnostic-only orthogonal/32-toy-seed comparison; NEVER change live template policy")
    args = parser.parse_args()
    target = report_target(args.report)
    os.environ.update(FACE_TEMPLATE_MODE="simhash", LIVENESS_BACKEND="minifasnet", FACE_MODEL_WORKERS="4",
                      FACE_NATIVE_THREADS="1", OTEL_EXPORTER_OTLP_ENDPOINT="", OPENBLAS_NUM_THREADS="1", OMP_NUM_THREADS="1")
    record = {"timestamp_utc": datetime.now(timezone.utc).isoformat(), "completed": False, "conditions": {},
              "transform_version": 2, "exif_orientation_normalized_before_transforms": True,
              "unchanged_api_threshold": .7, "raw_cosine_equivalent_threshold": .4,
              "score_policy": SCORE_POLICY, "query_second_quantization_removed": True,
              "thresholds_changed": False, "vectors_persisted": False, "newly_collected_faces": 0,
              "limitations": ["Only two identities/three publisher PAD demos; transformations are correlated.",
                              "Raw cosine comparison is diagnostic, not a replacement production matcher or calibrated threshold.",
                              "No vectors, templates, images or individual subject scores are in this aggregate report.",
                              "Successful diagnosis does not mean the biometric classification gate passes."]}
    if args.projection_study:
        record["projection_study_policy"] = "historical_rescaled_hamming_diagnostic_not_current_service"
        record["limitations"].append("Orthogonal projections are an unshipped experiment; 32 toy seeds do not add independent identities or certify a policy.")
    try:
        photos = {name: (MODULE.parent / "sample_images" / name).read_bytes()
                  for name in ("obama.jpg", "obama2.jpg", "obama3.jpg", "biden.jpg")}
        presentations = []
        with httpx.Client(timeout=60, follow_redirects=True) as fetch:
            for name, (expected, checksum) in PAD_SAMPLES.items():
                response = fetch.get(f"{FAS}/images/sample/{name}")
                response.raise_for_status()
                if hashlib.sha256(response.content).hexdigest() != checksum:
                    raise RuntimeError("Publisher diagnostic checksum mismatch")
                presentations.append((expected, response.content))
        with TestClient(app) as client:
            diagnose(client, photos, presentations, record, args.projection_study)
        record["completed"] = True
    except Exception as exc:
        record["failure_type"] = type(exc).__name__
    finally:
        save_report(target, record)
    print(f"Layer diagnosis completed={record['completed']}; not a classification approval; report={target}")
    return 0 if record["completed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
