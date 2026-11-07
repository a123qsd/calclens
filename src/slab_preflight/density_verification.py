"""Auditable CPU replays of retained density post-processing, never a new SCF run."""

from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timezone
from hashlib import sha256
import platform
from typing import Any

import ase
import numpy as np

from . import __version__
from .density import parse_cube, planar_average
from .density_records import (
    binding_digest, calculation_record, dataset_identity, replay_difference, structure_for,
    validate_computation,
)
from .native_fields import match_cube

RELATIVE_TOLERANCE = 2e-5
ABSOLUTE_SCALE_TOLERANCE = 2e-6
ALGORITHM = "calclens-density-voxel-rectangle-v1"


def runtime_identity() -> dict[str, str]:
    return {"calclens": __version__, "numpy": np.__version__, "ase": ase.__version__,
            "python": platform.python_version()}


def _manifest(record: dict[str, Any]) -> dict[str, Any]:
    return {
        "schema_version": 1, "postprocessing_algorithm": ALGORITHM,
        "operation": record.get("operation"), "dataset": deepcopy(record.get("dataset")),
        "calculation": deepcopy(record.get("calculation")),
        "original_input_provenance": deepcopy(record.get("provenance")),
        "result_grid_identity": deepcopy(record.get("grid")),
        "profile_sha256": binding_digest(record.get("profile")),
    }


def with_reproducibility(record: dict[str, Any]) -> dict[str, Any]:
    """Bind exact inputs, declared settings and retained results for an export.

    Export-runtime identity is explicitly distinct from historical execution.
    This checksum detects inconsistency; it is not a signature or an assertion
    that an external calculation used its user-declared settings.
    """
    result = deepcopy(record)
    manifest = _manifest(result)
    result["reproducibility"] = {
        "schema_version": 1, "manifest": manifest,
        "manifest_sha256": binding_digest(manifest), "record_export_runtime": runtime_identity(),
        "scope": "Retained input bytes, captured settings and density post-processing only; no external electronic-structure calculation is rerun.",
    }
    return result


def _verify_manifest(record: dict[str, Any]) -> None:
    if "reproducibility" not in record:
        return
    retained = record["reproducibility"]
    expected = _manifest(record)
    if (not isinstance(retained, dict) or type(retained.get("schema_version")) is not int
            or retained.get("schema_version") != 1
            or retained.get("manifest") != expected
            or retained.get("manifest_sha256") != binding_digest(expected)):
        raise ValueError("Calculation reproducibility manifest checksum or contents differ from the retained record.")


def _compare(actual: Any, expected: Any, label: str) -> float:
    try:
        value, reference = np.asarray(actual, dtype=float), np.asarray(expected, dtype=float)
    except (TypeError, ValueError) as error:
        raise ValueError(f"Invalid retained {label}.") from error
    if (value.shape != reference.shape or not np.isfinite(value).all()
            or not np.allclose(value, reference, rtol=RELATIVE_TOLERANCE,
                               atol=ABSOLUTE_SCALE_TOLERANCE
                               * max(1, float(np.max(np.abs(reference)))))):
        raise ValueError(f"Retained {label} differs from CPU replay.")
    return float(np.max(np.abs(value - reference)))


def _profile_errors(saved: dict[str, Any], replay: dict[str, Any]) -> dict[str, float]:
    if not isinstance(saved, dict):
        raise ValueError("Missing retained density profile.")
    if type(saved.get("axis")) is not int:
        raise ValueError("Invalid retained profile axis.")
    for key in ("field_kind", "axis", "units", "normal_unit_vector", "quadrature", "limitations"):
        if saved.get(key) != replay[key]:
            raise ValueError("Retained profile conditions differ from CPU replay.")
    errors = {key: _compare(saved.get(key), replay[key], key) for key in (
        "positions_angstrom", "average_e_per_angstrom3", "line_density_e_per_angstrom",
        "plane_area_angstrom2", "plane_step_angstrom", "integral_e",
    )}
    if "integration" in saved:
        if not isinstance(saved["integration"], dict) or set(saved["integration"]) != set(replay["integration"]):
            raise ValueError("Invalid retained integration fields.")
        for key, value in replay["integration"].items():
            actual = saved["integration"][key]
            if isinstance(value, (str, int)):
                if type(actual) is not type(value) or actual != value:
                    raise ValueError("Retained integration convention differs from CPU replay.")
            else:
                errors["integration." + key] = _compare(actual, value, key)
    return errors


def _check_dataset(record, item, entry, grid=None):
    if record.get("dataset") != dataset_identity(item, entry["sha256"], grid):
        raise ValueError("Retained dataset identity or exact source-byte SHA-256 differs from the selected source.")


def _report(record, replay_profile, errors, *, original_sources, warnings=(), grid_error=None,
            integrity_history=None):
    identified = with_reproducibility(record)
    result = {
        "schema_version": 1, "status": "passed", "operation": record["operation"],
        "verified_at_utc": datetime.now(timezone.utc).isoformat(),
        "verification_runtime": runtime_identity(),
        "source_identity_and_checksums": original_sources,
        "result_dataset_identity": deepcopy(record["dataset"]),
        "structure_sha256": record["dataset"]["structure_sha256"],
        "captured_settings": deepcopy(record["calculation"]),
        "declared_electronic_settings": {key: deepcopy(value)
                                         for key, value in record.get("provenance", {}).items()
                                         if key in ("common_method_declared", "common_reference_conditions_declared",
                                                    "frozen_geometry_confirmed", "a_indices_one_based",
                                                    "b_indices_one_based", "declaration_limit")},
        "record_manifest_sha256": identified["reproducibility"]["manifest_sha256"],
        "checks": ["Exact retained source-byte SHA-256 and source identity",
                   "Original structure and captured grid/normal/settings",
                   "CPU float64 replay of retained density post-processing",
                   "Retained profile and optional cumulative/voxel integrals"],
        "comparison": {
            "relative_tolerance": RELATIVE_TOLERANCE,
            "absolute_tolerance": "2e-6 * max(1, max(abs(reference quantity)))",
            "maximum_absolute_errors": errors,
        },
        "cpu_replay_execution": deepcopy(replay_profile["execution"]),
        "cpu_replay_integral_e": replay_profile["integral_e"],
        "cpu_replay_integration": deepcopy(replay_profile["integration"]),
        "warnings": list(warnings),
        "limits": ["Verification checks retained bytes and declared settings, not their authenticity.",
                   "External electronic-structure calculations, method equivalence and convergence are not independently rerun or proven.",
                   "Electron-density integrals are not a unique atom-partitioned charge transfer."],
    }
    if grid_error is not None:
        result["comparison"]["maximum_absolute_grid_error_e_per_angstrom3"] = grid_error
    if integrity_history is not None:
        result["checksum_history"] = integrity_history
    return result


def verify_planar_record(record, item, entry):
    """Reparse the exact retained field and replay its captured average on CPU."""
    if (type(record.get("schema_version")) is not int or record.get("schema_version") != 1
            or record.get("operation") != "planar_average"):
        raise ValueError("A supported retained planar-average record is required.")
    _verify_manifest(record)
    # Use the same declared-format dispatcher as normal imports, including fields
    # whose native format carries its own scalar normalization.
    from .desktop_sources import evaluate_source
    structure = structure_for(entry)
    grid = evaluate_source(item, "volume", structure, entry["sha256"])
    _check_dataset(record, item, entry, grid)
    if record.get("grid") != grid.metadata():
        raise ValueError("Retained grid metadata differs from the original field.")
    calculation = record.get("calculation", {})
    axis = calculation.get("grid_plane_axis")
    structure_axis = calculation.get("structure_normal_axis")
    normal = calculation.get("normal_vector")
    if (calculation.get("structure_sha256") != entry["sha256"]
            or type(axis) is not int or axis not in (0, 1, 2)
            or structure_axis not in ("a", "b", "c")
            or calculation.get("source_scalar_units") != grid.original_units
            or calculation.get("output_scalar_units") != grid.units):
        raise ValueError("Retained calculation settings do not identify the original density calculation.")
    try:
        original_normal = np.asarray(normal, dtype=float)
    except (TypeError, ValueError) as error:
        raise ValueError("Invalid retained original slab normal.") from error
    if (original_normal.shape != (3,) or not np.isfinite(original_normal).all()
            or not np.allclose(original_normal, structure["cell"]["abc".index(structure_axis)],
                               atol=1e-10, rtol=1e-10)):
        raise ValueError("Retained slab normal differs from the original structure axis.")
    replay = planar_average(grid, axis=axis, normal=normal, device="cpu")
    if record.get("execution") != record.get("profile", {}).get("execution"):
        raise ValueError("Retained historical execution records disagree.")
    errors = _profile_errors(record.get("profile"), replay)
    return _report(record, replay, errors,
                   original_sources=[{"role": "field", **dataset_identity(item, entry["sha256"], grid)}])


def verify_retained_difference(bundle, item, entry, record=None):
    """Check sources, captured settings, stored result and profile against CPU replay."""
    replay = replay_difference(bundle, entry, device="cpu")
    if bundle.get("result_id") != item.get("id"):
        raise ValueError("Retained result dataset identity differs from the selected source.")
    digest = sha256(item["rawText"].encode()).hexdigest()
    if "result_sha256" in bundle and bundle["result_sha256"] != digest:
        raise ValueError("Retained difference result-byte SHA-256 checksum mismatch.")
    field = parse_cube(item["rawText"], kind=item.get("kind"), units=item.get("units"),
                       source_name=item["filename"])
    match_cube(field, structure_for(entry))
    if field.kind != "difference_density":
        raise ValueError("Retained difference must identify a signed density-difference field.")
    for name in ("origin_angstrom", "voxel_vectors_angstrom"):
        _compare(getattr(field, name), getattr(replay.grid, name), name)
    grid_error = _compare(field.values, replay.grid.values, "density-difference grid")
    validate_computation(bundle, replay, field)
    expected_record = calculation_record(bundle, item, entry, replay)
    if record is not None:
        _verify_manifest(record)
        if {k: v for k, v in record.items() if k != "reproducibility"} != expected_record:
            raise ValueError("Current calculation record differs from its retained originals.")
    else:
        record = expected_record
    errors = _profile_errors(record["profile"], replay.profile)
    warnings = []
    if bundle.get("schema_version", 1) == 1:
        warnings.append("Legacy archive: original source checksums, execution and slab-normal orientation were not recorded. Current hashes identify the retained bytes; the documented migrated CPU replay is checked against the retained result.")
    return _report(record, replay.profile, errors, grid_error=grid_error, warnings=warnings,
                   integrity_history={
                       "original_input_sha256_recorded": all("sha256" in source for source in bundle["sources"].values()),
                       "result_source_sha256_recorded": "result_sha256" in bundle,
                   },
                   original_sources=[{"role": role, "filename": source["source_name"],
                                      "source_sha256": source["source_sha256"],
                                      "original_scalar_units": source["original_units"],
                                      "normalized_scalar_units": source["units"]}
                                     for role, source in zip(("AB", "A", "B"),
                                                             replay.provenance["sources"], strict=True)])
