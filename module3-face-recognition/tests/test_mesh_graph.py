from pathlib import Path

import base64
import mediapipe as mp
import numpy as np
import pytest

from app.services import mesh
from app.services.image import decode_base64_image


@pytest.mark.parametrize("sample", ["obama.jpg", "obama2.jpg", "obama3.jpg", "biden.jpg"])
def test_static_config_graph_matches_stock_mesh_numerically(sample):
    path = Path(__file__).resolve().parents[2] / "sample_images" / sample
    image = decode_base64_image(base64.b64encode(path.read_bytes()).decode("ascii"))
    with mp.solutions.face_mesh.FaceMesh(static_image_mode=True, max_num_faces=1,
                                       refine_landmarks=False, min_detection_confidence=.5) as original:
        reference = original.process(image).multi_face_landmarks
    result = mesh.landmarks_for_image(image)
    assert len(reference or []) == len(result)
    if reference:
        left = np.array([[item.x, item.y, item.z] for item in reference[0].landmark])
        right = np.array([[item.x, item.y, item.z] for item in result[0].landmark])
        assert len(left) == len(right) == 468
        np.testing.assert_allclose(left, right, atol=1e-7, rtol=0)
    # A separate graph must not reuse the last image's landmarks for blank input.
    assert mesh.landmarks_for_image(np.full((256, 256, 3), 128, np.uint8)) == []


@pytest.mark.parametrize("fail_at", ["start", "process"])
def test_graph_is_closed_even_when_processing_fails(monkeypatch, fail_at):
    closed = []

    class Graph:
        def __init__(self, **options):
            assert options == {"validated_graph_config": "static-config-only"}

        def observe_output_stream(self, *_):
            pass

        def start_run(self, side_packets):
            assert mp.packet_getter.get_bool(side_packets["use_prev_landmarks"]) is False
            assert mp.packet_getter.get_bool(side_packets["with_attention"]) is False
            if fail_at == "start":
                raise RuntimeError("start failed")

        def add_packet_to_input_stream(self, *_):
            pass

        def wait_until_idle(self):
            raise RuntimeError("process failed")

        def close(self):
            closed.append(True)

    monkeypatch.setattr(mesh, "validated_config", lambda: "static-config-only")
    monkeypatch.setattr(mesh.mp, "CalculatorGraph", Graph)
    with pytest.raises(RuntimeError):
        mesh.landmarks_for_image(np.zeros((256, 256, 3), np.uint8))
    assert closed == [True]
