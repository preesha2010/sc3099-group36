"""Startup preflight and local readiness; no network calls or biometric probes."""

import hashlib
import os

import cv2
import numpy as np
import mediapipe as mp

from app.config import Settings
from app.model_assets import model_directory
from app.services.neural import pool, verified_asset
from app.services.templates import template_key
from app.services.mesh import validated_config


def require_native_paths(platform, package_path, model_path=None):
    # The pinned Windows native readers cannot reliably open non-ASCII paths.
    # Fail before serving instead of reporting healthy and returning late 500s.
    if platform == "nt" and (not str(package_path).isascii()
                              or model_path is not None and not str(model_path).isascii()):
        raise ValueError("Use ASCII-only runtime/model paths on Windows; configure FACE_MODEL_DIR if needed")


class Runtime:
    def __init__(self, settings):
        self.settings = settings
        self.directory = model_directory()
        self.assets = {}
        self.pools = []
        self.pool_names = {}
        self.key_digest = None

    def start(self):
        uses_models = self.settings.template_mode == "simhash" or self.settings.liveness_backend == "minifasnet"
        require_native_paths(os.name, mp.__file__, self.directory if uses_models else None)
        validated_config()  # no biometric input; preflight MediaPipe's packaged graph
        required = []
        names = []
        if self.settings.template_mode == "simhash":
            self.key_digest = hashlib.sha256(template_key()).digest()
            required += ["yunet.onnx", "sface.onnx"]
            names += ["yunet", "sface"]
        if self.settings.liveness_backend == "minifasnet":
            required += ["retina.caffemodel", "retina.prototxt", "minifas-v2.onnx", "minifas-v1se.onnx"]
            names += ["pad"]
            required += ["derived.json"]
        for name in required:
            path = self.directory / name
            if name != "derived.json":
                verified_asset(name)
            self.assets[name] = (path.stat().st_size, path.stat().st_mtime_ns)
        for name in names:
            instance = pool(name)
            # Warm every slot with blank data, not a real face.
            held = []
            try:
                for _ in range(instance.count):
                    context = instance.borrow()
                    model = context.__enter__()
                    held.append(context)
                    if name == "yunet":
                        model.setInputSize((320, 320))
                        model.detect(np.zeros((320, 320, 3), np.uint8))
                    elif name == "sface":
                        model.feature(np.zeros((112, 112, 3), np.uint8))
                    else:
                        detector, nets = model
                        detector.setInput(cv2.dnn.blobFromImage(np.zeros((192, 192, 3), np.uint8), 1, mean=(104, 117, 123)), "data")
                        detector.forward("detection_out")
                        for net in nets:
                            net.setInput(np.zeros((1, 3, 80, 80), np.float32))
                            net.forward()
            except BaseException:
                # Failed warmup must not return a possibly dirty instance.
                import sys
                info = sys.exc_info()
                for context in reversed(held):
                    context.__exit__(*info)
                raise
            else:
                for context in reversed(held):
                    context.__exit__(None, None, None)
            self.pools.append(instance)
            self.pool_names[name] = instance

    def unchanged(self):
        try:
            if Settings.load() != self.settings or model_directory() != self.directory:
                return False
            for name, fingerprint in self.assets.items():
                stat = (self.directory / name).stat()
                if (stat.st_size, stat.st_mtime_ns) != fingerprint:
                    # Model files/config are immutable during a run; restart to re-verify.
                    return False
            if self.key_digest is not None:
                data = (self.directory / "template.key").read_bytes()
                if hashlib.sha256(data).digest() != self.key_digest:
                    return False
            return True
        except (OSError, ValueError):
            return False

    def recover(self):
        if self.unchanged():
            for instance in self.pools:
                if not instance.healthy:
                    instance.repair()

    def ready(self):
        return self.unchanged() and all(instance.healthy for instance in self.pools)
