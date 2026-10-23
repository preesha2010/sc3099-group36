from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from diagnose_classification import identity_observation, pad_observation, orthogonal_planes


def test_identity_diagnostic_compares_equivalent_thresholds_without_rescaling_policy():
    result = identity_observation(False, .2, .75)
    assert result["template_false_accepts"] == result["template_false_accepts_with_raw_rejection"] == 1
    assert result["raw_equivalent_false_accepts"] == 0
    assert identity_observation(False, .8, .75)["raw_equivalent_false_accepts"] == 1
    assert identity_observation(True, .8, .75)["projection_decision_disagreements"] == 0


def test_pad_diagnostic_attributes_quality_and_neural_failures_separately():
    details = {"face_detected": True, "depth_quality": "good", "face_mesh_complete": True,
               "texture_analysis_score": 1., "color_distribution_score": 1.,
               "quality_score": .9, "sharpness": 100., "anti_spoof_real_score": .9}
    assert pad_observation(False, {"details": details, "liveness_score": .9})["attacks_accepted_by_both_stages"] == 1
    result = pad_observation(True, {"details": {**details, "quality_score": .4}, "liveness_score": .49})
    assert result["genuine_reject_quality_only"] == 1 and result["reconstructed_score_disagreements"] == 0
    assert pad_observation(True, {"details": {**details, "anti_spoof_real_score": .1}, "liveness_score": .1})["genuine_reject_pad_only"] == 1


def test_diagnostic_orthogonalization_is_deterministic_and_does_not_mutate_original_planes():
    import numpy as np
    planes = np.random.default_rng(42).standard_normal((64, 128)).astype(np.float32)
    original = planes.copy()
    result = orthogonal_planes(planes)
    np.testing.assert_array_equal(planes, original)
    np.testing.assert_array_equal(result, orthogonal_planes(planes))
    np.testing.assert_allclose(result @ result.T, np.eye(64), atol=1e-6)
