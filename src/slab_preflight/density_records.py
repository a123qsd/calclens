"""Immutable density inputs, portable provenance and bounded legacy migration."""

from __future__ import annotations

from copy import deepcopy
from hashlib import sha256
import json
import re

import numpy as np

from .density import MAX_CUBE_BYTES, _plane_geometry, density_difference, parse_cube
from .native_fields import match_cube

RECORD_SCHEMA_VERSION = 2
LEGACY_NORMAL_NOTE = (
    "Legacy record omitted the slab normal. The plane normal is reconstructed from "
    "its recorded Cube axis and voxel basis; its original orientation was not recorded."
)


def structure_for(entry):
    analysis = entry.get("analysis", {}) if isinstance(entry, dict) else {}
    structure = analysis.get("report") or analysis.get("auxiliary_structure")
    if not structure:
        raise ValueError("No validated original P1 structure for the retained electronic data.")
    return structure


def dataset_identity(item, digest, grid=None):
    """Use exact exported/source bytes, keeping a derived-array hash separate."""
    value = {
        "dataset_id": item["id"], "name": item["name"], "filename": item["filename"],
        "structure_sha256": digest, "source_sha256": sha256(item["rawText"].encode()).hexdigest(),
        "kind": item.get("kind"), "units": grid.units if grid is not None else item.get("units"),
        "source": item.get("source", ""),
    }
    if grid is not None:
        value["original_units"] = grid.original_units
    return value


def freeze_difference_inputs(bundle, entry):
    """Capture current supported geometry once; replay never reads current UI normals."""
    report = entry["analysis"].get("report")
    if not report:
        raise ValueError("A supported slab analysis is required for a new difference calculation.")
    saved = deepcopy(bundle)
    saved["schema_version"] = RECORD_SCHEMA_VERSION
    saved["calculation"] = {
        "structure_sha256": entry["sha256"],
        "structure_normal_axis": entry["normal_axis"],
        "normal_vector": list(report["cell"][report["normal_axis_index"]]),
        "grid_plane_axis": bundle["axis"],
        "source_scalar_units": bundle["units"], "output_scalar_units": "e/angstrom^3",
    }
    for item in saved.get("sources", {}).values():
        item["sha256"] = sha256(item["raw"].encode()).hexdigest()
    return saved


def _inputs(bundle, entry):
    if not isinstance(bundle, dict) or type(bundle.get("schema_version", 1)) is not int:
        raise ValueError("Invalid density-difference record.")
    version = bundle.get("schema_version", 1)
    if version not in (1, RECORD_SCHEMA_VERSION):
        raise ValueError("Unsupported density-difference record version.")
    if not isinstance(bundle.get("sources"), dict) or set(bundle["sources"]) != {"AB", "A", "B"}:
        raise ValueError("Missing density-difference originals.")
    if type(bundle.get("axis")) is not int or bundle["axis"] not in (0, 1, 2):
        raise ValueError("Invalid retained grid plane axis.")
    grids = []
    for role in ("AB", "A", "B"):
        item = bundle["sources"][role]
        if (not isinstance(item, dict) or not isinstance(item.get("raw"), str)
                or not isinstance(item.get("filename"), str)
                or len(item["raw"].encode()) > MAX_CUBE_BYTES):
            raise ValueError("Invalid retained density-difference source.")
        digest = sha256(item["raw"].encode()).hexdigest()
        if (version == RECORD_SCHEMA_VERSION or "sha256" in item) and item.get("sha256") != digest:
            raise ValueError("Retained density-difference source checksum mismatch.")
        grids.append(parse_cube(item["raw"], kind="density", units=bundle.get("units"),
                                source_name=item["filename"]))
    structure = structure_for(entry)
    match_cube(grids[0], structure)
    calculation = bundle.get("calculation")
    if version == RECORD_SCHEMA_VERSION:
        if (not isinstance(calculation, dict)
                or calculation.get("structure_sha256") != entry["sha256"]
                or calculation.get("structure_normal_axis") not in ("a", "b", "c", None)
                or type(calculation.get("grid_plane_axis")) is not int
                or calculation.get("grid_plane_axis") != bundle["axis"]
                or calculation.get("source_scalar_units") != bundle["units"]
                or calculation.get("output_scalar_units") != "e/angstrom^3"):
            raise ValueError("Retained calculation identity or conditions are inconsistent.")
        axis = calculation["structure_normal_axis"]
        if axis is None:
            if calculation.get("migration_note") != LEGACY_NORMAL_NOTE:
                raise ValueError("A retained calculation cannot omit its original slab-axis declaration.")
            expected = _plane_geometry(grids[0], bundle["axis"], None)["normal"]
        else:
            if "migration_note" in calculation or "cell" not in structure:
                raise ValueError("Cannot verify the retained slab axis against the original P1 cell.")
            # A named slab axis is the original CIF lattice vector, independent of
            # whichever normal currently passes geometry screening.
            expected = structure["cell"]["abc".index(axis)]
        normal = np.asarray(calculation.get("normal_vector"), dtype=float)
        if (normal.shape != (3,) or not np.isfinite(normal).all()
                or not np.allclose(normal, expected, atol=1e-10, rtol=1e-10)):
            raise ValueError("Retained slab axis and plane normal disagree with the original geometry.")
        normal = normal.tolist()
    else:
        # Schema 1 omitted the original slab normal. Use only the immutable Cube
        # basis and declare the missing original orientation during migration.
        normal = _plane_geometry(grids[0], bundle["axis"], None)["normal"]
    return grids, normal


def replay_difference(bundle, entry, device="cpu", remote=None):
    grids, normal = _inputs(bundle, entry)
    return density_difference(
        *grids, a_indices=bundle.get("a_indices"), b_indices=bundle.get("b_indices"),
        method=bundle.get("method"), reference_conditions=bundle.get("conditions"),
        frozen_geometry=bundle.get("frozen"), axis=bundle["axis"], normal=normal,
        device=device, remote=remote,
    )


def migrate_difference(bundle, entry, result=None):
    """Keep legacy bytes/declarations; persist the documented missing-normal migration."""
    if bundle.get("schema_version", 1) == RECORD_SCHEMA_VERSION:
        return deepcopy(bundle)
    result = result or replay_difference(bundle, entry)
    migrated = deepcopy(bundle)
    migrated["schema_version"] = RECORD_SCHEMA_VERSION
    migrated["calculation"] = {
        "structure_sha256": entry["sha256"], "structure_normal_axis": None,
        "normal_vector": result.profile["normal_unit_vector"],
        "grid_plane_axis": bundle["axis"], "source_scalar_units": bundle["units"],
        "output_scalar_units": "e/angstrom^3", "migration_note": LEGACY_NORMAL_NOTE,
    }
    for item in migrated["sources"].values():
        item["sha256"] = sha256(item["raw"].encode()).hexdigest()
    migrated["computation"] = result.to_dict()
    migrated["computation"]["execution_origin"] = (
        "CPU replay during legacy migration; original execution device and timing were not retained."
    )
    return migrated


def calculation_record(bundle, item, entry, result=None):
    """Return a self-identifying record tied to the retained inputs and result Cube."""
    bundle = migrate_difference(bundle, entry, result)
    computation = deepcopy(bundle.get("computation"))
    if not isinstance(computation, dict):
        raise ValueError("Missing retained calculation result record.")
    computation["schema_version"] = 1
    computation["operation"] = "rho_AB-rho_A-rho_B"
    computation["calculation"] = deepcopy(bundle["calculation"])
    computation["dataset"] = dataset_identity(item, entry["sha256"])
    computation["dataset"]["units"] = "e/angstrom^3"
    return computation


def validate_computation(bundle, replay, field=None):
    """Check stored results against CPU replay without rewriting historical execution."""
    if bundle.get("schema_version", 1) == 1:
        return
    saved = bundle.get("computation")
    if (not isinstance(saved, dict) or type(saved.get("schema_version")) is not int
            or saved["schema_version"] != 1):
        raise ValueError("Missing or unsupported retained computation schema.")
    execution = saved.get("execution")
    if (not isinstance(execution, dict) or execution.get("effective_device") not in
            ("cpu", "metal", "cuda", "remote") or execution.get("precision") not in
            ("float32", "float64")
            or execution.get("includes_cpu_parity_check") is not True
            or not isinstance(execution.get("parity"), dict)
            or execution["parity"].get("passed") is not True):
        raise ValueError("Invalid retained device or CPU verification record.")
    if saved.get("provenance") != replay.provenance:
        raise ValueError("Retained calculation provenance differs from its original inputs.")
    grid = saved.get("grid")
    if not isinstance(grid, dict):
        raise ValueError("Missing retained calculation grid.")
    expected_grid = replay.grid.metadata()
    for key in ("shape", "origin_angstrom", "voxel_vectors_angstrom", "atom_numbers",
                "atom_positions_angstrom", "kind", "units", "original_units",
                "atom_record_charges", "source_name"):
        if grid.get(key) != expected_grid[key]:
            raise ValueError("Retained computation grid differs from the original inputs.")
    digest = grid.get("source_sha256")
    if not isinstance(digest, str) or not re.fullmatch("[0-9a-f]{64}", digest):
        raise ValueError("Missing retained derived-array SHA-256.")
    migrated = bundle.get("calculation", {}).get("migration_note") == LEGACY_NORMAL_NOTE
    if field is not None and not migrated:
        expected_digest = sha256(json.dumps(saved["provenance"], sort_keys=True).encode()
                                 + np.asarray(field.values, dtype="<f8").tobytes()).hexdigest()
        if digest != expected_digest:
            raise ValueError("Retained computation identity differs from the actual result Cube.")
    elif (migrated or execution["effective_device"] == "cpu") and digest != replay.grid.source_sha256:
        raise ValueError("Retained CPU computation identity differs from replay.")
    profile = saved.get("profile")
    if not isinstance(profile, dict) or profile.get("execution") != execution:
        raise ValueError("Invalid retained plane-average execution record.")
    for key in ("field_kind", "axis", "units", "normal_unit_vector", "quadrature", "limitations"):
        if profile.get(key) != replay.profile[key]:
            raise ValueError("Retained profile conditions differ from the original calculation.")
    for key in ("positions_angstrom", "average_e_per_angstrom3", "line_density_e_per_angstrom",
                "plane_area_angstrom2", "plane_step_angstrom", "integral_e"):
        try:
            value = np.asarray(profile[key], dtype=float)
            expected = np.asarray(replay.profile[key], dtype=float)
        except (KeyError, TypeError, ValueError) as error:
            raise ValueError("Invalid retained profile values.") from error
        if value.shape != expected.shape or not np.allclose(
                value, expected, rtol=2e-5, atol=2e-6 * max(1, float(np.max(np.abs(expected))))):
            raise ValueError("Retained profile values differ from CPU replay.")


def binding_digest(value):
    return sha256(json.dumps(value, sort_keys=True, ensure_ascii=False).encode()).hexdigest()
