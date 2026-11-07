"""Startup readiness, diagnostics before Qt, and deferred workspace behavior."""
import importlib.util
import json
from pathlib import Path
import subprocess
import sys

import pytest

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture
def startup():
    spec = importlib.util.spec_from_file_location("isolated_startup", ROOT / "src/slab_preflight/startup.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_importing_package_and_startup_does_not_require_scientific_or_qt_packages():
    program = """
import importlib.abc
import sys
class Block(importlib.abc.MetaPathFinder):
    def find_spec(self, fullname, path=None, target=None):
        if fullname.split('.')[0] in ('ase', 'numpy', 'PySide6'):
            raise RuntimeError('Premature heavy import: ' + fullname)
sys.meta_path.insert(0, Block())
import slab_preflight
from slab_preflight import startup
assert slab_preflight.__version__ == '0.9.0'
assert startup.trace_record()['ready'] is False
"""
    subprocess.run([sys.executable, "-c", program], check=True, cwd=ROOT)


def test_loading_indicator_and_first_window_are_not_ready(startup, tmp_path):
    trace = tmp_path / "startup.json"
    startup.configure(trace, benchmark=True)
    startup.mark("first_window")
    assert not json.loads(trace.read_text())["ready"]
    startup.mark("default_analysis_complete")
    assert not startup.trace_record()["ready"]
    startup.mark("first_input_response")
    record = json.loads(trace.read_text())
    assert record["ready"] and startup.benchmark_requested()
    original = record["milestones_ms"]["first_window"]
    startup.mark("first_window")
    assert startup.trace_record()["milestones_ms"]["first_window"] == original


def test_parent_timing_and_unpack_are_separate_phases(startup, tmp_path, monkeypatch):
    monkeypatch.setenv("CALCLENS_STARTUP_PARENT_NS", "1000000000")
    monkeypatch.setenv("CALCLENS_RUNTIME_UNPACK_MS", "42")
    monkeypatch.setattr(startup.time, "perf_counter_ns", lambda: 1_500_000_000)
    startup.configure(tmp_path / "trace.json", started_ns=1_200_000_000)
    record = startup.trace_record()
    assert record["parent_to_python_ms"] == 200
    assert record["runtime_unpack_ms"] == 42
    assert record["milestones_ms"]["python_entry"] == 300
    assert record["launch_to_ms"]["python_entry"] == 500


def test_safe_failure_log_never_stores_exception_values_or_remote_token(tmp_path):
    program = """
from pathlib import Path
import sys
from slab_preflight import startup
startup.diagnostic_directory = lambda: Path(sys.argv[1])
notices = []
startup.show_failure = lambda error, **kwargs: notices.append(type(error).__name__)
def fail():
    raise RuntimeError('remote_token=top-secret-token; private project contents')
assert startup.guarded_main(fail) == 1
assert notices == ['RuntimeError']
assert 'PySide6' not in sys.modules
text = next(Path(sys.argv[1]).glob('*.log')).read_text()
assert 'RuntimeError' in text and 'fail' in text
assert 'top-secret-token' not in text and 'private project contents' not in text
"""
    subprocess.run([sys.executable, "-c", program, str(tmp_path)], check=True, cwd=ROOT)


def test_deferred_workspace_has_no_default_result_until_background_initialization():
    from slab_preflight.web_api import Workspace

    workspace = Workspace(ROOT, "en", load_default=False)
    assert workspace.project.entries == [] and workspace.cache == {}
    assert workspace.snapshot(include_workspace=True)["entries"] == []
    snapshot = workspace.load_initial_example()
    assert snapshot["entries"][0]["analysis"]["report"]["formula"] == "C2"
    assert snapshot["entries"][0]["filename"] == "graphene.cif"
    before = workspace.project
    workspace.load_initial_example()
    assert workspace.project is before


def test_deferred_initialization_does_not_overwrite_a_new_workspace():
    from slab_preflight.project import Project
    from slab_preflight.web_api import Workspace

    workspace = Workspace(ROOT, "en", load_default=False)
    workspace.project = Project([])
    workspace.revision = 1
    workspace.load_initial_example()
    assert workspace.project.entries == []


def test_source_entrypoint_forwards_native_timing_flags(tmp_path, monkeypatch):
    from slab_preflight import desktop_entry

    spec = importlib.util.spec_from_file_location("source_launcher_timing", ROOT / "run_app.py")
    launcher = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(launcher)
    calls = []
    monkeypatch.setattr(desktop_entry, "main", lambda args, **kwargs: calls.append((args, kwargs)) or 0)
    trace = tmp_path / "startup.json"
    assert launcher.main(["--startup-benchmark", str(trace)], project_dir=tmp_path) == 0
    assert calls == [(["--startup-benchmark", str(trace)], {"root": tmp_path})]


def test_desktop_import_defers_ase_io_until_analysis_starts():
    pytest.importorskip("PySide6")
    program = """
import sys
import slab_preflight.desktop
assert 'ase.io' not in sys.modules
assert 'scipy.integrate' not in sys.modules
from pathlib import Path
from slab_preflight.core import analyze_cif
report = analyze_cif(Path('examples/graphene.cif').read_bytes())
assert report['atom_count'] == 2
assert 'ase.io.cif' in sys.modules
"""
    subprocess.run([sys.executable, "-c", program], check=True, cwd=ROOT)
