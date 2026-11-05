"""Verify workspace-only and explicit legacy bundle boundaries without building an EXE."""

import importlib.util
import json
import os
from pathlib import Path
import platform
import subprocess
import sys
from types import ModuleType, SimpleNamespace

import pytest


ROOT = Path(__file__).resolve().parents[1]


def load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


builder = load("calclens_windows_builder", ROOT / "scripts" / "build_windows.py")
licenses = load("calclens_windows_notices", ROOT / "scripts" / "collect_windows_licenses.py")


@pytest.mark.parametrize("legacy", [False, True])
def test_spec_collects_only_the_selected_ui_variant(tmp_path, monkeypatch, legacy):
    hooks = ModuleType("PyInstaller.utils.hooks")
    collected = []

    def collect_submodules(name, filter=lambda name: True):
        collected.append(name)
        names = ["slab_preflight.core", "slab_preflight.web_api", "slab_preflight.plotting"] \
            if name == "slab_preflight" else [name]
        return [item for item in names if filter(item)]

    hooks.collect_submodules = collect_submodules
    hooks.collect_data_files = lambda name: []
    hooks.copy_metadata = lambda name, **kwargs: []
    for name in ("PyInstaller", "PyInstaller.utils"):
        module = ModuleType(name)
        module.__path__ = []
        monkeypatch.setitem(sys.modules, name, module)
    monkeypatch.setitem(sys.modules, "PyInstaller.utils.hooks", hooks)
    monkeypatch.setenv("CALCLENS_BUILD_STAGE", str(tmp_path / "stage"))
    monkeypatch.setenv("CALCLENS_BUILD_NOTICES", str(tmp_path))
    monkeypatch.setenv("CALCLENS_BUILD_MODE", "onefile")
    monkeypatch.setenv("CALCLENS_BUILD_NAME", "fixture")
    monkeypatch.setenv("CALCLENS_BUILD_INCLUDE_LEGACY_UI", "1" if legacy else "0")
    analyses = []

    def analysis(*args, **kwargs):
        analyses.append(kwargs)
        return SimpleNamespace(pure=[], scripts=[], binaries=[], datas=[])

    scope = {"SPECPATH": str(ROOT / "packaging" / "windows"), "Analysis": analysis,
             "PYZ": lambda *args, **kwargs: None, "EXE": lambda *args, **kwargs: None}
    spec_path = ROOT / "packaging" / "windows" / "CalcLens.spec"
    exec(compile(spec_path.read_text(), str(spec_path), "exec"), scope)
    result = analyses[0]
    assert ("slab_preflight.plotting" in result["hiddenimports"]) is legacy
    assert ("streamlit" in collected) is legacy
    assert ("plotly" in collected) is legacy
    assert (str(ROOT / "streamlit_app.py"), ".") in result["datas"] if legacy else \
        (str(ROOT / "streamlit_app.py"), ".") not in result["datas"]
    if not legacy:
        assert {"streamlit", "plotly", "slab_preflight.plotting"} <= set(result["excludes"])


def test_runtime_notice_roots_exclude_ambient_legacy_packages(monkeypatch):
    dependencies = {"ase": ["numpy>=2"], "numpy": [], "streamlit": ["altair>=5"],
                    "plotly": ["narwhals>=1"], "altair": [], "narwhals": []}
    monkeypatch.setattr(licenses.metadata, "distribution", lambda name:
                        SimpleNamespace(requires=dependencies[name], version="6.0"))
    assert licenses.runtime_closure({}) == ["ase", "numpy"]
    assert licenses.runtime_closure({}, include_legacy_ui=True) == \
        ["altair", "ase", "narwhals", "numpy", "plotly", "streamlit"]


def test_build_and_notice_metadata_distinguish_bundle_variants(monkeypatch):
    monkeypatch.setattr(builder.importlib.metadata, "version", lambda name: "1.0")
    info = builder.build_info("en", "onefile", "a" * 40)
    legacy = builder.build_info("en", "onefile", "a" * 40, include_legacy_ui=True)
    assert info["includes_legacy_ui"] is False and info["app_sha256"] is None
    assert set(info["dependencies"]) == {"ase", "numpy"}
    assert legacy["includes_legacy_ui"] is True and legacy["app_sha256"]
    assert {"plotly", "streamlit"} <= legacy["dependencies"].keys()
    assert builder.bundle_name("0.6.0", "en") == "CalcLens-0.6.0-windows-x64-en"
    assert builder.bundle_name("0.6.0", "en", include_legacy_ui=True).endswith("-en-legacy")
    manifest = {"source_commit": "a" * 40, "version": info["version"], "includes_legacy_ui": False,
                "python": {"version": platform.python_version()},
                "runtime_dependencies": [], "build_tools": []}
    builder.validate_notices(manifest, info, "a" * 40)
    with pytest.raises(ValueError, match="different UI variant"):
        builder.validate_notices(manifest, legacy, "a" * 40)


def test_workspace_server_and_default_self_test_run_with_legacy_imports_blocked():
    script = r'''
import importlib.abc
import importlib.util
import json
from pathlib import Path
import sys
import threading
import urllib.request

class NoLegacy(importlib.abc.MetaPathFinder):
    def find_spec(self, fullname, path=None, target=None):
        if fullname.split('.')[0] in ('streamlit', 'plotly') or fullname == 'slab_preflight.plotting':
            raise ModuleNotFoundError('legacy import blocked: ' + fullname)
sys.meta_path.insert(0, NoLegacy())
root = Path.cwd()
spec = importlib.util.spec_from_file_location('launcher', root / 'packaging/windows/launcher.py')
launcher = importlib.util.module_from_spec(spec)
spec.loader.exec_module(launcher)
result = launcher.self_test(root, 'en')
assert result['includes_legacy_ui'] is False and result['chart_count'] == 0
assert set(result['versions']) == {'ase', 'numpy'}
from slab_preflight.web_api import create_server
server = create_server(root, 0, 'en')
thread = threading.Thread(target=server.serve_forever, daemon=True)
thread.start()
try:
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    with opener.open(f'http://127.0.0.1:{server.server_port}/_calclens/health', timeout=5) as response:
        assert response.status == 200 and response.read().strip() == b'ok'
finally:
    server.shutdown()
    server.server_close()
    thread.join(timeout=5)
assert not any(name.split('.')[0] in ('streamlit', 'plotly') or name == 'slab_preflight.plotting'
               for name in sys.modules)
print(json.dumps({'self_test': result['status'], 'workspace_health': 'ok', 'legacy_imports': 0}))
'''
    environment = os.environ.copy()
    environment["PYTHONPATH"] = str(ROOT / "src")
    result = subprocess.run([sys.executable, "-c", script], cwd=ROOT, env=environment,
                            capture_output=True, text=True, timeout=30, check=False)
    assert result.returncode == 0, result.stderr
    assert json.loads(result.stdout) == {
        "self_test": "ok", "workspace_health": "ok", "legacy_imports": 0,
    }
