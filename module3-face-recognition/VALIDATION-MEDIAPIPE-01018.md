# MediaPipe 0.10.18 validation (2026-11-02)

The M3 requirements now pin the course-announced MediaPipe 0.10.18, alongside
NumPy 1.26.4 and opencv-contrib-python 4.11.0.86. Validation used Windows,
Python 3.12, the existing pinned models and an isolated non-production test key.

- `pip check`: passed; installed versions were MediaPipe 0.10.18, NumPy 1.26.4,
  and OpenCV 4.11.0.
- Module-local pytest suite: 310 passed, with 13 dependency deprecation warnings.
- Enhanced SimHash/MiniFASNet service: 15/15 public face tests passed; all four
  existing identity examples and all three publisher PAD examples matched their
  expected labels. Both 10-client HTTP checks completed 10/10 successfully.
- The Python 3.11 Linux x86-64 MediaPipe 0.10.18 wheel downloaded successfully,
  and a cross-platform pip dry run resolved binary dependencies. That resolver
  runs on Windows and is not a Linux installation or Docker runtime test.

The sample results are not population accuracy or security estimates. Docker
build, Linux inference, and demo-machine testing remain unverified. Detailed
sample scores and timings are in `evaluation/mediapipe-01018-20261102.json`.
