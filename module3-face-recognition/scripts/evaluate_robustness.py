"""In-memory perturbation diagnostics on existing public smoke samples ONLY.

This expands condition coverage, not the number of independent identities or
attacks. It never collects new faces or stores transformed images/templates.
"""

import argparse
import base64
from datetime import datetime, timezone
import hashlib
from io import BytesIO
import sys

import httpx
from PIL import Image, ImageEnhance, ImageOps

from support import MODULE, local_service, report_target, save_report

sys.path.insert(0, str(MODULE))
from app.evaluation import summarize
from app.model_assets import FAS
from app.services.templates import SCORE_POLICY
from evaluate import PAD_SAMPLES

CONDITIONS = ("original", "dark", "bright", "low_contrast", "rotate_left", "rotate_right", "jpeg40", "resize512")


def perturb(data, condition):
    if condition == "original":
        return data
    with Image.open(BytesIO(data)) as source:
        # Match the API decoder BEFORE re-encoding strips EXIF. Otherwise a
        # portrait tagged Orientation=6 becomes a sideways image, not simply a
        # darker/brighter/compressed version of the same presentation.
        image = ImageOps.exif_transpose(source).convert("RGB")
    if condition == "dark":
        image = ImageEnhance.Brightness(image).enhance(.65)
    elif condition == "bright":
        image = ImageEnhance.Brightness(image).enhance(1.35)
    elif condition == "low_contrast":
        image = ImageEnhance.Contrast(image).enhance(.65)
    elif condition in {"rotate_left", "rotate_right"}:
        image = image.rotate(10 if condition == "rotate_left" else -10, resample=Image.Resampling.BILINEAR,
                             fillcolor=(128, 128, 128))
    elif condition == "resize512":
        image.thumbnail((512, 512), Image.Resampling.LANCZOS)
    elif condition != "jpeg40":
        raise ValueError("Unknown diagnostic condition")
    result = BytesIO()
    image.save(result, format="JPEG", quality=40 if condition == "jpeg40" else 95)
    return result.getvalue()


def encoded(data):
    return base64.b64encode(data).decode("ascii")


def diagnose(client, photos, presentations, report):
    references = {}
    for identity, source in (("a", "obama.jpg"), ("b", "biden.jpg")):
        response = client.post("/face/enroll", json={"user_id": "robustness-diagnostic", "camera_consent": True,
                                                   "image": encoded(photos[source])})
        if response.status_code != 201:
            raise RuntimeError("Diagnostic enrollment failed")
        references[identity] = response.json()["face_template_hash"]
    # The genuine B probe is augmented from its enrollment photo, NOT a second
    # capture. Count this explicitly instead of implying a larger identity corpus.
    pairs = (("a", "obama2.jpg", True), ("a", "obama3.jpg", True), ("b", "biden.jpg", True),
             ("a", "biden.jpg", False), ("b", "obama2.jpg", False))
    for condition in CONDITIONS:
        identity_rows, pad_rows = [], []
        identity_errors, pad_errors = 0, 0
        for target, source, expected in pairs:
            response = client.post("/face/verify", json={"reference_template_hash": references[target],
                "image": encoded(perturb(photos[source], condition))})
            if response.status_code != 200:
                identity_errors += 1
                continue
            data = response.json()
            identity_rows.append((expected, data["match_score"], data["face_detected"]))
        for source, (live, data) in presentations.items():
            response = client.post("/liveness/check", json={"challenge_response": encoded(perturb(data, condition))})
            if response.status_code != 200:
                pad_errors += 1
                continue
            data = response.json()
            pad_rows.append((live, data["liveness_score"], data["details"]["face_detected"]))
        report["conditions"][condition] = {
            "identity": summarize(identity_rows, .7, "identity"), "pad": summarize(pad_rows, .6, "pad"),
            "identity_threshold_sweep": [summarize(identity_rows, threshold, "identity") for threshold in (.7, .75, .8, .85, .9)],
            "pad_threshold_sweep": [summarize(pad_rows, threshold, "pad") for threshold in (.6, .7, .8, .9)],
            "identity_requested": len(pairs), "pad_requested": len(presentations),
            "identity_http_errors": identity_errors, "pad_http_errors": pad_errors}
        print(f"Condition {condition}: identity={len(identity_rows)}, PAD={len(pad_rows)}", flush=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--report", default="evaluation/robustness.json")
    args = parser.parse_args()
    target = report_target(args.report)
    record = {"timestamp_utc": datetime.now(timezone.utc).isoformat(), "conditions": {},
              "transform_version": 2, "exif_orientation_normalized_before_transforms": True,
              "score_policy": SCORE_POLICY,
              "independent_identities": 2, "independent_pad_sources": 3, "newly_collected_faces": 0,
              "identity_pairs_per_condition": 5, "genuine_pairs_derived_from_enrollment_per_condition": 1,
              "transport_checks_passed": False,
              "limitations": ["Existing repository samples and pinned publisher demos only; no new dataset authorization is claimed.",
                              "Transformations are correlated; they are not independent FAR/FRR or PAD trials.",
                              "The B genuine probe is derived from its enrollment image, not a separate capture.",
                              "Rates and binomial intervals are descriptive, not population security estimates.",
                              "Misclassifications remain in the report; production thresholds are never changed."]}
    try:
        photos = {name: (MODULE.parent / "sample_images" / name).read_bytes()
                  for name in ("obama.jpg", "obama2.jpg", "obama3.jpg", "biden.jpg")}
        presentations = {}
        with httpx.Client(timeout=60, follow_redirects=True) as fetch:
            for name, (live, checksum) in PAD_SAMPLES.items():
                response = fetch.get(f"{FAS}/images/sample/{name}")
                response.raise_for_status()
                if hashlib.sha256(response.content).hexdigest() != checksum:
                    raise RuntimeError("Publisher diagnostic checksum mismatch")
                presentations[name] = (live, response.content)
        with local_service("enhanced") as client:
            diagnose(client, photos, presentations, record)
        record["transport_checks_passed"] = all(row["identity_http_errors"] == row["pad_http_errors"] == 0
                                                for row in record["conditions"].values())
        record["all_conditions_classified_correctly"] = all(
            row["identity"]["FAR"]["errors"] == row["identity"]["FRR"]["errors"] ==
            row["pad"]["APCER"]["errors"] == row["pad"]["BPCER"]["errors"] == 0
            for row in record["conditions"].values())
        record["release_gate_passed"] = record["transport_checks_passed"] and record["all_conditions_classified_correctly"]
    except Exception as exc:
        record["failure_type"] = type(exc).__name__
    finally:
        save_report(target, record)
    print(f"Robustness transport checks={record['transport_checks_passed']}; "
          f"classification gate={record.get('release_gate_passed', False)}; report={target}")
    if not record["transport_checks_passed"]:
        return 1
    return 0 if record["release_gate_passed"] else 2


if __name__ == "__main__":
    sys.exit(main())
