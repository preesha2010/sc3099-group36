# Model provenance and redistribution

The API runtime uses already-declared OpenCV and MediaPipe. No inference call
sends a face image to an external service. Bootstrap downloads weights once.

## OpenCV Zoo SFace

- Project: https://github.com/opencv/opencv_zoo/tree/47534e27c9851bb1128ccc0102f1145e27f23f98/models/face_recognition_sface
- Publisher: OpenCV; SFace contributed by Yaoyao Zhong.
- License: Apache-2.0 (bootstrap keeps `models/LICENSE-SFace.txt`).
- Model: `face_recognition_sface_2021dec.onnx`, SHA-256 pinned in `app/model_assets.py`.
- Used for aligned 128-dimensional identity features; features are transient.

## OpenCV Zoo YuNet

- Project: https://github.com/opencv/opencv_zoo/tree/47534e27c9851bb1128ccc0102f1145e27f23f98/models/face_detection_yunet
- Publisher: OpenCV; license text is kept as `models/LICENSE-YuNet.txt`.
- Model: `face_detection_yunet_2023mar.onnx`, SHA-256 pinned in `app/model_assets.py`.
- Used for detection and the five landmarks needed by SFace alignment.

## MiniVision Silent-Face-Anti-Spoofing

- Project: https://github.com/minivision-ai/Silent-Face-Anti-Spoofing/tree/b6d5f04ad78778917853b25c778acef6d5626d15
- Copyright: MiniVision; original architecture author zhuying.
- License: Apache-2.0 (bootstrap keeps `models/LICENSE-MiniFASNet.txt`).
- Original V2 and V1SE checkpoints and `MiniFASNet.py` are checksum-pinned.
- Bootstrap converts the unchanged architecture/checkpoints to ONNX using
  CPU torch 2.5.1 and ONNX 1.17.0. It uses `weights_only=True` when loading
  checkpoints. The downloaded architecture is hash-verified before import.
- Cropping and BGR pixel preprocessing reproduce the publisher's test pipeline:
  2.7x and 4x patches, float pixel values in [0,255], class 1 = real.
- `models/derived.json` records source commit, tool versions and ONNX checksums.
- Public sample evaluation fetches publisher-labelled images into memory only.
  These three demonstration images are not an independent generalization dataset.

Retain the downloaded license texts and this attribution when distributing model
weights or their converted ONNX versions. Weights and the private template key
are intentionally excluded from Git. Runtime never downloads missing models
automatically; it returns 503 instead of silently using weaker inference.
