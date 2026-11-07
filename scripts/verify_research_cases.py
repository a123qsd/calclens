"""Check bounded research cases without Gaussian, PySCF, or network access.

Distances are independently enumerated over a finite [-2,2]^3 image shell,
without CalcLens MIC / lattice reduction code. A tiny literal-table reader is
used only for the controlled orthogonal/hexagonal fixtures, never arbitrary
CIFs. It preserves duplicate rows that ASE's high-level reader can merge.
This is not an independent electronic-structure implementation.
"""

from __future__ import annotations

import argparse
from hashlib import sha256
import itertools
import json
import math
from pathlib import Path
import runpy
import shlex
import sys

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from slab_preflight.core import UnsupportedStructure, analyze_cif  # noqa: E402
from slab_preflight.research import parse_log  # noqa: E402

DIRECTORY = ROOT / "examples" / "research_cases"


def independent_geometry(path: Path) -> dict:
    # This reference deliberately understands only our literal, one-row-per-
    # site test fixtures. Production ingestion continues to use the CIF parser.
    rows = [shlex.split(line, comments=True) for line in path.read_text().splitlines()]
    scalars = {row[0]: row[1] for row in rows
               if len(row) == 2 and row[0].startswith("_cell_")}
    lengths = [float(scalars[f"_cell_length_{axis}"]) for axis in "abc"]
    angles = [float(scalars[f"_cell_angle_{name}"]) for name in ("alpha", "beta", "gamma")]
    if angles[:2] != [90, 90]:
        raise ValueError("Literal fixture reference supports only a c-normal perpendicular cell.")
    gamma = math.radians(angles[2])
    cell = np.array([[lengths[0], 0, 0],
                     [lengths[1] * math.cos(gamma), lengths[1] * math.sin(gamma), 0],
                     [0, 0, lengths[2]]])
    start = next(index for index, row in enumerate(rows) if row == ["_atom_site_label"])
    fields = []
    while start < len(rows) and len(rows[start]) == 1 and rows[start][0].startswith("_atom_"):
        fields.append(rows[start][0])
        start += 1
    points = []
    for row in rows[start:]:
        if not row:
            continue
        if len(row) != len(fields):
            raise ValueError("Fixture reference requires one literal atom record per line.")
        atom = dict(zip(fields, row))
        points.append([float(atom[f"_atom_site_fract_{axis}"]) for axis in "xyz"])
    fractional = np.mod(np.asarray(points), 1)
    count = len(points)
    best = None
    for first in range(count):
        for second in range(first, count):
            for shift in itertools.product(range(-2, 3), repeat=3):
                if first == second and shift == (0, 0, 0):
                    continue
                vector = (fractional[second] - fractional[first] + shift) @ cell
                distance = float(np.sqrt(np.dot(vector, vector)))
                if best is None or distance < best["distance_angstrom"]:
                    best = {"distance_angstrom": distance, "atom_indices_zero_based": [first, second],
                            "periodic_shift": list(shift), "vector_angstrom": vector.tolist()}
    height = float(np.linalg.norm(cell[2]))
    heights = sorted(float(point[2]) * height for point in fractional)
    gaps = [heights[index + 1] - heights[index] for index in range(len(heights) - 1)]
    gaps.append(heights[0] + height - heights[-1])
    gap = max(gaps)
    return {"atom_count": count, "minimum_distance_angstrom": best["distance_angstrom"],
            "minimum_witness": best, "nuclei_gap_angstrom": gap,
            "nuclei_thickness_angstrom": height - gap}


def verify_cif_cases(directory: Path = DIRECTORY / "cif_cases") -> list[dict]:
    manifest = json.loads((directory / "cases.json").read_bytes())
    results = []
    for case in manifest["cases"]:
        path = directory / case["path"]
        data = path.read_bytes()
        if sha256(data).hexdigest() != case["sha256"]:
            raise ValueError(f"CIF case SHA-256 mismatch: {case['id']}")
        if case.get("expected_rejection_contains"):
            try:
                analyze_cif(data)
            except UnsupportedStructure as error:
                if case["expected_rejection_contains"].lower() not in str(error).lower():
                    raise ValueError(f"Unexpected rejection for {case['id']}: {error}") from error
                results.append({"id": case["id"], "class": case["class"],
                                "status": "expected_rejection", "reason": str(error)})
                continue
            raise ValueError(f"Unsupported CIF was incorrectly accepted: {case['id']}")
        independent = independent_geometry(path)
        report = analyze_cif(data)
        actual = {"atom_count": report["atom_count"], **report["metrics"]}
        for field, expected in case["expected"].items():
            if not np.isclose(independent[field], expected, atol=1e-8, rtol=0):
                raise ValueError(f"Independent/analytic geometry mismatch: {case['id']} {field}")
            if not np.isclose(actual[field], independent[field], atol=1e-8, rtol=0):
                raise ValueError(f"CalcLens/independent geometry mismatch: {case['id']} {field}")
        if case.get("expected_issue") and case["expected_issue"] not in {
            issue["code"] for issue in report["issues"]
        }:
            raise ValueError(f"Missing expected issue in {case['id']}")
        results.append({"id": case["id"], "class": case["class"], "status": "checked",
                        "source_sha256": case["sha256"], "independent": independent,
                        "maximum_absolute_metric_difference": max(
                            abs(float(actual[field]) - float(independent[field]))
                            for field in case["expected"]),
                        "issue_codes": [issue["code"] for issue in report["issues"]]})
    return results


def verify_gaussian_cases(directory: Path = DIRECTORY / "gaussian_reference") -> list[dict]:
    sources = json.loads((directory / "sources.json").read_bytes())
    results = []
    for record in sources["files"]:
        data = (directory / record["path"]).read_bytes()
        if len(data) != record["size_bytes"] or sha256(data).hexdigest() != record["sha256"]:
            raise ValueError(f"Public reference SHA-256 mismatch: {record['path']}")
        if record["path"] == "LICENSE.cclib":
            continue
        report = parse_log(data, source_name=record["path"], source_url=record["source_url"])
        if report["status"] != "normal" or len(report["steps"]) != 1:
            raise ValueError("Bundled public Gaussian reference was not parsed as one normal step.")
        step = report["steps"][0]
        if step["charge"] != 0 or step["multiplicity"] != 1 or step["atom_count"] != 20:
            raise ValueError("Unexpected state/atom mapping in public Gaussian case.")
        results.append({"path": record["path"], "sha256": record["sha256"],
                        "program": report["program"], "status": report["status"],
                        "route": step["route"], "optimization": step["optimization"]["status"],
                        "scf_energy_count": len(step["energies"]),
                        "frequency_count": step["frequencies"]["reported_mode_count"],
                        "final_scf_energy": step["final_scf_energy"]})
    return results


def verify_all() -> dict:
    convergence = runpy.run_path(str(ROOT / "scripts" / "prepare_convergence_case.py"))
    report = convergence["check_case"](DIRECTORY / "hbn_vacuum")
    return {"schema_version": 1, "kind": "research_case_verification",
            "cif_cases": verify_cif_cases(), "gaussian_cases": verify_gaussian_cases(),
            "convergence": {"status": report["status"], "summary": report["summary"],
                            "comparisons": report["comparisons"]},
            "limits": ["Automated controlled tests, not independent human researcher trials.",
                       "Independent geometry uses a literal-table fixture reader, not a general CIF reader.",
                       "Electronic matrix checks share PySCF integrals/components."]}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--write", action="store_true", help="Refresh the local verification JSON.")
    arguments = parser.parse_args()
    report = verify_all()
    if arguments.write:
        (DIRECTORY / "verification.json").write_text(
            json.dumps(report, indent=2, allow_nan=False) + "\n", encoding="utf-8")
    print(json.dumps(report, indent=2, allow_nan=False))


if __name__ == "__main__":
    main()
