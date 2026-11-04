"""Verify the frozen launch contract and exercise its actual offline checks."""

from contextlib import nullcontext
import importlib.util
import io
import json
import os
from pathlib import Path
import socket
import subprocess
import sys
import threading
from types import ModuleType, SimpleNamespace
import urllib.error

import pytest


ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location(
    "calclens_windows_launcher", ROOT / "packaging" / "windows" / "launcher.py"
)
launcher = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(launcher)


@pytest.fixture
def package(tmp_path):
    (tmp_path / "streamlit_app.py").write_text("# bundled app", encoding="utf-8")
    (tmp_path / ".streamlit").mkdir()
    (tmp_path / ".streamlit" / "config.toml").write_text(
        "[browser]\ngatherUsageStats = false\n", encoding="utf-8"
    )
    return tmp_path


def forbid_process(*args, **kwargs):
    pytest.fail("The frozen launcher must not start an external Python process")


def fake_streamlit(monkeypatch, callback):
    streamlit = ModuleType("streamlit")
    streamlit.__path__ = []
    web = ModuleType("streamlit.web")
    web.__path__ = []
    cli = ModuleType("streamlit.web.cli")
    cli.main = callback
    bootstrap = ModuleType("streamlit.web.bootstrap")
    bootstrap._on_server_start = lambda server: None
    web.cli = cli
    web.bootstrap = bootstrap
    streamlit.web = web
    for name, module in (("streamlit", streamlit), ("streamlit.web", web),
                         ("streamlit.web.cli", cli), ("streamlit.web.bootstrap", bootstrap)):
        monkeypatch.setitem(sys.modules, name, module)
    return bootstrap


def test_bundle_root_uses_extraction_directory_only_when_frozen(tmp_path, monkeypatch):
    monkeypatch.delattr(sys, "frozen", raising=False)
    assert launcher.bundle_root() == ROOT
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setattr(sys, "_MEIPASS", str(tmp_path), raising=False)
    assert launcher.bundle_root() == tmp_path.resolve()
    monkeypatch.delattr(sys, "_MEIPASS")
    with pytest.raises(launcher.LauncherError, match="extracted bundle"):
        launcher.bundle_root()


@pytest.mark.parametrize("marker,expected", [(None, "ko"), ("ko\n", "ko"), ("EN\n", "en")])
def test_source_language_uses_package_marker_or_korean_default(package, marker, expected):
    if marker is not None:
        (package / "DEFAULT_LANGUAGE.txt").write_text(marker, encoding="utf-8")
    assert launcher.package_language(package) == expected


def test_frozen_language_marker_is_required(package, monkeypatch):
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    with pytest.raises(launcher.LauncherError, match="DEFAULT_LANGUAGE.txt is missing"):
        launcher.package_language(package)


@pytest.mark.parametrize("marker,explicit,expected", [
    (None, None, "ko"), ("en", None, "en"), ("ko", "en", "en"),
    ("en", "ko", "ko"), ("invalid", "en", "en"),
])
def test_main_runs_cli_in_process_with_required_flags_and_locale(
    package, monkeypatch, marker, explicit, expected,
):
    if marker is not None:
        (package / "DEFAULT_LANGUAGE.txt").write_text(marker, encoding="utf-8")
    monkeypatch.setenv("CALCLENS_LANGUAGE", "existing-parent-value")
    monkeypatch.setenv("STREAMLIT_GLOBAL_DEVELOPMENT_MODE", "true")
    monkeypatch.setattr(sys, "executable", "CalcLens.exe")
    monkeypatch.setattr(subprocess, "Popen", forbid_process)
    monkeypatch.setattr(launcher, "choose_port", lambda requested: 43123)
    previous_cwd = Path.cwd()
    previous_argv = sys.argv
    calls = []

    def cli_main(**kwargs):
        assert os.environ["CALCLENS_LANGUAGE"] == expected
        assert os.environ["STREAMLIT_GLOBAL_DEVELOPMENT_MODE"] == "false"
        assert Path.cwd() == package
        assert (Path.cwd() / ".streamlit" / "config.toml").is_file()
        assert sys.argv == ["streamlit", *kwargs["args"]]
        calls.append(kwargs)
        return 7

    bootstrap = fake_streamlit(monkeypatch, cli_main)
    original_callback = bootstrap._on_server_start
    arguments = ["--no-browser"]
    if explicit:
        arguments.extend(["--language", explicit])
    assert launcher.main(arguments, project_dir=package) == 7
    assert len(calls) == 1
    command = calls[0]["args"]
    assert command[:2] == ["run", str(package / "streamlit_app.py")]
    assert {
        "--global.developmentMode=false", "--server.address=127.0.0.1",
        "--server.port=43123", "--server.fileWatcherType=none",
        "--server.headless=true", "--browser.gatherUsageStats=false",
    }.issubset(command)
    assert calls[0]["standalone_mode"] is False
    assert calls[0]["prog_name"] == "CalcLens"
    assert bootstrap._on_server_start is original_callback
    assert sys.argv is previous_argv
    assert Path.cwd() == previous_cwd
    assert os.environ["CALCLENS_LANGUAGE"] == "existing-parent-value"
    assert os.environ["STREAMLIT_GLOBAL_DEVELOPMENT_MODE"] == "true"


def test_run_cli_marks_own_server_ready_only_after_startup_callback(monkeypatch):
    ready = threading.Event()

    def cli_main(**kwargs):
        assert not ready.is_set()
        bootstrap._on_server_start(object())
        assert ready.is_set()

    bootstrap = fake_streamlit(monkeypatch, cli_main)
    assert launcher._run_streamlit(["streamlit", "run", "app.py"], ready) == 0


def test_streamlit_import_occurs_after_development_mode_is_disabled(package, monkeypatch):
    import builtins

    real_import = builtins.__import__
    observed = []

    def checked_import(name, *args, **kwargs):
        if name.startswith("streamlit"):
            observed.append(name)
            assert os.environ["STREAMLIT_GLOBAL_DEVELOPMENT_MODE"] == "false"
        return real_import(name, *args, **kwargs)

    fake_streamlit(monkeypatch, lambda **kwargs: 0)
    monkeypatch.setattr(builtins, "__import__", checked_import)
    monkeypatch.setenv("STREAMLIT_GLOBAL_DEVELOPMENT_MODE", "true")
    monkeypatch.setattr(launcher, "choose_port", lambda requested: 43123)
    assert launcher.main(["--no-browser"], project_dir=package) == 0
    assert observed


def test_free_port_selection_and_occupied_explicit_port():
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as occupied:
        occupied.bind((launcher.HOST, 0))
        occupied.listen(1)
        port = occupied.getsockname()[1]
        with pytest.raises(launcher.LauncherError, match=f"local port {port}"):
            launcher.choose_port(port)
        automatic = launcher.choose_port(None)
        assert 1 <= automatic <= 65535
        assert automatic != port


@pytest.mark.parametrize("port", ["0", "65536", "not-a-port"])
def test_invalid_port_never_imports_streamlit_or_opens_browser(package, monkeypatch, port):
    monkeypatch.setattr(launcher, "_run_streamlit", forbid_process)
    monkeypatch.setattr(launcher.webbrowser, "open", forbid_process)
    with pytest.raises(SystemExit) as error:
        launcher.main(["--port", port], project_dir=package)
    assert error.value.code == 2


def test_occupied_port_fails_without_starting_app(package, monkeypatch, capsys):
    monkeypatch.setattr(launcher, "_run_streamlit", forbid_process)
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as occupied:
        occupied.bind((launcher.HOST, 0))
        occupied.listen(1)
        port = occupied.getsockname()[1]
        assert launcher.main(["--port", str(port)], project_dir=package) == 1
    assert "Cannot use local port" in capsys.readouterr().err


def test_invalid_marker_and_missing_app_have_clear_errors(package, monkeypatch, capsys):
    monkeypatch.setattr(launcher, "_run_streamlit", forbid_process)
    (package / "DEFAULT_LANGUAGE.txt").write_text("invalid", encoding="utf-8")
    assert launcher.main([], project_dir=package) == 1
    assert "DEFAULT_LANGUAGE.txt must contain" in capsys.readouterr().err
    (package / "streamlit_app.py").unlink()
    assert launcher.main([], project_dir=package) == 1
    assert "streamlit_app.py is missing" in capsys.readouterr().err


@pytest.mark.parametrize("status,body,final_url,expected", [
    (200, b"ok", "http://127.0.0.1:43123/_stcore/health", True),
    (503, b"ok", "http://127.0.0.1:43123/_stcore/health", False),
    (200, b"<html>another server</html>", "http://127.0.0.1:43123/_stcore/health", False),
    (200, b"ok", "http://127.0.0.1:43124/_stcore/health", False),
])
def test_health_check_requires_exact_local_ready_response(
    monkeypatch, status, body, final_url, expected,
):
    response = SimpleNamespace(
        status=status, geturl=lambda: final_url, read=lambda count: body[:count],
    )
    requests = []

    def open_request(request, *, timeout):
        requests.append(request.full_url)
        assert timeout == 1.0
        return nullcontext(response)

    def build_opener(proxy, redirect):
        assert proxy.proxies == {}
        assert redirect.redirect_request(None, None, 302, "", {}, "https://example.invalid") is None
        return SimpleNamespace(open=open_request)

    monkeypatch.setattr(launcher.urllib.request, "build_opener", build_opener)
    assert launcher._health_is_ready("http://127.0.0.1:43123") is expected
    assert requests == ["http://127.0.0.1:43123/_stcore/health"]


def test_health_connection_errors_are_not_readiness(monkeypatch):
    def unavailable(*args, **kwargs):
        raise urllib.error.URLError("not listening yet")

    monkeypatch.setattr(launcher.urllib.request, "build_opener",
                        lambda *args: SimpleNamespace(open=unavailable))
    assert not launcher._health_is_ready("http://127.0.0.1:43123")


def test_browser_timeout_does_not_open_competing_server(monkeypatch):
    # Another process can return a perfect Streamlit health response on a port
    # won after our probe. Our own server startup is a separate prerequisite.
    monkeypatch.setattr(launcher, "_health_is_ready", lambda url: True)
    monkeypatch.setattr(launcher.webbrowser, "open", forbid_process)
    assert not launcher.open_browser_when_ready(
        "http://127.0.0.1:43123", threading.Event(), threading.Event(),
        timeout=0.01, poll_interval=0.001,
    )


def test_browser_opens_once_after_own_start_and_health_are_ready(monkeypatch):
    started = threading.Event()
    started.set()
    opened = []
    monkeypatch.setattr(launcher, "_health_is_ready", lambda url: True)
    monkeypatch.setattr(launcher.webbrowser, "open", lambda url: opened.append(url) or True)
    assert launcher.open_browser_when_ready(
        "http://127.0.0.1:43123", started, threading.Event(), timeout=0.01,
    )
    assert opened == ["http://127.0.0.1:43123"]


def test_browser_never_opens_after_shutdown_or_without_valid_health(monkeypatch):
    started = threading.Event()
    started.set()
    stopped = threading.Event()
    monkeypatch.setattr(launcher.webbrowser, "open", forbid_process)
    monkeypatch.setattr(launcher, "_health_is_ready", lambda url: False)
    assert not launcher.open_browser_when_ready(
        "http://127.0.0.1:43123", started, stopped, timeout=0.01, poll_interval=0.001,
    )
    stopped.set()
    monkeypatch.setattr(launcher, "_health_is_ready", lambda url: True)
    assert not launcher.open_browser_when_ready(
        "http://127.0.0.1:43123", started, stopped, timeout=0.01,
    )


def test_source_and_embedded_build_information_are_inspectable_offline(package, capsys):
    from slab_preflight import __version__

    assert launcher.main(["--build-info"], project_dir=package) == 0
    source = json.loads(capsys.readouterr().out)
    assert source["format"] == "calclens.source-checkout"
    assert source["version"] == __version__
    assert source["language"] == "ko"
    info = {
        "format": "calclens.windows-build", "version": __version__, "language": "en",
        "source_commit": "a" * 40, "architecture": "x86_64", "python_version": "3.12.12",
        "pyinstaller_version": "6.22.3", "build_mode": "onefile",
        "dependencies": {"streamlit": "1.66.1", "plotly": "6.9.0"},
    }
    (package / "DEFAULT_LANGUAGE.txt").write_text("en\n", encoding="utf-8")
    (package / "WINDOWS_BUILD_INFO.json").write_text(json.dumps(info), encoding="utf-8")
    assert launcher.main(["--build-info"], project_dir=package) == 0
    assert json.loads(capsys.readouterr().out) == info


@pytest.mark.parametrize("content", ["not-json", "[]", '{"version":"0.3.0"}'])
def test_damaged_build_metadata_is_reported(package, content, capsys):
    (package / "WINDOWS_BUILD_INFO.json").write_text(content, encoding="utf-8")
    assert launcher.main(["--build-info"], project_dir=package) == 1
    assert "WINDOWS_BUILD_INFO.json" in capsys.readouterr().err


def test_real_self_test_exercises_current_dependencies_without_network(monkeypatch, capsys):
    from slab_preflight import __version__

    monkeypatch.setattr(launcher, "choose_port", forbid_process)
    monkeypatch.setattr(launcher, "_run_streamlit", forbid_process)
    monkeypatch.setattr(launcher.webbrowser, "open", forbid_process)
    monkeypatch.setattr(launcher.urllib.request.OpenerDirector, "open", forbid_process)
    monkeypatch.setattr(socket, "create_connection", forbid_process)
    monkeypatch.setattr(subprocess, "Popen", forbid_process)
    assert launcher.main(["--self-test", "--language", "en"], project_dir=ROOT) == 0
    report = json.loads(capsys.readouterr().out)
    assert report["status"] == "ok"
    assert report["version"] == __version__
    assert report["language"] == "en"
    assert report["frozen"] is False
    assert report["executable"] == sys.executable
    assert report["chart_count"] == 2
    assert report["checks"] == {name: True for name in (
        "graphene_geometry", "mos2_axes", "invalid_cell_isolation", "project_roundtrip",
        "plotly_charts", "streamlit_static", "plotly_validators", "metadata",
    )}
    assert set(report["versions"]) == set(launcher.METADATA_PACKAGES)
    assert all(report["versions"].values())
    assert set(report["module_origins"]) == {"streamlit", "ase", "numpy", "plotly"}
    assert all(Path(origin).is_file() for origin in report["module_origins"].values())


def test_unexpected_launcher_defects_remain_visible(package, monkeypatch):
    def broken_runner(*args):
        raise TypeError("unexpected launcher defect")

    monkeypatch.setattr(launcher, "choose_port", lambda requested: 43123)
    monkeypatch.setattr(launcher, "_run_streamlit", broken_runner)
    with pytest.raises(TypeError, match="unexpected launcher defect"):
        launcher.main(["--no-browser"], project_dir=package)


def test_redirected_korean_console_and_errors_use_utf8_without_environment(
    package, monkeypatch,
):
    output_bytes, error_bytes = io.BytesIO(), io.BytesIO()
    output = io.TextIOWrapper(output_bytes, encoding="cp1252", errors="strict", write_through=True)
    errors = io.TextIOWrapper(error_bytes, encoding="cp1252", errors="strict", write_through=True)
    monkeypatch.delenv("PYTHONUTF8", raising=False)
    monkeypatch.delenv("PYTHONIOENCODING", raising=False)
    monkeypatch.setattr(launcher, "choose_port", lambda requested: 43123)
    monkeypatch.setattr(launcher, "_run_streamlit", lambda *args: 0)
    with monkeypatch.context() as capture:
        capture.setattr(sys, "stdout", output)
        capture.setattr(sys, "stderr", errors)
        assert launcher.main(["--no-browser", "--language", "ko"], project_dir=package) == 0
        assert launcher.main(["--language", "ko"], project_dir=package / "missing") == 1
        assert output.encoding == errors.encoding == "utf-8"
        assert output.errors == errors.errors == "backslashreplace"
    assert "사용하는 동안 이 창을 열어 두세요" in output_bytes.getvalue().decode("utf-8")
    assert "CalcLens를 시작할 수 없습니다" in error_bytes.getvalue().decode("utf-8")
