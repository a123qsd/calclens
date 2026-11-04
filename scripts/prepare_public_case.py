"""Reproduce the bundled COD graphite case without network access.

This is a deliberately source-specific preparation, not a general CIF converter.
The independent reference below uses only stdlib geometry and no CalcLens/ASE
distance or symmetry routines. Run from the repository with PYTHONPATH=src.
"""

from __future__ import annotations

import argparse
from hashlib import sha256
from io import BytesIO
from itertools import product
import json
from math import isfinite, sqrt
from pathlib import Path

import ase
from ase import Atoms
from ase.io.cif import parse_cif
import numpy as np


ROOT = Path(__file__).resolve().parents[1]
CASE_DIR = ROOT / "examples" / "public_case"
SOURCE = CASE_DIR / "source" / "9011577-rev291877.cif"
SOURCE_SHA256 = "35d1661c3131acc9b1c33dad65358d094b93105d6aae711465ac4352ae809748"
SOURCE_URL = "https://www.crystallography.net/cod/9011577.cif"
REVISION_URL = "https://www.crystallography.net/cod/9011577.cif@291877"
A = 2.464
SOURCE_C = 6.711
SLAB_C = 20.0
# Identity and (-x, -x+y, z+1/2), as listed in the source, produce these sites.
# Keep the deposited five-decimal fractions, including 0.33334 in layer two.
REFERENCE_BULK = (
    (0.0, 0.0, 0.25),
    (0.33333, 0.66667, 0.25),
    (0.0, 0.0, 0.75),
    (0.66667, 0.33334, 0.75),
)
REFERENCE_SLAB = ((0.0, 0.0, 0.5), (0.33333, 0.66667, 0.5))
METRICS = (
    "minimum_distance_angstrom",
    "normal_height_angstrom",
    "nuclei_thickness_angstrom",
    "nuclei_gap_angstrom",
    "second_largest_gap_angstrom",
    "gap_fraction",
)


def validate_occupancy(block) -> str:
    """Reject ambiguity before symmetry expansion can choose a species.

    For this pinned source, an omitted occupancy is expanded using the
    documented coreCIF dictionary default, 1.0. Unknown explicit values do not
    receive that default.
    """
    count = len(block["_atom_site_label"])
    for key in ("_atom_site_disorder_assembly", "_atom_site_disorder_group"):
        if key in block:
            values = block[key]
            if not isinstance(values, list) or len(values) != count:
                raise ValueError("Malformed disorder column in public source.")
            if any(str(value) not in (".", "0") for value in values):
                raise ValueError("Disordered sites cannot be prepared as full occupancy.")
    if "_atom_site_occupancy" not in block:
        return "omitted in source; coreCIF default 1.0 made explicit"
    values = block["_atom_site_occupancy"]
    if not isinstance(values, list) or len(values) != count:
        raise ValueError("Occupancy column must contain one value per source site.")
    try:
        occupancies = [float(value) for value in values]
    except (TypeError, ValueError):
        raise ValueError("Unknown occupancy cannot be replaced by 1.0.") from None
    if any(not isfinite(value) or abs(value - 1.0) > 1e-10 for value in occupancies):
        raise ValueError("Only fully occupied source sites can be prepared.")
    return "explicit source occupancy 1.0 retained"


def _sorted_atoms(atoms: Atoms) -> Atoms:
    scaled = atoms.get_scaled_positions(wrap=True)
    order = sorted(range(len(atoms)), key=lambda index: tuple(scaled[index, [2, 0, 1]]))
    return atoms[order]


def prepare_structures(source: bytes) -> tuple[Atoms, Atoms, str]:
    """Validate this graphite record, expand it, and select its z=1/4 sheet."""
    blocks = list(parse_cif(BytesIO(source)))
    if len(blocks) != 1:
        raise ValueError("The public case requires exactly one source data block.")
    block = blocks[0]
    policy = validate_occupancy(block)
    if block.name != "9011577" or block.get("_chemical_formula_sum") != "C":
        raise ValueError("This preparation is restricted to COD 9011577 graphite.")
    if block.get("_space_group_it_number") != 194:
        raise ValueError("The source must retain its P63/mmc space group, number 194.")
    if block["_atom_site_label"] != ["C1", "C2"] or block.get_symbols() != ["C", "C"]:
        raise ValueError("Expected the two carbon-only asymmetric source sites.")
    if not np.allclose(block.get_cell().cellpar(), [A, A, SOURCE_C, 90, 90, 120], atol=1e-10, rtol=0):
        raise ValueError("Unexpected source cell or direction; the case requires c normal to ab.")
    bulk = _sorted_atoms(block.get_atoms(
        primitive_cell=False, subtrans_included=True, fractional_occupancies=True,
    ))
    if len(bulk) != 4 or bulk.get_chemical_symbols() != ["C"] * 4:
        raise ValueError("Source symmetry expansion must produce four carbon sites.")
    if not np.allclose(bulk.get_scaled_positions(), REFERENCE_BULK, atol=1e-10, rtol=0):
        raise ValueError("Expanded sites disagree with the source-derived symmetry reference.")
    scaled = bulk.get_scaled_positions()
    selected = np.isclose(scaled[:, 2], 0.25, atol=1e-10, rtol=0)
    if np.count_nonzero(selected) != 2:
        raise ValueError("Expected exactly two atoms in the source z=1/4 basal sheet.")
    slab_scaled = scaled[selected].copy()
    slab_scaled[:, 2] = 0.5
    slab = Atoms("C2", scaled_positions=slab_scaled,
                 cell=[A, A, SLAB_C, 90, 90, 120], pbc=True)
    return bulk, slab, policy


def explicit_p1(atoms: Atoms, name: str, description: str) -> str:
    """Write only explicit sites and identity symmetry, with occupancy 1."""
    names = ("length_a", "length_b", "length_c", "angle_alpha", "angle_beta", "angle_gamma")
    lines = [
        "# Derived from COD 9011577 revision 291877 (COD data: CC0).",
        "# Trucano and Chen, Nature 258 (1975), 136-137; doi:10.1038/258136a0.",
        f"# {description}",
        f"data_{name}",
    ]
    lines.extend(f"_cell_{key} {value:.12g}" for key, value in zip(names, atoms.cell.cellpar()))
    lines.extend([
        "_space_group_IT_number 1", "_space_group_name_H-M_alt 'P 1'",
        "loop_", "_space_group_symop_operation_xyz", "'x,y,z'", "loop_",
        "_atom_site_label", "_atom_site_type_symbol", "_atom_site_fract_x",
        "_atom_site_fract_y", "_atom_site_fract_z", "_atom_site_occupancy",
    ])
    for index, (symbol, point) in enumerate(zip(atoms.symbols, atoms.get_scaled_positions()), 1):
        x, y, z = point
        lines.append(f"{symbol}{index} {symbol} {x:.12g} {y:.12g} {z:.12g} 1")
    return "\n".join(lines) + "\n"


def independent_minimum(fractional, c: float) -> float:
    """Enumerate all pairs and [-2,2]^3 shifts in this hexagonal reference.

    The analytic reference basis is (a,0,0), (-a/2,sqrt(3)*a/2,0), (0,0,c).
    No ASE/CalcLens cell, minimum-image, or distance routine is used. The range
    includes adjacent hexagonal neighbours and self-images for these four
    known, wrapped reference sites; it is not a general skew-cell algorithm.
    """
    distances = []
    for i, first in enumerate(fractional):
        for j, second in enumerate(fractional):
            for shift in product(range(-2, 3), repeat=3):
                if i == j and shift == (0, 0, 0):
                    continue
                dx, dy, dz = (second[k] - first[k] + shift[k] for k in range(3))
                cartesian = (A * (dx - dy / 2), A * sqrt(3) * dy / 2, c * dz)
                distances.append(sqrt(sum(value * value for value in cartesian)))
    return min(distances)


def build_artifacts(source: bytes) -> dict[str, str]:
    """Build the two CIFs and a measured comparison; fail if checks disagree."""
    from slab_preflight.core import analyze_cif

    if sha256(source).hexdigest() != SOURCE_SHA256:
        raise ValueError("Public source SHA-256 mismatch; use the bundled unmodified source.")
    bulk, slab, occupancy_policy = prepare_structures(source)
    artifacts = {
        "graphite_p1.cif": explicit_p1(bulk, "cod_9011577_expanded", "Bulk graphite; no vacuum added."),
        "graphene_from_graphite_p1.cif": explicit_p1(
            slab, "cod_9011577_basal_sheet", "One basal sheet; c=20 angstrom; unrelaxed derived model.",
        ),
    }
    comparisons = {}
    for filename, points, c, thickness, gap, second_gap in (
        ("graphite_p1.cif", REFERENCE_BULK, SOURCE_C, SOURCE_C / 2, SOURCE_C / 2, SOURCE_C / 2),
        ("graphene_from_graphite_p1.cif", REFERENCE_SLAB, SLAB_C, 0.0, SLAB_C, 0.0),
    ):
        report = analyze_cif(artifacts[filename], short_distance=1.0, normal_axis="c")
        reference = {
            "minimum_distance_angstrom": independent_minimum(points, c),
            "normal_height_angstrom": c,
            "nuclei_thickness_angstrom": thickness,
            "nuclei_gap_angstrom": gap,
            "second_largest_gap_angstrom": second_gap,
            "gap_fraction": gap / c,
        }
        errors = {key: abs(report["metrics"][key] - reference[key]) for key in METRICS}
        if any(value > 1e-9 for value in errors.values()):
            raise ValueError(f"CalcLens geometry disagrees with the independent reference: {filename}")
        comparisons[filename] = {
            "atom_count": report["atom_count"],
            "normal_axis": report["normal_axis"],
            "in_plane_axes": report["in_plane_axes"],
            "calclens_metrics": {key: report["metrics"][key] for key in METRICS},
            "independent_reference": reference,
            "absolute_errors": errors,
            "short_contact_count": report["short_contact_count"],
            "issue_codes": sorted(issue["code"] for issue in report["issues"]),
            "gap_review_required": report["gap_review_required"],
        }
    provenance = {
        "source": {
            "cod_id": "9011577", "revision": 291877,
            "download_url": SOURCE_URL, "revision_url": REVISION_URL,
            "retrieved_date": "2026-11-04", "sha256": SOURCE_SHA256,
            "license": "CC0-1.0",
            "license_evidence_url": "https://www.crystallography.net/cod/9011577.html",
            "article_doi": "10.1038/258136a0", "occupancy_policy": occupancy_policy,
        },
        "preparation": {
            "source_asymmetric_sites": 2, "source_symmetry_operations": 24,
            "expanded_sites": len(bulk), "selected_sheet_sites": len(slab),
            "selected_source_fractional_z": 0.25, "slab_fractional_z": 0.5,
            "slab_normal_repeat_angstrom": SLAB_C,
            "relaxation_performed": False, "fractional_xy_rounding_retained": True,
        },
        "environment": {"ase": ase.__version__, "numpy": np.__version__},
        "benchmark": {
            "method": "stdlib periodic-image enumeration and analytical hexagonal geometry",
            "comparison_tolerance_angstrom": 1e-9,
            "ideal_honeycomb_a_over_sqrt3_angstrom": A / sqrt(3),
            "source_fractional_rounding_tolerance_angstrom": 3e-5,
            "cases": comparisons,
        },
    }
    provenance["derived_sha256"] = {
        name: sha256(text.encode("utf-8")).hexdigest() for name, text in artifacts.items()
    }
    artifacts["case_results.json"] = json.dumps(provenance, indent=2, allow_nan=False) + "\n"
    return artifacts


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", type=Path, default=CASE_DIR)
    parser.add_argument("--check", action="store_true", help="verify committed artifacts without writing")
    args = parser.parse_args()
    artifacts = build_artifacts(SOURCE.read_bytes())
    if args.check:
        mismatches = [name for name, text in artifacts.items()
                      if not (args.output_dir / name).exists()
                      or (args.output_dir / name).read_bytes() != text.encode("utf-8")]
        if mismatches:
            parser.exit(1, "Public-case artifacts differ: " + ", ".join(mismatches) + "\n")
        print("Public source hash, preparation, and independent geometry comparison passed.")
    else:
        args.output_dir.mkdir(parents=True, exist_ok=True)
        for name, text in artifacts.items():
            (args.output_dir / name).write_bytes(text.encode("utf-8"))
        print(f"Prepared {len(artifacts)} public-case artifacts in {args.output_dir}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
