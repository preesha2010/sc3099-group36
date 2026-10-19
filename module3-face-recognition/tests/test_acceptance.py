from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from acceptance import accumulate, memory_summary
import support
import pytest
import release_check
from evaluate import latency_gate
from types import SimpleNamespace


@pytest.mark.parametrize("changes", [{"successful": 99}, {"successful_within_target": 99},
                                    {"health_failures": 1}, {"maximum_seconds": 5.01}])
def test_throughput_gate_does_not_hide_rejections_or_tail_timeouts(changes):
    row = {"clients": 100, "successful": 100, "successful_within_target": 100,
           "health_failures": 0, "maximum_seconds": 4.9}
    assert latency_gate({"/face/verify": [row]})
    assert not latency_gate({"/face/verify": [row, {**row, **changes}]})


def test_empty_throughput_observations_cannot_pass():
    assert not latency_gate({})
    assert not latency_gate({"/face/verify": []})


def test_compact_soak_summary_counts_every_request_not_only_sampled_waves():
    result = {}
    row = {"clients": 4, "successful_200": 4, "health_failures": 0,
           "maximum_seconds": .4, "p95_all_seconds": .3, "status_counts": {"200": 4}}
    accumulate(result, row)
    accumulate(result, {**row, "successful_200": 2, "maximum_seconds": .8, "status_counts": {"200": 2, "503": 2}})
    assert result["waves"] == 2
    assert result["requests"] == 8
    assert result["successful_200"] == 6
    assert result["status_counts"] == {"200": 6, "503": 2}
    assert result["maximum_seconds"] == .8


def test_windowed_rss_check_is_not_fooled_by_a_single_final_dip():
    mib = 1024 ** 2
    values = [100] * 10 + [300] * 29 + [100]
    summary = memory_summary([{"rss_bytes": value * mib} for value in values], 128)
    assert summary["end_minus_initial_mib"] == 0
    assert summary["window_growth_mib"] == 180
    assert summary["growth_within_budget"] is False
    assert memory_summary([{"rss_bytes": None}], 128) == {"available": False}


def test_failed_checkpoint_replace_preserves_previous_report(tmp_path, monkeypatch):
    target = tmp_path / "checkpoint.json"
    target.write_text('{"state":"previous-valid-checkpoint"}')

    def fail(*_):
        raise OSError("simulated replacement failure")

    monkeypatch.setattr(support.os, "replace", fail)
    with pytest.raises(OSError):
        support.save_report(target, {"state": "new"})
    assert target.read_text() == '{"state":"previous-valid-checkpoint"}'
    assert list(tmp_path.glob("*.tmp")) == []


@pytest.mark.parametrize("statuses,expected,calls", [([0, 2], 2, 2), ([1], 1, 1), ([0, 0], 0, 2)])
def test_release_wrapper_preserves_failed_gate_and_stops(statuses, expected, calls, monkeypatch):
    pending = iter(statuses)
    commands = []

    def run(command, **_):
        commands.append(command)
        return SimpleNamespace(returncode=next(pending))

    monkeypatch.setattr(release_check.subprocess, "run", run)
    assert release_check.main([]) == expected
    assert len(commands) == calls
