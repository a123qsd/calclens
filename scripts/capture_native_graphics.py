#!/usr/bin/env python3
"""Capture actual offscreen Qt depth scenes and an original Cube at each preset."""
from __future__ import annotations

import argparse
from hashlib import sha256
import json
import platform
from pathlib import Path
import re
import subprocess
import types

import numpy as np
from PySide6 import __version__ as pyside_version
from PySide6.QtCore import QPointF
from PySide6.QtGui import QImage
from PySide6.QtWidgets import QApplication

from slab_preflight.core import analyze_cif
from slab_preflight.density import parse_cube
from slab_preflight.desktop_view import StructureView
from slab_preflight.native_fields import isosurfaces


ROOT = Path(__file__).resolve().parents[1]


def depth_view(view_class, z=1, opacity=1):
    view = view_class(language="en")
    view.resize(900, 640)
    view.set_structure({"positions": [[0., 0., 0.]], "cell": np.diag([4., 4., 4.]).tolist(),
                        "elements": ["O"], "normal_axis": "c", "metrics": {}},
                       {"filename": "Depth scene: oxygen and plane", "sha256": "a" * 64})
    view.show_cell = view.show_bonds = False
    view.yaw = view.pitch = 0
    view.set_surfaces([{"vertices": [[-1.5, -1.5, z], [1.5, -1.5, z], [1.5, 1.5, z], [-1.5, 1.5, z]],
                        "faces": [[0, 1, 2], [0, 2, 3]], "opacity": opacity, "color": "#4d9db0",
                        "label": f"Test plane z = {z:+g} Å, α = {opacity:g}"}],
                      {"kind": "density", "units": "e/angstrom^3", "isovalue": 0.05,
                       "filename": "synthetic-depth-plane", "source_sha256": "b" * 64,
                       "scope": "Geometric depth fixture; this plane is not an electronic calculation."})
    return view


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--baseline-ref", help="Optional original Git commit, 7–40 hex digits.")
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=True)
    app = QApplication.instance() or QApplication([])
    view_class = StructureView
    prefix = "graphics-after"
    if args.baseline_ref:
        if not re.fullmatch(r"[a-fA-F0-9]{7,40}", args.baseline_ref):
            parser.error("baseline-ref must be a Git commit hash")
        source = subprocess.run(["git", "show", f"{args.baseline_ref}:src/slab_preflight/desktop_view.py"],
                                cwd=ROOT, check=True, capture_output=True, text=True).stdout
        module = types.ModuleType("calclens_baseline_graphics")
        exec(compile(source, "baseline/desktop_view.py", "exec"), module.__dict__)
        view_class, prefix = module.StructureView, "graphics-before"
    observations = {"environment": {"system": platform.system(), "architecture": platform.machine(),
                                     "python": platform.python_version(), "pyside": pyside_version,
                                     "qt_platform": app.platformName()}, "baseline_ref": args.baseline_ref,
                    "scenes": []}

    def capture(view, suffix):
        view.show()
        app.processEvents()
        path = args.output / f"{prefix}-{suffix}.png"
        view.grab().save(str(path))
        point = QPointF(*view._projected_atoms[0][1:3]) if view._projected_atoms else QPointF()
        record = {"image": path.name, "picked_center_atom": view._picked(point)}
        if hasattr(view, "_last_render_stats"):
            record["rendering"] = view._last_render_stats
        observations["scenes"].append(record)
        view.close()

    for suffix, z, opacity in (("opaque-plane", 1, 1), ("plane-behind-atom", -1, 1), ("transparent-plane", 1, 0.45)):
        capture(depth_view(view_class, z, opacity), suffix)
    if not args.baseline_ref:
        view = depth_view(view_class)
        view.positions[0, 2] = -3
        vertices = [[-1.5, -1.5, -1], [1.5, -1.5, 1], [1.5, 1.5, 1], [-1.5, 1.5, -1]]
        flat = np.array(vertices)
        flat[:, 2] = 0
        view.set_surfaces([{"vertices": vertices, "faces": [[0, 1, 2], [0, 2, 3]], "opacity": 0.65,
                            "color": "#cf5a59", "label": "Crossing red plane"},
                           {"vertices": flat, "faces": [[0, 1, 2], [0, 2, 3]], "opacity": 0.65,
                            "color": "#4c74bd", "label": "Blue reference plane"}],
                          {"scope": "Two synthetic crossing planes; red depth changes continuously across x."})
        capture(view, "intersecting-transparent-planes")
    directory = ROOT / "examples/electronic_case"
    cif, cube = (directory / "water.cif").read_bytes(), (directory / "density.cube").read_bytes()
    grid = parse_cube(cube, kind="density", units="e/bohr^3", source_name="density.cube")
    meshes = isosurfaces(grid, 0.05)
    for quality in (("baseline",) if args.baseline_ref else ("light", "balanced", "high")):
        view = view_class(language="en")
        view.resize(1000, 700)
        view.set_structure(analyze_cif(cif), {"filename": "water.cif", "sha256": sha256(cif).hexdigest()})
        view.show_cell = False
        if not args.baseline_ref:
            view.set_graphics_quality(quality)
        view.set_surfaces(meshes, {"dataset_id": "verification-water-density", "name": "Water total electron density",
                                  "filename": "density.cube", "kind": grid.kind, "units": grid.units,
                                  "isovalue": 0.05, "source_sha256": grid.source_sha256})
        capture(view, f"water-{quality}")
        if quality == "high":
            for width, background in ((800, "transparent"), (1600, "white"), (3200, "white")):
                path = args.output / f"{prefix}-water-export-{width}-{background}.png"
                view.export_png(path, width=width, background=background)
                image = QImage(str(path))
                observations["scenes"].append({"image": path.name, "width": image.width(), "height": image.height(),
                                                "rendering": json.loads(image.text("CalcLens provenance"))["rendering"]})
    report = args.output / f"{prefix}-observations.json"
    report.write_text(json.dumps(observations, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(report)


if __name__ == "__main__":
    main()
