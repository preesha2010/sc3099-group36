"""Fetch checksum-pinned models; optionally export trusted MiniFASNet weights.

Runtime uses OpenCV only. PyTorch/ONNX are required only for --pad conversion.
No user image is downloaded, uploaded, or written by this script.
"""

import argparse
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import secrets
import sys

import httpx

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app.model_assets import ASSETS, FAS, ZOO_COMMIT, FAS_COMMIT, model_directory


def download(name: str, client: httpx.Client) -> Path:
    target = model_directory() / name
    url, expected = ASSETS[name]
    if target.is_file() and hashlib.sha256(target.read_bytes()).hexdigest() == expected:
        return target
    response = client.get(url)
    response.raise_for_status()
    if hashlib.sha256(response.content).hexdigest() != expected:
        raise RuntimeError(f"Checksum mismatch: {name}")
    target.write_bytes(response.content)
    print(f"Verified model asset: {name}", flush=True)
    return target


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--pad", action="store_true", help="Export both anti-spoofing models (requires CPU torch 2.5.1 and onnx)")
    args = parser.parse_args()
    directory = model_directory()
    directory.mkdir(parents=True, exist_ok=True)
    with httpx.Client(timeout=120, follow_redirects=True) as client:
        for name in ("sface.onnx", "yunet.onnx"):
            download(name, client)
        key_path = directory / "template.key"
        if not key_path.exists():
            with os.fdopen(os.open(key_path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600), "wb") as stream:
                stream.write(secrets.token_bytes(32))
            print("Created private template key; back it up, never commit it.", flush=True)

        # Include upstream license texts alongside the downloaded/derived models.
        licenses = {
            "LICENSE-SFace.txt": f"https://raw.githubusercontent.com/opencv/opencv_zoo/{ZOO_COMMIT}/models/face_recognition_sface/LICENSE",
            "LICENSE-YuNet.txt": f"https://raw.githubusercontent.com/opencv/opencv_zoo/{ZOO_COMMIT}/models/face_detection_yunet/LICENSE",
            "LICENSE-MiniFASNet.txt": f"{FAS}/LICENSE",
        }
        for name, url in licenses.items():
            response = client.get(url)
            response.raise_for_status()
            (directory / name).write_bytes(response.content)
        if not args.pad:
            return
        for name in ("retina.caffemodel", "retina.prototxt"):
            download(name, client)
        try:
            import torch
            import onnx
        except ImportError as exc:
            raise RuntimeError("--pad requires the documented optional model-tools environment") from exc
        if torch.__version__.split("+")[0] != "2.5.1":
            raise RuntimeError("Use torch 2.5.1 for reproducible checked model conversion")
        source = download("MiniFASNet.py", client)
        spec = importlib.util.spec_from_file_location("verified_minifasnet", source)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        torch.set_num_threads(1)
        derived = {"upstream_commit": FAS_COMMIT, "torch": torch.__version__, "onnx": onnx.__version__, "models": {}}
        for name, factory in (("minifas-v2", module.MiniFASNetV2), ("minifas-v1se", module.MiniFASNetV1SE)):
            weight_path = download(name + ".pth", client)
            # Do not execute arbitrary pickle globals from a downloaded checkpoint.
            state = torch.load(weight_path, map_location="cpu", weights_only=True)
            state = {key.removeprefix("module."): value for key, value in state.items()}
            net = factory(conv6_kernel=(5, 5)).eval()
            net.load_state_dict(state, strict=True)
            model_path = directory / (name + ".onnx")
            torch.onnx.export(net, torch.zeros(1, 3, 80, 80), str(model_path),
                              input_names=["input"], output_names=["logits"], opset_version=11)
            onnx.checker.check_model(onnx.load(str(model_path)))
            derived["models"][model_path.name] = hashlib.sha256(model_path.read_bytes()).hexdigest()
            print(f"Exported checked anti-spoof model: {model_path.name}", flush=True)
        (directory / "derived.json").write_text(json.dumps(derived, indent=2), encoding="utf-8")


if __name__ == "__main__":
    main()
