"""Native executable entry point shared by the Windows and macOS distributions."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import platform
import sys

from . import startup


def resource_root() -> Path:
    here = Path(__file__).resolve()
    candidates = [
        Path(getattr(sys, "_MEIPASS", here.parent)),
        here.parents[2],
        here.parent / "_resources",
    ]
    for candidate in candidates:
        if (candidate / "examples/graphene.cif").is_file():
            return candidate
    raise FileNotFoundError("CalcLens could not locate its bundled structure examples.")


def smoke(path: Path, root: Path, language: str) -> int:
    """Exercise a real Qt event loop and render using the packaged runtime."""
    from PySide6.QtCore import QTimer, qVersion
    from PySide6.QtWidgets import QApplication, QMainWindow
    from . import __version__
    from .desktop import MainWindow
    from .core import analyze_cif, UnsupportedStructure
    from .project import loads_project

    path = path.resolve()
    path.parent.mkdir(parents=True, exist_ok=True)
    record = {
        "status": "failed",
        "version": __version__,
        "platform": sys.platform,
        "architecture": platform.machine(),
        "qt": qVersion(),
        "language": language,
    }
    try:
        # A display failure or an accidental browser/server fallback must fail this smoke test.
        import socket
        import webbrowser
        from unittest.mock import patch

        def forbid(*args, **kwargs):
            raise AssertionError(
                "Native startup attempted to open a browser or listen on a socket."
            )

        with (
            patch.object(socket.socket, "bind", forbid),
            patch.object(socket.socket, "listen", forbid),
            patch.object(webbrowser, "open", forbid),
        ):
            app = QApplication.instance() or QApplication(["CalcLens"])
            window = MainWindow(language, root=root, recovery=False)
            window.show()

            def inspect():
                try:
                    entry = window.selected_entry
                    assert isinstance(window, QMainWindow) and window.isVisible()
                    report = entry["analysis"]["report"]
                    assert report["atom_count"] == 2
                    try:
                        analyze_cif(
                            (root / "examples/partial_occupancy.cif")
                            .read_text()
                            .replace("_atom_site_occupancy", "_atom_site.occupancy")
                        )
                    except UnsupportedStructure:
                        pass
                    else:
                        raise AssertionError("Partial occupancy passed.")
                    png = path.with_suffix(".png")
                    assert window.grab().save(str(png), "PNG") and png.stat().st_size > 2000
                    if window.research_panel is None:
                        raise AssertionError("The native research controls are missing.")
                    from .research import compare_convergence_series, parse_log

                    case_root = root / "examples" / "research_cases"
                    gaussian = parse_log(
                        (case_root / "gaussian_reference/dvb_gopt.out").read_bytes()
                    )
                    series = compare_convergence_series(case_root / "hbn_vacuum/series.json")
                    hydrogen = loads_project(
                        (case_root / "h2_density/h2-density.calclens.zip").read_bytes()
                    )
                    if (
                        gaussian["status"] != "normal"
                        or len(series["cases"]) != 3
                        or not hydrogen.entries
                    ):
                        raise AssertionError("Bundled computational research examples failed.")
                    record["research"] = {
                        "gaussian": gaussian["status"],
                        "hbn": series["status"],
                        "h2_project": True,
                    }
                    if sys.platform == "darwin" and platform.machine() == "arm64":
                        import numpy as np
                        from .compute_devices import compute_arrays

                        _, _, device = compute_arrays([np.ones((3, 3, 3))], device="metal")
                        record["apple_gpu"] = {
                            "device": device["device_name"],
                            "effective": device["effective_device"],
                        }
                    original = window.workspace.project.entries[0].data
                    archived = window.workspace.export_workspace(
                        {
                            "expected_revision": window.workspace.revision,
                            "workspace_state": window.portable_state(),
                        }
                    )
                    assert loads_project(archived).entries[0].data == original
                    record.update(
                        status="passed",
                        formula=report["formula"],
                        atom_count=report["atom_count"],
                        screenshot=png.name,
                        active_window=window.windowTitle(),
                        native_widget=type(window).__name__,
                        browser_or_socket_listeners=0,
                    )
                except Exception as exc:
                    record["error"] = f"{type(exc).__name__}: {exc}"
                finally:
                    window.dirty = False
                    window.close()
                    app.quit()

            QTimer.singleShot(600, inspect)
            app.exec()
    except Exception as exc:
        record["error"] = f"{type(exc).__name__}: {exc}"
    path.write_text(json.dumps(record, ensure_ascii=False, indent=2), encoding="utf-8")
    return 0 if record["status"] == "passed" else 1


def _main(argv=None, *, root=None):
    args = list(sys.argv[1:] if argv is None else argv)
    if args[:1] == ["--worker"]:
        from .compute_server import main as worker_main

        return worker_main(args[1:])
    parser = argparse.ArgumentParser(description="CalcLens native desktop")
    parser.add_argument("--language", choices=("ko", "en"), default=None)
    parser.add_argument("--native-smoke", type=Path, metavar="RESULT.json")
    timing = parser.add_mutually_exclusive_group()
    timing.add_argument("--startup-trace", type=Path, metavar="TRACE.json",
                        help="Record actual startup milestones without closing the app.")
    timing.add_argument("--startup-benchmark", type=Path, metavar="TRACE.json",
                        help="Record startup and close only after the first input response.")
    parser.add_argument("files", nargs="*")
    options = parser.parse_args(args)
    startup.configure(options.startup_trace or options.startup_benchmark,
                      benchmark=options.startup_benchmark is not None)
    root = Path(root) if root is not None else resource_root()
    if options.native_smoke:
        return smoke(options.native_smoke, root, options.language or "ko")
    with startup.trace_span("qt_import"):
        import PySide6.QtWidgets  # noqa: F401 -- separately measured before scientific imports
    with startup.trace_span("scientific_import"):
        from .desktop import main as desktop_main

    return desktop_main(language=options.language, root=root, argv=["CalcLens", *options.files])


def main(argv=None, *, root=None):
    return startup.guarded_main(lambda: _main(argv, root=root))


if __name__ == "__main__":
    raise SystemExit(main())
