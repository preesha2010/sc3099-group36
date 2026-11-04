"""Check the canonical synthetic risk corpus over HTTP or a trusted fallback.

Default: own loopback M3 service; no biometrics, backend, DB or private key.
--candidate package.module:function receives a raw JSON dictionary, returns
the risk response, and raises ValueError for invalid inputs. Its module must
declare RISK_POLICY_ID/RISK_POLICY_SHA256. Only load trusted project code.
"""

import argparse
from copy import deepcopy
from datetime import datetime, timezone
import hashlib
import importlib
import json
import math
from pathlib import Path
import re
import sys
from urllib.parse import urlsplit

import httpx

from support import MODULE, local_service, report_target, save_report

MANIFEST_PATH = MODULE / "app" / "contracts" / "risk-v1.json"
CASES_PATH = MODULE / "contracts" / "risk-v1-cases.json"


def corpus():
    manifest = json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))
    data = json.loads(CASES_PATH.read_text(encoding="utf-8"))
    digest = hashlib.sha256(json.dumps(manifest, sort_keys=True, separators=(",", ":"),
                                       allow_nan=False).encode()).hexdigest()
    cases = data["cases"]
    names = [case["id"] for case in cases]
    if (data["policy_id"] != manifest["policy_id"] or not cases or len(names) != len(set(names))
            or any(not re.fullmatch(r"[a-z0-9_]{1,80}", name) for name in names)):
        raise ValueError("Invalid local contract corpus")
    return manifest, digest, cases


def agrees(actual, expected, tolerance=1e-9):
    """Compare strict finite numeric semantics; never accept bool as a score."""
    if not isinstance(actual, dict):
        return False
    for name in ("risk_score", "risk_threshold"):
        value = actual.get(name)
        if (type(value) not in (int, float) or not math.isfinite(value) or not 0 <= value <= 1
                or abs(value - expected[name]) > tolerance):
            return False
    if (type(actual.get("pass_threshold")) is not bool
            or actual["pass_threshold"] != expected["pass_threshold"]
            or actual.get("risk_level") != expected["risk_level"]):
        return False
    breakdown = actual.get("signal_breakdown")
    if not isinstance(breakdown, dict) or set(breakdown) != set(expected["signal_breakdown"]):
        return False
    for name, target in expected["signal_breakdown"].items():
        value = breakdown[name]
        if (type(value) not in (int, float) or not math.isfinite(value) or not 0 <= value <= 1
                or abs(value - target) > tolerance):
            return False
    return (abs(sum(breakdown.values()) - actual["risk_score"]) <= tolerance
            and actual["pass_threshold"] == (actual["risk_score"] < actual["risk_threshold"]))


def check_cases(cases, operation):
    """Only fixed case IDs/results/types enter reports, never payloads or errors."""
    rows = []
    for case in cases:
        row = {"case": case["id"], "passed": False}
        try:
            status, body = operation(deepcopy(case["input"]))
            row["passed"] = status == case["status"] and (
                agrees(body, case["expected"]) if status == 200 else True)
        except Exception as exc:
            row["failure_type"] = type(exc).__name__
        rows.append(row)
    return rows


def candidate_operation(function):
    def call(payload):
        try:
            return 200, function(payload)
        except ValueError:
            return 422, None
    return call


def http_checks(client, manifest, digest, cases):
    rows = []
    try:
        policy = client.get("/risk/policy")
        expected = {"policy_id": manifest["policy_id"], "policy_sha256": digest, "manifest": manifest}
        root = client.get("/").json()
        rows.append({"case": "policy_discovery", "passed": policy.status_code == 200 and
                     policy.json() == expected and root["risk_policy_id"] == manifest["policy_id"]
                     and root["risk_policy_sha256"] == digest})
    except Exception as exc:
        rows.append({"case": "policy_discovery", "passed": False, "failure_type": type(exc).__name__})

    def call(payload):
        result = client.post("/risk/assess", json=payload)
        if result.status_code == 200 and (
                result.headers.get("X-Risk-Policy-ID") != manifest["policy_id"]
                or result.headers.get("X-Risk-Policy-SHA256") != digest):
            raise ValueError("Risk response policy mismatch")
        return result.status_code, result.json()
    return rows + check_cases(cases, call)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--base-url", help="Explicit trusted stateless M3 test service; synthetic inputs only")
    mode.add_argument("--candidate", help="Trusted fallback module:function; no M3 code substitution")
    parser.add_argument("--candidate-root", default=str(MODULE), help="Import root for the candidate's own runtime")
    parser.add_argument("--profile", choices=("sha256", "enhanced"), default="sha256")
    parser.add_argument("--report", default="evaluation/risk-contract.json")
    args = parser.parse_args(argv)
    target = report_target(args.report)
    report = {"timestamp_utc": datetime.now(timezone.utc).isoformat(), "completed": False, "passed": False,
              "target": "candidate" if args.candidate else "explicit_http" if args.base_url else "owned_loopback",
              "checks": [], "limitations": [
                  "Synthetic numerical contract only; not full fallback equivalence, DB transactions or attendance authorization.",
                  "A candidate result applies only to that candidate and runtime, not the current M2 branch automatically.",
                  "Required evidence, unavailable vs disabled states, fallback eligibility and final status are M2 responsibilities."]}
    try:
        manifest, digest, cases = corpus()
        report.update(policy_id=manifest["policy_id"], policy_sha256=digest,
                      corpus_sha256=hashlib.sha256(CASES_PATH.read_bytes()).hexdigest())
        if args.candidate:
            if not re.fullmatch(r"[A-Za-z_]\w*(?:\.[A-Za-z_]\w*)*:[A-Za-z_]\w*", args.candidate):
                raise ValueError("Invalid candidate import specification")
            sys.path.insert(0, str(Path(args.candidate_root).resolve()))
            module_name, name = args.candidate.split(":")
            module = importlib.import_module(module_name)
            identified = (getattr(module, "RISK_POLICY_ID", None) == manifest["policy_id"] and
                          getattr(module, "RISK_POLICY_SHA256", None) == digest)
            report["checks"].append({"case": "candidate_policy_identity", "passed": identified})
            report["checks"] += check_cases(cases, candidate_operation(getattr(module, name)))
        else:
            if args.base_url:
                url = urlsplit(args.base_url)
                if (url.scheme not in {"http", "https"} or not url.hostname or url.username is not None
                        or url.password is not None or url.query or url.fragment):
                    raise ValueError("Invalid test service URL")
            context = (httpx.Client(base_url=args.base_url, timeout=5, trust_env=False, follow_redirects=False)
                       if args.base_url else local_service(args.profile))
            with context as client:
                report["checks"] = http_checks(client, manifest, digest, cases)
        report["completed"] = True
        report["passed"] = bool(report["checks"]) and all(row["passed"] for row in report["checks"])
    except Exception as exc:
        report["failure_type"] = type(exc).__name__
    finally:
        save_report(target, report)
    print(f"Risk contract passed={report['passed']}; checks={len(report['checks'])}; report={target}", flush=True)
    return 0 if report["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
