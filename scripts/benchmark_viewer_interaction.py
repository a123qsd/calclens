"""Portable native viewport benchmark, including Windows display scale factors.

Run from a checkout with its desktop environment, for example:
    python scripts/benchmark_viewer_interaction.py --atoms 2 100 400 --scale-factor 1.5
Use --offscreen for CI; omit it for timings on the real Windows/macOS desktop.
Each scale factor needs a fresh process because Qt reads it at startup.
"""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import platform
import statistics
import sys
import time


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--atoms", type=int, nargs="+", default=[2, 100, 400])
    parser.add_argument("--iterations", type=int, default=8)
    parser.add_argument("--scale-factor", type=float, default=1.0)
    parser.add_argument("--quality", choices=("light", "balanced", "high", "auto"), default="balanced")
    parser.add_argument("--offscreen", action="store_true")
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    if any(count < 1 or count > 10000 for count in args.atoms) or args.iterations < 2:
        parser.error("Use 1–10000 atoms and at least two iterations.")
    if not 0.5 <= args.scale_factor <= 4:
        parser.error("Display scale factor must be between 0.5 and 4.")
    os.environ["QT_SCALE_FACTOR"] = str(args.scale_factor)
    if args.offscreen:
        os.environ["QT_QPA_PLATFORM"] = "offscreen"
    sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

    import numpy as np
    from PySide6 import __version__ as qt_version
    from PySide6.QtCore import QPoint
    from PySide6.QtTest import QTest
    from PySide6.QtWidgets import QApplication
    import slab_preflight.desktop_view as viewer

    app = QApplication.instance() or QApplication([])
    result = {"platform": platform.platform(), "python": platform.python_version(), "qt": qt_version,
              "offscreen": args.offscreen, "requested_scale_factor": args.scale_factor,
              "quality": args.quality, "iterations": args.iterations, "cases": []}

    def summary(values):
        return {"median_ms": round(statistics.median(values), 3),
                "p95_ms": round(float(np.percentile(values, 95)), 3)}

    for count in args.atoms:
        side = int(np.ceil(np.sqrt(count)))
        positions = [[(index % side) * 2.5, (index // side) * 2.5, 0] for index in range(count)]
        view = viewer.StructureView(language="en")
        view.resize(800, 560)
        view.set_graphics_quality(args.quality)
        view.set_structure({"positions": positions, "elements": ["C"] * count,
                            "cell": np.diag([side * 2.5, side * 2.5, 4]).tolist(), "metrics": {}})
        view.fit_atoms()
        view.show()
        app.processEvents()
        calls = [0]
        original = viewer.rasterize

        def counted(*values, **keywords):
            calls[0] += 1
            return original(*values, **keywords)

        viewer.rasterize = counted
        try:
            full, hover, selection = [], [], []
            for _ in range(args.iterations):
                view.yaw += 0.025
                started = time.perf_counter()
                view.repaint()
                full.append((time.perf_counter() - started) * 1000)
            full_calls = calls[0]
            # Choose projected atoms with visible fragments for actual pointer
            # moves. Hover updates include picking, tooltip and paint costs.
            visible = set(int(value) for value in np.unique(view._pick_map) if value >= 0)
            points = [(index, x, y) for index, x, y, _ in view._projected_atoms if index in visible]
            for iteration in range(args.iterations):
                index, x, y = points[iteration % len(points)]
                started = time.perf_counter()
                QTest.mouseMove(view, QPoint(round(x), round(y)))
                view.repaint()
                hover.append((time.perf_counter() - started) * 1000)
                started = time.perf_counter()
                view.set_selection([index])
                view.repaint()
                selection.append((time.perf_counter() - started) * 1000)
            result["cases"].append({"atoms": count, "actual_device_pixel_ratio": view.devicePixelRatioF(),
                                    "raster_size": view._last_render_stats["raster_size"],
                                    "scene": summary(full), "hover": summary(hover),
                                    "selection": summary(selection), "scene_raster_calls": full_calls,
                                    "hover_selection_raster_calls": calls[0] - full_calls})
        finally:
            viewer.rasterize = original
            view.close()
            app.processEvents()
    rendered = json.dumps(result, ensure_ascii=False, indent=2)
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(rendered + "\n", encoding="utf-8")
    print(rendered)


if __name__ == "__main__":
    main()
