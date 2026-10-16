"""Offline, authorized local corpus -> aggregate FAR/FRR and APCER/BPCER.

No image download/copy, image paths, identities, scores per person or templates
are written to reports. Inputs must remain inside the manifest's directory.
"""

import argparse
import base64
from datetime import datetime, timezone
import json
from pathlib import Path
import sys

from support import MODULE, local_service, report_target, save_report

sys.path.insert(0, str(MODULE))
from app.evaluation import summarize


def load_manifest(path):
    if path.stat().st_size > 1024 * 1024:
        raise ValueError("Manifest exceeds size limit")
    manifest = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(manifest, dict) or manifest.get("authorized") is not True:
        raise ValueError("Explicit dataset authorization acknowledgement is required")
    identity, pad = manifest.get("identity", []), manifest.get("pad", [])
    if not isinstance(identity, list) or not isinstance(pad, list) or not 1 <= len(identity) + len(pad) <= 10000:
        raise ValueError("Expected between 1 and 10000 labeled cases")
    for row in identity:
        if not isinstance(row, dict) or type(row.get("same_person")) is not bool:
            raise ValueError("Identity cases require boolean same_person labels")
        for name in ("enroll", "probe"):
            image_path(path, row.get(name))
    for row in pad:
        if not isinstance(row, dict) or type(row.get("live")) is not bool:
            raise ValueError("PAD cases require boolean live labels")
        image_path(path, row.get("image"))
    return identity, pad


def image_path(manifest, value):
    if not isinstance(value, str) or not value or Path(value).is_absolute():
        raise ValueError("Image path must be relative")
    target = (manifest.parent / value).resolve()
    if not target.is_relative_to(manifest.parent) or target.suffix.lower() not in {".jpg", ".jpeg", ".png"}:
        raise ValueError("Image must be a JPEG/PNG inside the dataset directory")
    if not target.is_file() or target.stat().st_size > 6 * 1024 * 1024:
        raise ValueError("Image is missing or too large")
    return target


def photo(manifest, value):
    target = image_path(manifest, value)
    with target.open("rb") as source:
        data = source.read(6 * 1024 * 1024 + 1)
    if len(data) > 6 * 1024 * 1024:
        raise ValueError("Image is too large")
    return base64.b64encode(data).decode("ascii")


def evaluate(client, manifest, identity, pad, report):
    matches, presentations = [], []
    for case in identity:
        enroll = client.post("/face/enroll", json={"user_id": "local-evaluation", "camera_consent": True,
                                                 "image": photo(manifest, case["enroll"])})
        if enroll.status_code != 201:
            report["identity_http_errors"] += 1
            continue
        reference = enroll.json()["face_template_hash"]
        result = client.post("/face/verify", json={"reference_template_hash": reference,
                                                 "image": photo(manifest, case["probe"])})
        if result.status_code != 200:
            report["identity_http_errors"] += 1
            continue
        data = result.json()
        matches.append((case["same_person"], data["match_score"], data["face_detected"]))
    for case in pad:
        result = client.post("/liveness/check", json={"challenge_response": photo(manifest, case["image"])})
        if result.status_code != 200:
            report["pad_http_errors"] += 1
            continue
        data = result.json()
        presentations.append((case["live"], data["liveness_score"], data["details"]["face_detected"]))
    report["identity_at_api_threshold"] = summarize(matches, .7, "identity")
    report["pad_at_api_threshold"] = summarize(presentations, .6, "pad")
    report["identity_threshold_sweep"] = [summarize(matches, threshold, "identity") for threshold in (.5, .6, .7, .8, .9)]
    report["pad_threshold_sweep"] = [summarize(presentations, threshold, "pad") for threshold in (.5, .6, .7, .8, .9)]
    report["identity_evaluated"] = len(matches)
    report["pad_evaluated"] = len(presentations)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("manifest", type=Path)
    parser.add_argument("--report", default="evaluation/corpus.json")
    args = parser.parse_args()
    target = report_target(args.report)
    manifest = args.manifest.resolve()
    record = {"timestamp_utc": datetime.now(timezone.utc).isoformat(), "template_mode": "simhash",
              "liveness_backend": "minifasnet", "identity_http_errors": 0, "pad_http_errors": 0,
              "completed_without_errors": False,
              "limitations": ["Threshold sweeps are descriptive only; production thresholds are unchanged.",
                              "HTTP/quality errors are reported separately, not silently counted as correct rejections.",
                              "Confidence intervals treat comparisons as independent; repeated subjects violate that assumption.",
                              "Population/camera/attack representativeness and subject-disjoint validation require dataset design."]}
    try:
        identity, pad = load_manifest(manifest)
        record["identity_requested"] = len(identity)
        record["pad_requested"] = len(pad)
        record["same_file_identity_pairs"] = sum(image_path(manifest, row["enroll"]) == image_path(manifest, row["probe"]) for row in identity)
        with local_service("enhanced") as client:
            evaluate(client, manifest, identity, pad, record)
        record["completed_without_errors"] = record["identity_http_errors"] == record["pad_http_errors"] == 0
    except Exception as exc:
        record["failure_type"] = type(exc).__name__
    finally:
        save_report(target, record)
    print(f"Corpus evaluation completed={record['completed_without_errors']}; report={target}")
    return 0 if record["completed_without_errors"] else 1


if __name__ == "__main__":
    sys.exit(main())
