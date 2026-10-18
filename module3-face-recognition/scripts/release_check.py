"""Fail-closed LOCAL checks, not a production accuracy certification.

Passing public tests alone must not hide a failed classification gate. This
wrapper stops on the first failure and preserves the child exit status.
"""

import subprocess
import sys
import argparse

from support import MODULE


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--report", default="evaluation/robustness.json")
    args = parser.parse_args(argv)
    for script in ("verify.py", "evaluate_robustness.py"):
        command = [sys.executable, str(MODULE / "scripts" / script)]
        if script == "evaluate_robustness.py":
            command += ["--report", args.report]
        result = subprocess.run(command, cwd=MODULE)
        if result.returncode:
            print(f"Local release checks BLOCKED at {script}; exit={result.returncode}", flush=True)
            return result.returncode
    print("Local smoke gates passed; independent dataset/policy approval is still required.", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
