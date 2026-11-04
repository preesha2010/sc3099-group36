"""Fixed scoring comparison, including rejected formulas and the live policy.

No score formula or operating point is selected automatically from these two
identities. Raw vectors/margins are transient, never exported or persisted.
"""
import argparse
from datetime import datetime, timezone
import math
import os
import sys

import numpy as np

from support import MODULE, report_target, save_report
from diagnose_classification import features
from evaluate_robustness import CONDITIONS, perturb

sys.path.insert(0, str(MODULE))
from app.config import Settings
from app.runtime import Runtime
from app.services.templates import projection, template_key


def observe(target, expected, score):
    target["comparisons"] = target.get("comparisons", 0) + 1
    key = "genuine" if expected else "impostor"
    target[key] = target.get(key, 0) + 1
    error = "false_rejects" if expected else "false_accepts"
    target[error] = target.get(error, 0) + int((score >= .7) != expected)


def run(report):
    photos = {name: (MODULE.parent / "sample_images" / name).read_bytes()
              for name in ("obama.jpg", "obama2.jpg", "obama3.jpg", "biden.jpg")}
    planes = projection(template_key())
    # Sensitivity only: fixed public toy seeds, NEVER a replacement private key.
    toy_planes = np.stack([np.random.default_rng(seed).standard_normal((64, 128))
                           for seed in range(32)])
    references = {}
    try:
        for label, name in (("a", "obama.jpg"), ("b", "biden.jpg")):
            references[label] = features(photos[name])
        pairs = (("a", "obama2.jpg", True), ("a", "obama3.jpg", True), ("b", "biden.jpg", True),
                 ("a", "biden.jpg", False), ("b", "obama2.jpg", False))
        for condition in CONDITIONS:
            result = {}
            for label, name, expected in pairs:
                vector = features(perturb(photos[name], condition))
                try:
                    reference = references[label]
                    reference_signs = np.einsum("ij,j->i", planes, reference, optimize=False) >= 0
                    margins = np.einsum("ij,j->i", planes, vector, optimize=False)
                    distance = int(np.count_nonzero(reference_signs != (margins >= 0)))
                    estimated = math.cos(math.pi * distance / 64)
                    raw = float(np.clip(np.dot(reference, vector), -1, 1))
                    # Gaussian identity: E[sign(a.v) (a.u)] = sqrt(2/pi) cos(u,v)
                    # for unit u/v, a~N(0,I). This uses query margins, not only
                    # query sign bits; no reference vector is needed to compute it.
                    moment = float(math.sqrt(math.pi / 2) * np.mean(np.where(reference_signs, 1., -1.) * margins))
                    candidates = {"historical_rescaled_hamming": (1 + estimated) / 2,
                                  "cosine_hamming": max(0., estimated), "raw_cosine": max(0., raw),
                                  "raw_rescaled": (1 + raw) / 2,
                                  "query_margin_cosine": float(np.clip(moment, 0, 1)),
                                  "query_margin_rescaled": float(np.clip((1 + moment) / 2, 0, 1))}
                    for method, score in candidates.items():
                        observe(result.setdefault(method, {}), expected, score)
                        observe(report["totals"].setdefault(method, {}), expected, score)
                    signs = np.einsum("sij,j->si", toy_planes, reference, optimize=False) >= 0
                    toy_margins = np.einsum("sij,j->si", toy_planes, vector, optimize=False)
                    moments = math.sqrt(math.pi / 2) * np.mean(np.where(signs, 1., -1.) * toy_margins, axis=1)
                    distances = np.count_nonzero(signs != (toy_margins >= 0), axis=1)
                    for method, scores in {
                        "query_margin_rescaled": np.clip((1 + moments) / 2, 0, 1),
                        "historical_rescaled_hamming": (1 + np.cos(np.pi * distances / 64)) / 2,
                    }.items():
                        for score in scores:
                            observe(report["toy_seed_sensitivity"].setdefault(method, {}), expected, score)
                finally:
                    vector.fill(0)
            report["conditions"][condition] = result
    finally:
        for vector in references.values():
            vector.fill(0)
        toy_planes.fill(0)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--report", default="evaluation/scoring-comparison.json")
    args = parser.parse_args()
    target = report_target(args.report)
    os.environ.update(FACE_TEMPLATE_MODE="simhash", LIVENESS_BACKEND="heuristic", FACE_MODEL_WORKERS="4",
                      FACE_NATIVE_THREADS="1", OTEL_EXPORTER_OTLP_ENDPOINT="", OPENBLAS_NUM_THREADS="1", OMP_NUM_THREADS="1")
    report = {"timestamp_utc": datetime.now(timezone.utc).isoformat(), "completed": False, "threshold": .7,
              "conditions": {}, "totals": {}, "toy_seed_sensitivity": {}, "toy_seeds": list(range(32)),
              "formulas_fitted_to_samples": False, "newly_collected_faces": 0,
              "limitations": ["Two identities and correlated transforms only, not a calibration/held-out dataset.",
                              "Only query_margin_rescaled is now live; all other formulas are diagnostic/rejected.",
                              "No production template/key/projection is changed or selected by this script.",
                              "Toy seeds repeat the SAME people; counts are sensitivity, not population error rates.",
                              "Raw vector baselines are diagnostic, never reference-vector storage proposals."]}
    try:
        Runtime(Settings.load()).start()
        run(report)
        report["completed"] = True
    except Exception as exc:
        report["failure_type"] = type(exc).__name__
    finally:
        save_report(target, report)
    print({"completed": report["completed"], "totals": report["totals"]}, flush=True)
    return 0 if report["completed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
