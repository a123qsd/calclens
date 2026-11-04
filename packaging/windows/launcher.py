"""Run the bundled CalcLens app without an external Python installation."""

from __future__ import annotations

import argparse
from contextlib import contextmanager
import importlib.metadata
import json
import math
import multiprocessing
import os
from pathlib import Path
import platform
import socket
import sys
import threading
import time
import urllib.error
import urllib.request
import webbrowser


HOST = "127.0.0.1"
METADATA_PACKAGES = ("ase", "numpy", "plotly", "streamlit", "starlette", "uvicorn")


class LauncherError(ValueError):
    """A missing or damaged bundle prevents a supported launch."""


def bundle_root() -> Path:
    """Use PyInstaller's extracted resources, or the complete source checkout."""
    if getattr(sys, "frozen", False):
        extracted = getattr(sys, "_MEIPASS", None)
        if not extracted:
            raise LauncherError("The executable is missing its extracted bundle directory.")
        return Path(extracted).resolve()
    return Path(__file__).resolve().parents[2]


def package_language(root: Path) -> str:
    marker = root / "DEFAULT_LANGUAGE.txt"
    if not marker.exists():
        if getattr(sys, "frozen", False):
            raise LauncherError("DEFAULT_LANGUAGE.txt is missing from the executable.")
        return "ko"
    try:
        language = marker.read_text(encoding="utf-8").strip().lower()
    except (OSError, UnicodeError) as error:
        raise LauncherError(f"Cannot read DEFAULT_LANGUAGE.txt: {error}") from error
    if language not in ("ko", "en"):
        raise LauncherError("DEFAULT_LANGUAGE.txt must contain exactly 'ko' or 'en'.")
    return language


def _port(value: str) -> int:
    try:
        number = int(value)
    except ValueError:
        raise argparse.ArgumentTypeError("Port must be an integer from 1 to 65535.") from None
    if not 1 <= number <= 65535:
        raise argparse.ArgumentTypeError("Port must be an integer from 1 to 65535.")
    return number


def choose_port(requested: int | None) -> int:
    """Reject occupied explicit ports and choose a free loopback port by default.

    Streamlit receives an explicit port, so a bind race fails instead of silently
    serving on a different port. Its startup callback also gates browser opening.
    """
    if requested is not None and (type(requested) is not int or not 1 <= requested <= 65535):
        raise LauncherError("Port must be an integer from 1 to 65535.")
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
            if os.name == "nt":
                probe.setsockopt(socket.SOL_SOCKET, socket.SO_EXCLUSIVEADDRUSE, 1)
            probe.bind((HOST, requested or 0))
            return int(probe.getsockname()[1])
    except OSError as error:
        label = str(requested) if requested is not None else "an automatic port"
        raise LauncherError(f"Cannot use local port {label}: {error}") from error


def streamlit_arguments(root: Path, port: int) -> list[str]:
    return [
        "streamlit", "run", str(root / "streamlit_app.py"),
        "--global.developmentMode=false",
        f"--server.address={HOST}", f"--server.port={port}",
        "--server.fileWatcherType=none", "--server.headless=true",
        "--browser.gatherUsageStats=false",
    ]


@contextmanager
def _runtime_environment(root: Path, language: str):
    values = {
        "CALCLENS_LANGUAGE": language,
        # Set this before the first Streamlit import. Extracted PyInstaller paths
        # otherwise trigger Streamlit's source-tree development-mode heuristic.
        "STREAMLIT_GLOBAL_DEVELOPMENT_MODE": "false",
    }
    previous = {key: os.environ.get(key) for key in values}
    previous_cwd = Path.cwd()
    os.environ.update(values)
    try:
        os.chdir(root)  # Read the bundled .streamlit/config.toml, not the user's cwd.
        yield
    finally:
        os.chdir(previous_cwd)
        for key, value in previous.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, request, response, code, message, headers, newurl):
        return None


def _health_is_ready(url: str) -> bool:
    health_url = f"{url}/_stcore/health"
    # Local health checks must not use an inherited corporate HTTP proxy or
    # follow another server's redirect away from this exact loopback endpoint.
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}), _NoRedirect())
    request = urllib.request.Request(health_url, headers={"Cache-Control": "no-cache"})
    try:
        with opener.open(request, timeout=1.0) as response:
            return (response.status == 200 and response.geturl() == health_url
                    and response.read(32).strip() == b"ok")
    except (urllib.error.URLError, OSError, TimeoutError):
        return False


def open_browser_when_ready(
    url: str, started: threading.Event, stopped: threading.Event,
    *, timeout: float = 45.0, poll_interval: float = 0.2,
) -> bool:
    """Open only after our own server has bound and its health response is ready."""
    deadline = time.monotonic() + timeout
    while not stopped.is_set() and time.monotonic() < deadline:
        # A different process can win the port after choose_port's probe closes.
        # In that case our startup callback never fires, even if its health is ok.
        if started.is_set() and _health_is_ready(url) and not stopped.is_set():
            return bool(webbrowser.open(url))
        stopped.wait(min(poll_interval, max(0.0, deadline - time.monotonic())))
    return False


def _run_streamlit(arguments: list[str], started: threading.Event) -> int:
    # This must remain in-process: sys.executable is the app EXE when frozen,
    # so launching it with "-m streamlit" would recursively start this launcher.
    from streamlit.web import bootstrap, cli

    original_callback = bootstrap._on_server_start
    original_argv = sys.argv

    def on_server_start(server):
        original_callback(server)
        started.set()

    bootstrap._on_server_start = on_server_start
    sys.argv = arguments
    try:
        result = cli.main(args=arguments[1:], prog_name="CalcLens", standalone_mode=False)
        return int(result or 0)
    except SystemExit as error:
        if isinstance(error.code, int):
            return error.code
        if error.code:
            print(error.code, file=sys.stderr)
            return 1
        return 0
    finally:
        bootstrap._on_server_start = original_callback
        sys.argv = original_argv


def read_build_info(root: Path, language: str) -> dict:
    from slab_preflight import __version__

    path = root / "WINDOWS_BUILD_INFO.json"
    if not path.exists():
        if getattr(sys, "frozen", False):
            raise LauncherError("WINDOWS_BUILD_INFO.json is missing from the executable.")
        return {
            "format": "calclens.source-checkout", "version": __version__,
            "language": language, "architecture": platform.machine(),
            "python_version": platform.python_version(), "build_mode": "source",
        }
    try:
        info = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, ValueError) as error:
        raise LauncherError(f"Cannot read WINDOWS_BUILD_INFO.json: {error}") from error
    if (not isinstance(info, dict) or not isinstance(info.get("version"), str)
            or info.get("language") not in ("ko", "en")):
        raise LauncherError("WINDOWS_BUILD_INFO.json must contain a version and language.")
    return info


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise LauncherError(f"Self-test failed: {message}")


def self_test(root: Path, language: str) -> dict:
    """Exercise bundled computation and resources offline, without starting a server."""
    import ase
    import numpy
    import plotly
    import streamlit

    from slab_preflight import __version__, analyze_cif
    from slab_preflight.batch import BatchInput, analyze_batch
    from slab_preflight.plotting import profile_figure, structure_figure
    from slab_preflight.project import Project, ProjectEntry, dumps_project, loads_project

    def close(actual, expected):
        return math.isclose(actual, expected, rel_tol=0.0, abs_tol=1e-8)

    graphene_bytes = (root / "examples" / "graphene.cif").read_bytes()
    graphene = analyze_cif(graphene_bytes)
    _require(graphene["atom_count"] == 2, "graphene must contain two sites")
    _require(close(graphene["metrics"]["minimum_distance_angstrom"], 2.46 / math.sqrt(3)),
             "graphene periodic minimum distance")
    _require(close(graphene["metrics"]["nuclei_gap_angstrom"], 20.0), "graphene nuclear gap")

    axis_reports = {}
    for axis, filename in (("a", "mos2_a_normal.cif"), ("b", "mos2_b_normal.cif"),
                           ("c", "mos2.cif")):
        report = analyze_cif((root / "examples" / filename).read_bytes(), normal_axis=axis)
        metrics = report["metrics"]
        _require(report["atom_count"] == 3 and report["normal_axis"] == axis,
                 f"MoS2 {axis}-normal site count and axis")
        for field, expected in (
            ("minimum_distance_angstrom", math.sqrt(3.18**2 / 3 + 1.56**2)),
            ("normal_height_angstrom", 20.0), ("nuclei_thickness_angstrom", 3.12),
            ("nuclei_gap_angstrom", 16.88),
        ):
            _require(close(metrics[field], expected), f"MoS2 {axis}-normal {field}")
        axis_reports[axis] = report

    invalid = graphene_bytes.replace(
        b"_cell_angle_alpha 90", b"_cell_angle_alpha 90.000001"
    ).replace(b"_cell_angle_gamma 120", b"_cell_angle_gamma 0.00000001")
    _require(invalid != graphene_bytes, "invalid-cell fixture must change the original")
    batch = analyze_batch([
        BatchInput("invalid.cif", invalid), BatchInput("graphene.cif", graphene_bytes),
    ])
    _require(batch[0]["report"] is None and "valid three-dimensional cell" in
             (batch[0]["error"] or ""), "invalid cell must fail independently")
    _require(batch[1]["error"] is None and batch[1]["report"]["atom_count"] == 2,
             "a valid file must survive an invalid batch entry")

    project = Project(entries=[
        ProjectEntry("graphene", "graphene.cif", graphene_bytes,
                     note="Bundled review / 번들 검토\nOriginal bytes preserved.", reviewed=True),
        ProjectEntry("mos2-b", "mos2_b_normal.cif",
                     (root / "examples" / "mos2_b_normal.cif").read_bytes(),
                     normal_axis="b", short_distance=1.25, note="Axis b / b축"),
    ], selected_id="mos2-b", review_focus="gap", filter_mode="needs_review")
    restored = loads_project(dumps_project(project))
    _require(restored == project, "project originals, notes, and review state must round-trip")

    charts = [structure_figure(axis_reports["b"], korean=language == "ko", highlight_gap=True),
              profile_figure(axis_reports["b"], korean=language == "ko")]
    chart_json = [json.loads(figure.to_json()) for figure in charts]
    _require(all(document.get("data") and document.get("layout") for document in chart_json),
             "both Plotly charts must serialize with traces and layout")
    _require(any(trace.get("type") == "scatter3d" for trace in chart_json[0]["data"]),
             "the structure chart must contain a 3D trace")
    _require(any(trace.get("type") == "scatter" for trace in chart_json[1]["data"]),
             "the profile chart must contain a profile trace")

    static_index = Path(streamlit.__file__).resolve().parent / "static" / "index.html"
    validators = Path(plotly.__file__).resolve().parent / "validators" / "_validators.json"
    _require(static_index.is_file() and static_index.stat().st_size > 0,
             "Streamlit's static/index.html must be bundled")
    _require(validators.is_file(), "Plotly's validators/_validators.json must be bundled")
    _require(bool(json.loads(validators.read_text(encoding="utf-8"))),
             "Plotly's validator data must contain valid JSON")

    versions = {name: importlib.metadata.version(name) for name in METADATA_PACKAGES}
    info = read_build_info(root, language)
    _require(info["version"] == __version__, "build metadata version must match the engine")
    if (root / "DEFAULT_LANGUAGE.txt").exists():
        _require(info["language"] == package_language(root),
                 "build metadata language must match the embedded default")
    expected_dependencies = info.get("dependencies", {})
    _require(isinstance(expected_dependencies, dict), "build dependency metadata must be an object")
    for name, actual in versions.items():
        if name in expected_dependencies:
            _require(expected_dependencies[name] == actual, f"{name} metadata version mismatch")

    modules = {"streamlit": streamlit, "ase": ase, "numpy": numpy, "plotly": plotly}
    origins = {name: str(Path(module.__file__).resolve()) for name, module in modules.items()}
    frozen = bool(getattr(sys, "frozen", False))
    if frozen:
        _require(all(Path(origin).is_relative_to(root) for origin in origins.values()),
                 "runtime modules must load from inside the extracted executable")
    return {
        "status": "ok", "version": __version__, "language": language, "frozen": frozen,
        "executable": sys.executable, "meipass": getattr(sys, "_MEIPASS", None),
        "platform": sys.platform, "bundle_root": str(root), "build_info": info,
        "versions": versions, "module_origins": origins,
        "checks": {name: True for name in (
            "graphene_geometry", "mos2_axes", "invalid_cell_isolation", "project_roundtrip",
            "plotly_charts", "streamlit_static", "plotly_validators", "metadata",
        )},
        "chart_count": len(charts),
    }


def _console_directions(url: str, language: str) -> None:
    if os.name == "nt":
        import ctypes

        ctypes.windll.kernel32.SetConsoleTitleW(
            "CalcLens · 한국어" if language == "ko" else "CalcLens · English"
        )
    if language == "ko":
        print(f"CalcLens를 시작합니다. 브라우저 주소: {url}\n"
              "사용하는 동안 이 창을 열어 두세요. 창을 닫거나 Ctrl+C를 누르면 종료됩니다.",
              flush=True)
    else:
        print(f"Starting CalcLens. Browser address: {url}\n"
              "Keep this window open while using the app. Close it or press Ctrl+C to stop.",
              flush=True)


def _configure_text_streams() -> None:
    # Windows redirects otherwise inherit an ANSI encoding such as cp1252.
    # The isolated executable cannot rely on the build runner's PYTHONUTF8.
    for stream in (sys.stdout, sys.stderr):
        reconfigure = getattr(stream, "reconfigure", None)
        if callable(reconfigure):
            try:
                reconfigure(encoding="utf-8", errors="backslashreplace")
            except (OSError, ValueError):
                # An embedding host may supply a closed or read-only capture.
                pass


def main(argv: list[str] | None = None, *, project_dir: Path | None = None) -> int:
    _configure_text_streams()
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--language", choices=("ko", "en"), help="Override the bundled language.")
    parser.add_argument("--port", type=_port, help="Local TCP port (default: choose a free port).")
    parser.add_argument("--no-browser", action="store_true", help="Do not open the browser.")
    inspection = parser.add_mutually_exclusive_group()
    inspection.add_argument("--self-test", action="store_true", help="Run offline bundle checks.")
    inspection.add_argument("--build-info", action="store_true", help="Print build metadata as JSON.")
    args = parser.parse_args(argv)
    stopped = threading.Event()
    language = args.language or "en"
    try:
        root = project_dir.resolve() if project_dir is not None else bundle_root()
        if not (root / "streamlit_app.py").is_file():
            raise LauncherError("streamlit_app.py is missing from the CalcLens bundle.")
        language = args.language or package_language(root)
        # A source invocation is useful for verifying the same launcher before a
        # Windows build. Frozen imports are supplied exclusively by PyInstaller.
        if not getattr(sys, "frozen", False) and (root / "src").is_dir():
            source = str(root / "src")
            if source not in sys.path:
                sys.path.insert(0, source)
        with _runtime_environment(root, language):
            if args.build_info:
                print(json.dumps(read_build_info(root, language), sort_keys=True))
                return 0
            if args.self_test:
                print(json.dumps(self_test(root, language), sort_keys=True))
                return 0
            port = choose_port(args.port)
            url = f"http://{HOST}:{port}"
            _console_directions(url, language)
            started = threading.Event()
            if not args.no_browser:
                threading.Thread(
                    target=open_browser_when_ready, args=(url, started, stopped),
                    name="CalcLens-browser", daemon=True,
                ).start()
            return _run_streamlit(streamlit_arguments(root, port), started)
    except KeyboardInterrupt:
        return 130
    except (OSError, ImportError, ValueError) as error:
        prefix = "CalcLens를 시작할 수 없습니다" if language == "ko" else "CalcLens could not start"
        print(f"{prefix}: {error}", file=sys.stderr)
        return 1
    finally:
        stopped.set()


if __name__ == "__main__":
    multiprocessing.freeze_support()
    raise SystemExit(main())
