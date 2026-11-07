"""Measure bounded structure/field parsing, native mesh building and process peak RSS."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import platform
import subprocess
import sys
from time import perf_counter

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))


def measure(operation):
    import resource
    from slab_preflight.core import _read_cif, analyze_cif
    from slab_preflight.density import parse_cube
    from slab_preflight.native_fields import isosurfaces

    if operation.startswith("cif"):
        text = "data_benchmark\n_cell_length_a 55\n_cell_length_b 55\n_cell_length_c 20\n_cell_angle_alpha 90\n_cell_angle_beta 90\n_cell_angle_gamma 90\n_space_group_IT_number 1\nloop_\n_atom_site_type_symbol\n_atom_site_fract_x\n_atom_site_fract_y\n_atom_site_fract_z\n_atom_site_occupancy\n"
        fixture = (
            text
            + "\n".join(f"C {i / 20} {j / 20} 0.5 1" for i in range(20) for j in range(20))
            + "\n"
        ).encode()
        start = perf_counter()
        if operation == "cif_parse":
            _read_cif(fixture, "c")
        else:
            analyze_cif(fixture)
        duration = perf_counter() - start
        source = "400-site synthetic square sheet; timing fixture only"
    else:
        source = "examples/research_cases/h2_density/ab.cube"
        raw = (ROOT / source).read_bytes()
        start = perf_counter()
        grid = parse_cube(raw, kind="density", units="e/bohr^3")
        duration = perf_counter() - start
        if operation == "native_mesh":
            start = perf_counter()
            meshes = isosurfaces(grid, 0.12)
            duration = perf_counter() - start
            source += (
                f"; level 0.12 e/angstrom^3, {sum(len(mesh['faces']) for mesh in meshes)} triangles"
            )
    rss = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
    return {
        "operation": operation,
        "source": source,
        "seconds": duration,
        "peak_process_rss_mib": rss / (2**20 if sys.platform == "darwin" else 1024),
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--operation")
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    if args.operation:
        print(json.dumps(measure(args.operation)))
        return
    data = {
        "platform": sys.platform,
        "architecture": platform.machine(),
        "units": "seconds and mebibytes",
        "method": "Three fresh processes per operation; peak RSS includes interpreter and loaded libraries. No GPU was requested.",
    }
    rows = []
    for mode in ("cif_parse", "cif_analyze", "cube_parse", "native_mesh"):
        runs = [
            json.loads(
                subprocess.check_output([sys.executable, __file__, "--operation", mode], text=True)
            )
            for _ in range(3)
        ]
        rows.append(
            {
                "operation": mode,
                "runs": runs,
                "median_seconds": sorted(r["seconds"] for r in runs)[1],
                "max_process_rss_mib": max(r["peak_process_rss_mib"] for r in runs),
            }
        )
    data["measurements"] = rows
    if args.output:
        args.output.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
    else:
        print(json.dumps(data, indent=2))


if __name__ == "__main__":
    main()
