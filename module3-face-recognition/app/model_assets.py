"""Pinned upstream assets. No network access occurs during an API request."""

from pathlib import Path
import os
from functools import lru_cache

MODULE_DIR = Path(__file__).resolve().parents[1]
ZOO_COMMIT = "47534e27c9851bb1128ccc0102f1145e27f23f98"
FAS_COMMIT = "b6d5f04ad78778917853b25c778acef6d5626d15"
ZOO = f"https://media.githubusercontent.com/media/opencv/opencv_zoo/{ZOO_COMMIT}/models"
FAS = f"https://raw.githubusercontent.com/minivision-ai/Silent-Face-Anti-Spoofing/{FAS_COMMIT}"

ASSETS = {
    "sface.onnx": (f"{ZOO}/face_recognition_sface/face_recognition_sface_2021dec.onnx",
                   "0ba9fbfa01b5270c96627c4ef784da859931e02f04419c829e83484087c34e79"),
    "yunet.onnx": (f"{ZOO}/face_detection_yunet/face_detection_yunet_2023mar.onnx",
                   "8f2383e4dd3cfbb4553ea8718107fc0423210dc964f9f4280604804ed2552fa4"),
    "minifas-v2.pth": (f"{FAS}/resources/anti_spoof_models/2.7_80x80_MiniFASNetV2.pth",
                       "a5eb02e1843f19b5386b953cc4c9f011c3f985d0ee2bb9819eea9a142099bec0"),
    "minifas-v1se.pth": (f"{FAS}/resources/anti_spoof_models/4_0_0_80x80_MiniFASNetV1SE.pth",
                         "84ee1d37d96894d5e82de5a57df044ef80a58be2b218b5ed7cdfd875ec2f5990"),
    "retina.caffemodel": (f"{FAS}/resources/detection_model/Widerface-RetinaFace.caffemodel",
                          "d08338a2c207df16a9c566f767fea67fb43ba6fff76ce11e938fe3fabefb9402"),
    "retina.prototxt": (f"{FAS}/resources/detection_model/deploy.prototxt",
                        "9fe2f141b4baee039ed9442da2833e216af40a6ff3e639e7b39258812bcda808"),
    "MiniFASNet.py": (f"{FAS}/src/model_lib/MiniFASNet.py",
                      "e498c4ec5e1ddfaba62b941a126c19d65aa564999f3309661fe43ee8bf38acd7"),
}


@lru_cache(maxsize=4)
def _resolved_directory(value: str) -> Path:
    return Path(value).resolve()


def model_directory() -> Path:
    return _resolved_directory(os.getenv("FACE_MODEL_DIR", str(MODULE_DIR / "models")))
