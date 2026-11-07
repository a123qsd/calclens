"""Timing evidence must distinguish compatibility runs and actual readiness."""
import importlib.util
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location("desktop_benchmark", ROOT / "scripts/benchmark_desktop_startup.py")
BENCH = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(BENCH)


def test_mac_process_cannot_be_reported_as_windows_performance(tmp_path, monkeypatch):
    monkeypatch.setattr(BENCH.sys, "platform", "darwin")
    with pytest.raises(ValueError, match="Run this on Windows"):
        BENCH.measure(tmp_path / "app.exe", tmp_path / "evidence")


def test_wine_is_labelled_and_a_loading_window_never_counts_as_passed(tmp_path, monkeypatch):
    exe = tmp_path / "app.exe"
    exe.write_bytes(b"synthetic executable")
    output = tmp_path / "measurements"
    runner = tmp_path / "wine"

    def run(command, **options):
        assert command[0] == str(runner)
        assert "CALCLENS_STARTUP_PARENT_NS" not in options["env"]
        (output / "run-1.json").write_text(json.dumps({
            "ready": False, "milestones_ms": {"first_window": 5.0},
        }))
        return SimpleNamespace(returncode=0)

    monkeypatch.setattr(BENCH.subprocess, "run", run)
    monkeypatch.setattr(BENCH.platform, "platform", lambda: "test host")
    record = BENCH.measure(exe, output, runner=runner, runs=3)
    assert record["status"] == "failed"
    assert not record["windows_performance_measured"]
    assert record["environment"].startswith("Wine on ")
    assert not record["first_is_cold_boot"]


def test_reusing_old_trace_is_rejected_before_execution(tmp_path, monkeypatch):
    output = tmp_path / "measurements"
    output.mkdir()
    (output / "run-1.json").write_text('{"ready": true}')
    monkeypatch.setattr(BENCH.subprocess, "run", lambda *args, **kwargs: pytest.fail("Stale evidence must not be reused"))
    with pytest.raises(ValueError, match="old timing result"):
        BENCH.measure(tmp_path / "app.exe", output, runner=Path("/wine"))
