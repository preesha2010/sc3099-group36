"""Explicitly enable the lecture's SimHash profile and pretrained PAD models."""

import argparse
import os
from pathlib import Path
import sys

import uvicorn

MODULE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(MODULE))


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8001)
    parser.add_argument("--workers", type=int, default=4, choices=range(1, 9), help="In-process model slots, not Uvicorn worker processes")
    args = parser.parse_args()
    os.environ.update(FACE_TEMPLATE_MODE="simhash", LIVENESS_BACKEND="minifasnet", FACE_MODEL_WORKERS=str(args.workers),
                      OPENBLAS_NUM_THREADS="1", OMP_NUM_THREADS="1", GLOG_minloglevel="2", TF_CPP_MIN_LOG_LEVEL="2")
    from app.services.neural import pool
    from app.services.templates import template_key
    template_key()
    for name in ("yunet", "sface", "pad"):
        pool(name)
    uvicorn.run("app.main:app", host=args.host, port=args.port, timeout_keep_alive=60, access_log=False)


if __name__ == "__main__":
    main()
