"""Bounded log interpretation and auditable vacuum-series comparison.

The series format binds the source CIF, every derived CIF, original output and
machine-readable result by SHA-256. Conditions and internal Cartesian geometry
must stay fixed. Successful samples establish only a sampled energy tolerance,
not a general material-specific prescription for sufficient vacuum.
"""

from __future__ import annotations

from hashlib import sha256
import json
import math
from pathlib import Path
import re
from typing import Any

import numpy as np

from .core import MAX_FILE_BYTES, _read_cif
from .research_logs import (  # re-export the native application's public API
    HARTREE_EV, MAX_LOG_BYTES, ResearchError, convert_energy, parse_log,
)

__all__ = ["ResearchError", "parse_log", "convert_energy", "build_vacuum_cif",
           "load_convergence_series", "compare_convergence_series"]
MAX_MANIFEST_BYTES = 4 * 1024 * 1024
MAX_SERIES_CASES = 64
MAX_BUNDLE_BYTES = 128 * 1024 * 1024
GEOMETRY_ATOL_ANGSTROM = 1e-6


def _finite(value: Any, name: str, *, positive: bool = False) -> float:
    if (isinstance(value, bool) or not isinstance(value, (int, float))
            or not math.isfinite(value) or (positive and value <= 0)):
        raise ResearchError(f"{name} must be a finite {'positive ' if positive else ''}number.")
    return float(value)


def _unique_pairs(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result = {}
    for key, value in pairs:
        if key in result:
            raise ResearchError(f"Repeated JSON key: {key}.")
        result[key] = value
    return result


def _json(data: bytes, description: str) -> dict[str, Any]:
    if len(data) > MAX_MANIFEST_BYTES:
        raise ResearchError(f"{description} exceeds {MAX_MANIFEST_BYTES} bytes.")
    try:
        result = json.loads(data, object_pairs_hook=_unique_pairs,
                            parse_constant=lambda value: (_ for _ in ()).throw(
                                ResearchError(f"Non-finite JSON constant: {value}.")))
    except (UnicodeDecodeError, json.JSONDecodeError, RecursionError) as error:
        raise ResearchError(f"Cannot read {description}: {error}.") from None
    if not isinstance(result, dict):
        raise ResearchError(f"{description} must be a JSON object.")
    return result


def _artifact(root: Path, record: Any, *, limit: int) -> tuple[bytes, dict[str, Any]]:
    if not isinstance(record, dict) or not isinstance(record.get("path"), str):
        raise ResearchError("Artifact requires a relative path and SHA-256.")
    relative = Path(record["path"])
    # Windows syntax is rejected on every host, as are parent components,
    # symlinks escaping the selected bundle, and absolute paths.
    if (relative.anchor or not relative.parts or ".." in relative.parts
            or "\\" in record["path"] or ":" in record["path"]):
        raise ResearchError("Artifact paths must stay inside the selected series bundle.")
    try:
        path = (root / relative).resolve(strict=True)
    except (OSError, RuntimeError):
        raise ResearchError(f"Missing artifact: {relative}.") from None
    if not path.is_relative_to(root) or not path.is_file():
        raise ResearchError("Artifact paths must stay inside the selected series bundle.")
    digest = record.get("sha256")
    if not isinstance(digest, str) or not re.fullmatch(r"[0-9a-f]{64}", digest):
        raise ResearchError(f"Missing/invalid SHA-256 for {relative}.")
    if path.stat().st_size > limit:
        raise ResearchError(f"Artifact is too large: {relative}.")
    # Re-check after reading so a changing file cannot bypass the size bound.
    data = path.read_bytes()
    if len(data) > limit or sha256(data).hexdigest() != digest:
        raise ResearchError(f"Artifact SHA-256 or size mismatch: {relative}.")
    provenance = {**record, "size_bytes": len(data)}
    return data, provenance


def _geometry(data: bytes, normal_axis: str) -> dict[str, Any]:
    """Unwrap across the largest empty normal gap before measuring offsets.

    Comparing raw fractional coordinates when c changes distorts a buckled or
    boundary-wrapped layer. Here the ordered, relative Cartesian positions are
    the invariant; a common translation is irrelevant. No atom is deleted,
    merged, permuted, relaxed, or assigned to a layer automatically.
    """
    if normal_axis not in ("a", "b", "c"):
        raise ResearchError("normal_axis must be a, b, or c.")
    try:
        atoms, _ = _read_cif(data, normal_axis)
    except ValueError as error:
        raise ResearchError(f"Unsupported series CIF: {error}") from None
    axis = "abc".index(normal_axis)
    cell = np.asarray(atoms.cell)
    length = float(np.linalg.norm(cell[axis]))
    scaled = atoms.get_scaled_positions(wrap=True)
    ordered = np.sort(np.unique(np.round(scaled[:, axis], 12)))
    gaps = np.diff(np.r_[ordered, ordered[0] + 1])
    largest = int(np.argmax(gaps))
    if len(gaps) > 1 and np.count_nonzero(np.isclose(gaps, gaps[largest], atol=1e-10)) > 1:
        raise ResearchError("The normal gap is ambiguous; explicit layer selection is required.")
    cut = float(ordered[(largest + 1) % len(ordered)])
    offsets = (scaled[:, axis] < cut - 1e-10).astype(float)
    points = atoms.positions + offsets[:, None] * cell[axis]
    relative = points - points[0]
    normal = cell[axis] / length
    projection = relative @ normal
    thickness = float(np.ptp(projection))
    return {
        "elements": atoms.get_chemical_symbols(), "atom_count": len(atoms),
        "cell_angstrom": cell.tolist(), "normal_axis": normal_axis,
        "normal_vector": normal.tolist(), "normal_repeat_angstrom": length,
        "relative_cartesian_angstrom": relative.tolist(),
        "unwrapped_cartesian_angstrom": points.tolist(),
        "nuclei_thickness_angstrom": thickness,
        "vacuum_angstrom": length - thickness,
        "vacuum_definition": "largest cyclic nuclei-to-nuclei gap; not density-free vacuum",
        "inplane_vectors_angstrom": np.delete(cell, axis, axis=0).tolist(),
    }


def build_vacuum_cif(data: bytes, vacuum_angstrom: float, *, normal_axis: str = "c",
                     center_fraction: float = 0.5) -> bytes:
    """Change only the normal repeat, preserving ordered internal Cartesian offsets.

    The source remains untouched. ``center_fraction=0`` deliberately wraps the
    layer around the cell boundary and is useful for checking the invariant.
    The input must already meet the explicit full-occupancy P1 contract.
    """
    vacuum = _finite(vacuum_angstrom, "Vacuum", positive=True)
    center = _finite(center_fraction, "Layer center")
    if not 0 <= center < 1:
        raise ResearchError("Layer center fraction must be in [0, 1).")
    geometry = _geometry(data, normal_axis)
    axis = "abc".index(normal_axis)
    cell = np.array(geometry["cell_angstrom"])
    normal = np.array(geometry["normal_vector"])
    new_length = geometry["nuclei_thickness_angstrom"] + vacuum
    cell[axis] = normal * new_length
    points = np.array(geometry["unwrapped_cartesian_angstrom"])
    projections = points @ normal
    shift = center * new_length - (projections.min() + projections.max()) / 2
    points = points + shift * normal
    fractional = np.mod(points @ np.linalg.inv(cell), 1.0)
    from ase.cell import Cell

    parameters = Cell(cell).cellpar()
    lines = [
        "# Constructed vacuum variant; no relaxation or experimental structure claim.",
        f"# Source SHA-256: {sha256(data).hexdigest()}",
        "# Atom order and internal Cartesian geometry retained across the normal boundary.",
        "data_vacuum_variant",
    ]
    for name, value in zip(("length_a", "length_b", "length_c", "angle_alpha",
                            "angle_beta", "angle_gamma"), parameters):
        lines.append(f"_cell_{name} {value:.12f}")
    lines.extend(["_space_group_IT_number 1", "_space_group_name_H-M_alt 'P 1'", "loop_",
                  "_space_group_symop_operation_xyz", "'x,y,z'", "loop_", "_atom_site_label",
                  "_atom_site_type_symbol", "_atom_site_fract_x", "_atom_site_fract_y",
                  "_atom_site_fract_z", "_atom_site_occupancy"])
    for index, (element, point) in enumerate(zip(geometry["elements"], fractional), 1):
        lines.append(f"{element}{index} {element} "
                     + " ".join(f"{value:.12f}" for value in point) + " 1")
    result = ("\n".join(lines) + "\n").encode()
    _assert_geometry_equal(geometry, _geometry(result, normal_axis))
    return result


def _assert_geometry_equal(reference: dict[str, Any], candidate: dict[str, Any]) -> None:
    if reference["elements"] != candidate["elements"]:
        raise ResearchError("Atom identity/order differs from the source CIF.")
    for field in ("inplane_vectors_angstrom", "normal_vector", "relative_cartesian_angstrom"):
        if not np.allclose(reference[field], candidate[field], atol=GEOMETRY_ATOL_ANGSTROM,
                           rtol=0):
            raise ResearchError(f"Fixed geometry differs from the source CIF: {field}.")


def _conditions(value: Any) -> dict[str, Any]:
    if not isinstance(value, dict) or not value:
        raise ResearchError("Fixed calculation conditions must be a nonempty object.")
    required = {"program", "program_version", "method", "basis", "charge", "multiplicity",
                "kpoint_grid", "periodic_dimensions", "energy_quantity"}
    if not required.issubset(value):
        raise ResearchError("Fixed conditions lack required program/method/basis/state/k-point fields.")
    for field in ("program", "program_version", "method", "basis", "energy_quantity"):
        if not isinstance(value[field], str) or not value[field].strip():
            raise ResearchError(f"Fixed condition {field} must be explicitly specified.")
    if value["energy_quantity"] != "electronic_total":
        raise ResearchError("Only total electronic energies are supported for vacuum comparison.")
    for field in ("charge", "multiplicity", "periodic_dimensions"):
        if isinstance(value[field], bool) or not isinstance(value[field], int):
            raise ResearchError(f"Fixed condition {field} must be an integer.")
    if value["multiplicity"] < 1 or value["periodic_dimensions"] not in (2, 3):
        raise ResearchError("Invalid multiplicity or periodic dimension for a slab series.")
    kpoints = value["kpoint_grid"]
    if (not isinstance(kpoints, list) or len(kpoints) != 3
            or any(isinstance(x, bool) or not isinstance(x, int) or x < 1 for x in kpoints)):
        raise ResearchError("kpoint_grid must be three positive integers.")
    return value


def _periodic_input_matches(raw: str, conditions: dict, geometry: dict) -> bool:
    """Check the controlled PySCF log's input snapshot, not only its energy line.

    Generic molecular logs cannot establish a periodic vacuum series. Version
    one therefore supports the explicit input envelope emitted by the bundled
    script; it does not infer cell/k-points from an arbitrary PySCF log.
    """
    lines = raw.splitlines()
    if len(lines) < 2 or lines[0] != "CalcLens controlled periodic input; lengths in angstrom.":
        return False
    try:
        snapshot = _json(lines[1].encode(), "Periodic log input snapshot")
        if snapshot.get("fixed_conditions") != conditions or snapshot.get("elements") != geometry["elements"]:
            return False
        cell = np.asarray(snapshot.get("cell_angstrom"), dtype=float)
        points = np.asarray(snapshot.get("positions_angstrom"), dtype=float)
        if (cell.shape != (3, 3) or points.shape != (geometry["atom_count"], 3)
                or not np.isfinite(cell).all() or not np.isfinite(points).all()
                or not np.allclose(cell, geometry["cell_angstrom"],
                                   atol=GEOMETRY_ATOL_ANGSTROM, rtol=0)):
            return False
        difference = (points - np.array(geometry["unwrapped_cartesian_angstrom"])) @ np.linalg.inv(cell)
        cartesian_error = (difference - np.rint(difference)) @ cell
        return bool(np.max(np.abs(cartesian_error)) <= GEOMETRY_ATOL_ANGSTROM)
    except (ResearchError, ValueError, TypeError, np.linalg.LinAlgError):
        return False


def load_convergence_series(path: str | Path) -> dict[str, Any]:
    """Read and verify a self-contained series bundle, with no network access."""
    try:
        path = Path(path).resolve(strict=True)
    except (OSError, RuntimeError, TypeError):
        raise ResearchError("Series manifest is missing or inaccessible.") from None
    if not path.is_file() or path.stat().st_size > MAX_MANIFEST_BYTES:
        raise ResearchError("Series manifest is missing or too large.")
    manifest_data = path.read_bytes()
    manifest = _json(manifest_data, "Series manifest")
    if manifest.get("schema_version") != 1 or manifest.get("kind") != "vacuum_convergence_series":
        raise ResearchError("Unsupported convergence-series schema.")
    variable = manifest.get("variable")
    if not isinstance(variable, dict) or variable.get("name") != "vacuum_angstrom":
        raise ResearchError("Only the explicitly named vacuum_angstrom variable is supported.")
    normal_axis = variable.get("normal_axis")
    fixed = _conditions(manifest.get("fixed_conditions"))
    tolerance = manifest.get("tolerance")
    if not isinstance(tolerance, dict) or tolerance.get("unit") != "meV/atom":
        raise ResearchError("Acceptance tolerance must be labelled meV/atom.")
    _finite(tolerance.get("value"), "Acceptance tolerance", positive=True)
    minimum = tolerance.get("minimum_successful_cases", 3)
    if isinstance(minimum, bool) or not isinstance(minimum, int) or not 2 <= minimum <= MAX_SERIES_CASES:
        raise ResearchError("minimum_successful_cases must be an integer between 2 and 64.")
    cases = manifest.get("cases")
    if not isinstance(cases, list) or not 1 <= len(cases) <= MAX_SERIES_CASES:
        raise ResearchError("A convergence series requires 1 to 64 cases.")
    source, source_provenance = _artifact(path.parent, manifest.get("source_cif"),
                                          limit=MAX_FILE_BYTES)
    if any(not isinstance(source_provenance.get(field), str)
           or not source_provenance[field].strip() for field in ("origin", "license")):
        raise ResearchError("Source CIF requires origin and reuse/license information.")
    source_geometry = _geometry(source, normal_axis)
    loaded = []
    ids = set()
    total_bytes = len(manifest_data) + len(source)
    for case in cases:
        if not isinstance(case, dict) or not isinstance(case.get("id"), str) or not case["id"]:
            raise ResearchError("Every case needs a nonempty id.")
        if case["id"] in ids:
            raise ResearchError("Repeated convergence-case id.")
        ids.add(case["id"])
        vacuum = _finite(case.get("vacuum_angstrom"), "Case vacuum", positive=True)
        cif, cif_provenance = _artifact(path.parent, case.get("cif"), limit=MAX_FILE_BYTES)
        output, output_provenance = _artifact(path.parent, case.get("output"), limit=MAX_LOG_BYTES)
        result_data, result_provenance = _artifact(path.parent, case.get("result"),
                                                  limit=MAX_MANIFEST_BYTES)
        result = _json(result_data, "Calculation result")
        if result.get("schema_version") != 1 or result.get("kind") != "calclens_calculation_result":
            raise ResearchError("Unsupported per-case calculation result schema.")
        total_bytes += len(cif) + len(output) + len(result_data)
        if total_bytes > MAX_BUNDLE_BYTES:
            raise ResearchError("Convergence bundle exceeds its 128 MiB read limit.")
        if result.get("input_cif_sha256") != cif_provenance["sha256"]:
            raise ResearchError("Calculation result is not bound to its exact case CIF.")
        if result.get("output_sha256") != output_provenance["sha256"]:
            raise ResearchError("Calculation result is not bound to its original output.")
        geometry = _geometry(cif, normal_axis)
        reasons = []
        comparable = True
        try:
            _assert_geometry_equal(source_geometry, geometry)
        except ResearchError as error:
            reasons.append(str(error))
            comparable = False
        if abs(geometry["vacuum_angstrom"] - vacuum) > GEOMETRY_ATOL_ANGSTROM:
            reasons.append("Declared vacuum differs from the CIF nuclei gap.")
            comparable = False
        conditions = _conditions(result.get("fixed_conditions"))
        if conditions != fixed:
            reasons.append("Calculation conditions differ from the series fixed conditions.")
            comparable = False
        status = result.get("status")
        if status not in ("normal", "failure", "truncated", "unknown"):
            raise ResearchError("Unknown calculation status label.")
        if status != "normal" or result.get("scf_converged") is not True:
            reasons.append("Failed, incomplete, or unconfirmed SCF run is excluded.")
        energy = result.get("energy")
        energy_hartree = None
        if energy is not None:
            if not isinstance(energy, dict) or energy.get("quantity") != "electronic_total":
                raise ResearchError("Case energy must identify electronic_total and an explicit unit.")
            energy_hartree = convert_energy(energy.get("value"), energy.get("unit"))
        else:
            reasons.append("No total electronic energy was supplied.")
        output_kind = case.get("output", {}).get("kind")
        if output_kind == "pyscf_log":
            raw = output.decode("utf-8", errors="replace")
            if not _periodic_input_matches(raw, conditions, geometry):
                reasons.append("Original output lacks a matching controlled periodic input snapshot.")
            matches = list(re.finditer(r"converged SCF energy\s*=\s*([-+\d.eEdD]+)", raw))
            final_scf_confirmed = bool(matches) and "SCF not converged" not in raw[
                matches[-1].end():]
            if not final_scf_confirmed:
                if status == "normal":
                    reasons.append("Original PySCF log does not establish a converged final SCF.")
            elif energy_hartree is not None:
                printed = float(matches[-1].group(1).replace("D", "E").replace("d", "e"))
                if not math.isfinite(printed) or abs(printed - energy_hartree) > 1e-8:
                    reasons.append("Result energy disagrees with the original PySCF output.")
        elif output_kind == "gaussian_log":
            reasons.append("Gaussian molecular log parsing does not verify periodic cell/k-point input mapping.")
            parsed = parse_log(output)
            step_index = result.get("log_step", 1)
            if (isinstance(step_index, bool) or not isinstance(step_index, int)
                    or not 1 <= step_index <= len(parsed["steps"])):
                reasons.append("A valid Gaussian job step must be selected explicitly.")
            else:
                step = parsed["steps"][step_index - 1]
                if (step["status"] != "normal" or step["scf"]["status"] != "converged"
                        or not step["supported_scope"]):
                    reasons.append("Selected Gaussian step is unsuccessful or outside supported scope.")
                if step["final_scf_energy"] is None or energy_hartree is None or abs(
                    step["final_scf_energy"]["value"] - energy_hartree
                ) > 1e-8:
                    reasons.append("Result energy disagrees with the selected Gaussian SCF energy.")
                for field, parsed_value in (("charge", step["charge"]),
                                            ("multiplicity", step["multiplicity"]),
                                            ("method", step["method"]), ("basis", step["basis"])):
                    if str(conditions[field]).lower() != str(parsed_value).lower():
                        reasons.append(f"Condition {field} disagrees with the Gaussian route/output.")
        else:
            raise ResearchError("output.kind must be pyscf_log or gaussian_log.")
        loaded.append({
            "id": case["id"], "vacuum_angstrom": vacuum, "status": status,
            "eligible": not reasons, "comparable": comparable, "exclusion_reasons": reasons,
            "energy_hartree": energy_hartree,
            "energy_ev_per_atom": (energy_hartree * HARTREE_EV / geometry["atom_count"]
                                   if energy_hartree is not None else None),
            "geometry": geometry, "fixed_conditions": conditions,
            "cif": cif_provenance, "output": output_provenance, "result": result_provenance,
        })
    return {"schema_version": 1, "kind": "loaded_vacuum_convergence_series",
            "name": manifest.get("name", path.stem), "fixed_conditions": fixed,
            "variable": manifest["variable"], "tolerance": tolerance, "cases": loaded,
            "source_cif": source_provenance, "source_geometry": source_geometry,
            "manifest": {"name": path.name, "sha256": sha256(manifest_data).hexdigest(),
                         "size_bytes": len(manifest_data)},
            "limitations": manifest.get("limitations", [])}


def compare_convergence_series(series: str | Path | dict[str, Any]) -> dict[str, Any]:
    """Compare hash-verified samples with the largest successful vacuum.

    Passing a path performs full bundle verification. A dictionary must be a
    result of ``load_convergence_series``; it is not an unchecked raw manifest.
    """
    if isinstance(series, (str, Path)):
        series = load_convergence_series(series)
    if not isinstance(series, dict) or series.get("kind") != "loaded_vacuum_convergence_series":
        raise ResearchError("Load the self-contained series before comparing it.")
    cases = sorted(series["cases"], key=lambda case: case["vacuum_angstrom"])
    eligible = [case for case in cases if case["eligible"]]
    duplicate_vacua = len({case["vacuum_angstrom"] for case in eligible}) != len(eligible)
    incomparable = any(not case["comparable"] for case in cases) or duplicate_vacua
    tolerance = series["tolerance"]["value"]
    minimum = series["tolerance"].get("minimum_successful_cases", 3)
    comparisons = []
    reference = eligible[-1] if eligible else None
    if reference:
        for case in eligible:
            delta = abs(case["energy_ev_per_atom"] - reference["energy_ev_per_atom"]) * 1000
            comparisons.append({"id": case["id"], "vacuum_angstrom": case["vacuum_angstrom"],
                                "reference_id": reference["id"], "delta_mev_per_atom": delta,
                                "within_tolerance": delta <= tolerance})
    recommended = None
    if incomparable:
        status = "incomparable"
        summary = "Conditions or internal geometry differ; this is not a vacuum-only series."
    elif len(eligible) < minimum:
        status = "insufficient_data"
        summary = f"Only {len(eligible)} successful comparable cases; at least {minimum} are required."
    else:
        for index, comparison in enumerate(comparisons[:-1]):
            if all(item["within_tolerance"] for item in comparisons[index:]):
                recommended = comparison["vacuum_angstrom"]
                break
        if recommended is None:
            status = "not_converged"
            summary = "The final two successful vacuum samples do not meet the energy tolerance."
        else:
            status = "accepted"
            summary = (f"Sampled energies from {recommended:g} Å onward meet {tolerance:g} meV/atom "
                       f"against the {reference['vacuum_angstrom']:g} Å reference.")
    warnings = [
        "Acceptance concerns these sampled total energies only; it does not certify density-free vacuum, "
        "forces, band gaps, basis/k-point/grid convergence, or another material/method.",
        "Normal calculation termination is separate from physical accuracy.",
    ]
    if duplicate_vacua:
        warnings.append("Repeated successful vacuum settings cannot establish an independent series.")
    return {
        "schema_version": 1, "kind": "vacuum_convergence", "name": series["name"],
        "status": status, "summary": summary, "fixed_conditions": series["fixed_conditions"],
        "variable": series["variable"], "tolerance_mev_per_atom": tolerance,
        "minimum_successful_cases": minimum, "source_cif": series["source_cif"],
        "manifest": series["manifest"], "cases": cases, "comparisons": comparisons,
        "reference_id": reference["id"] if reference else None,
        "recommended_sampled_vacuum_angstrom": recommended,
        "accepted": [case["id"] for case in eligible
                     if case["vacuum_angstrom"] >= recommended] if status == "accepted" else [],
        "excluded": [case["id"] for case in cases if not case["eligible"]],
        "warnings": warnings, "limitations": series.get("limitations", []),
    }
