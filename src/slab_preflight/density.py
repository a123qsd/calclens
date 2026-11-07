"""Explicit external Cube fields, frozen-geometry differences and plane averages.

This module performs post-processing only. It never runs an electronic-structure
calculation, registers mismatched grids, or interprets orbital amplitudes as density.
"""
from __future__ import annotations

from dataclasses import dataclass
from hashlib import sha256
import json
import math
import re
from typing import Any, Sequence

import numpy as np

BOHR_ANGSTROM = 0.529177210903
MAX_CUBE_BYTES = 32 * 1024 * 1024
MAX_GRID_POINTS = 1_000_000
GRID_TOLERANCE_ANGSTROM = 1e-8
FROZEN_POSITION_TOLERANCE_ANGSTROM = 1e-6
_NUMBER = re.compile(r"^[+-]?(?:\d+(?:\.\d*)?|\.\d+)(?:[eEdD][+-]?\d+)?$")
_INTEGER = re.compile(r"^[+-]?\d+$")
_DENSITY_KINDS = {"density", "difference_density", "spin_density"}


class DensityError(ValueError):
    """An external field does not satisfy the declared scientific contract."""


@dataclass(frozen=True)
class CubeGrid:
    values: np.ndarray
    origin_angstrom: np.ndarray
    voxel_vectors_angstrom: np.ndarray
    atom_numbers: tuple[int, ...]
    atom_positions_angstrom: np.ndarray
    kind: str
    units: str
    original_units: str
    source_sha256: str
    source_name: str
    atom_record_charges: tuple[float, ...] | None = None

    def __post_init__(self) -> None:
        arrays = {"values": np.array(self.values, dtype=np.float64, copy=True),
                  "origin_angstrom": np.array(self.origin_angstrom, dtype=np.float64, copy=True),
                  "voxel_vectors_angstrom": np.array(self.voxel_vectors_angstrom, dtype=np.float64, copy=True),
                  "atom_positions_angstrom": np.array(self.atom_positions_angstrom, dtype=np.float64, copy=True)}
        if (arrays["values"].ndim != 3 or min(arrays["values"].shape) < 2
                or arrays["values"].size > MAX_GRID_POINTS
                or arrays["origin_angstrom"].shape != (3,)
                or arrays["voxel_vectors_angstrom"].shape != (3, 3)
                or arrays["atom_positions_angstrom"].shape != (len(self.atom_numbers), 3)
                or len(self.atom_numbers) > 400
                or any(not np.isfinite(array).all() for array in arrays.values())):
            raise DensityError("CubeGrid arrays have invalid dimensions, size or non-finite values.")
        if (self.kind not in _DENSITY_KINDS | {"orbital"}
                or (self.kind in _DENSITY_KINDS and self.units != "e/angstrom^3")
                or (self.kind == "orbital" and self.units not in {"arbitrary", "angstrom^-3/2"})
                or (self.kind == "density" and np.any(arrays["values"] < 0))):
            raise DensityError("CubeGrid field kind, normalized units or density sign is invalid.")
        if any(isinstance(value, bool) or not isinstance(value, (int, np.integer))
               or not 1 <= value <= 118 for value in self.atom_numbers):
            raise DensityError("CubeGrid requires standard atomic numbers 1–118.")
        if np.linalg.cond(arrays["voxel_vectors_angstrom"]) > 1e6:
            raise DensityError("CubeGrid voxel basis is degenerate or too ill-conditioned.")
        if any(array.size and np.max(np.abs(array)) > 1e6 for name, array in arrays.items()
               if name != "values"):
            raise DensityError("CubeGrid spatial coordinates must stay within ±1,000,000 Å.")
        extents = arrays["voxel_vectors_angstrom"] * (np.array(arrays["values"].shape) - 1)[:, None]
        origin = arrays["origin_angstrom"]
        if np.any(origin + np.minimum(extents, 0).sum(axis=0) < -1e6) or np.any(
                origin + np.maximum(extents, 0).sum(axis=0) > 1e6):
            raise DensityError("CubeGrid extent exceeds ±1,000,000 Å.")
        if not isinstance(self.source_sha256, str) or not re.fullmatch("[0-9a-f]{64}", self.source_sha256):
            raise DensityError("CubeGrid requires its exact source SHA-256 (or an identified derived hash).")
        if self.atom_record_charges is not None:
            charges = tuple(float(value) for value in self.atom_record_charges)
            if len(charges) != len(self.atom_numbers) or not all(math.isfinite(value) for value in charges):
                raise DensityError("Cube atom-record charges must match the finite original atom records.")
            object.__setattr__(self, "atom_record_charges", charges)
        for name, array in arrays.items():
            array.setflags(write=False)
            object.__setattr__(self, name, array)
        object.__setattr__(self, "atom_numbers", tuple(int(value) for value in self.atom_numbers))

    @property
    def shape(self) -> tuple[int, int, int]:
        return tuple(self.values.shape)

    def metadata(self) -> dict[str, Any]:
        return {
            "shape": list(self.shape), "origin_angstrom": self.origin_angstrom.tolist(),
            "voxel_vectors_angstrom": self.voxel_vectors_angstrom.tolist(),
            "atom_numbers": list(self.atom_numbers),
            "atom_positions_angstrom": self.atom_positions_angstrom.tolist(),
            "kind": self.kind, "units": self.units, "original_units": self.original_units,
            "source_sha256": self.source_sha256, "source_name": self.source_name,
            "atom_record_charges": list(self.atom_record_charges) if self.atom_record_charges is not None else None,
        }


@dataclass(frozen=True)
class DensityComputation:
    grid: CubeGrid
    profile: dict[str, Any]
    execution: dict[str, Any]
    provenance: dict[str, Any]

    def to_dict(self, *, include_values: bool = False) -> dict[str, Any]:
        result = {"schema_version": 1, "grid": self.grid.metadata(), "profile": self.profile,
                  "execution": self.execution, "provenance": self.provenance}
        if include_values:
            result["grid"]["values"] = self.grid.values.ravel().tolist()
        return result


def _number(token: str, label: str) -> float:
    if not _NUMBER.fullmatch(token):
        raise DensityError(f"{label} must be a finite decimal number.")
    value = float(token.replace("D", "e").replace("d", "e"))
    if not math.isfinite(value) or (value == 0 and re.search(r"[1-9]", re.split("[eEdD]", token)[0])):
        raise DensityError(f"{label} overflows or underflows floating-point precision.")
    return value


def _integer(token: str, label: str) -> int:
    if not _INTEGER.fullmatch(token) or len(token) > 12:
        raise DensityError(f"{label} must be a bounded integer.")
    return int(token)


def _readonly(value: Any) -> np.ndarray:
    array = np.asarray(value, dtype=np.float64)
    array.setflags(write=False)
    return array


def parse_cube(data: bytes | str, *, kind: str, units: str,
               source_name: str = "Cube") -> CubeGrid:
    """Parse one explicitly declared scalar field; preserve exact source-byte hash.

    Positive voxel counts mean Bohr coordinates; negative counts mean Å, matching
    CalcLens's existing explicit spatial convention. Density scalars are normalized
    to e/Å³ independently of that spatial convention.
    """
    if kind not in _DENSITY_KINDS | {"orbital"}:
        raise DensityError("Choose density, difference_density, spin_density or orbital explicitly.")
    if not isinstance(source_name, str) or not source_name.strip() or len(source_name) > 500:
        raise DensityError("A source name of 1–500 characters is required.")
    density_units = {"e/bohr^3": 1 / BOHR_ANGSTROM**3, "e/angstrom^3": 1.0}
    orbital_units = {"bohr^-3/2": 1 / BOHR_ANGSTROM**1.5,
                     "angstrom^-3/2": 1.0, "arbitrary": 1.0}
    choices = density_units if kind in _DENSITY_KINDS else orbital_units
    if units not in choices:
        raise DensityError(f"Explicit scalar units for {kind} must be one of {', '.join(choices)}.")
    raw = data.encode("utf-8") if isinstance(data, str) else data
    if not isinstance(raw, bytes) or not 1 <= len(raw) <= MAX_CUBE_BYTES:
        raise DensityError("Each Cube source must contain 1 byte to 32 MiB.")
    try:
        lines = raw.decode("utf-8-sig").splitlines()
    except UnicodeDecodeError as error:
        raise DensityError("Cube source must be UTF-8 text.") from error
    if len(lines) < 7:
        raise DensityError("Cube needs two comments, a grid header and scalar data.")

    def row(index: int, lengths: tuple[int, ...], label: str) -> list[str]:
        tokens = lines[index].split() if index < len(lines) else []
        if len(tokens) not in lengths:
            raise DensityError(f"{label} has missing or extra columns.")
        return tokens

    header = row(2, (4, 5), "Cube origin")
    signed_atoms = _integer(header[0], "Atom count")
    atom_count = abs(signed_atoms)
    if atom_count > 400:
        raise DensityError("Cube supports at most 400 atom records.")
    if len(header) == 5 and _integer(header[4], "Values per voxel") != 1:
        raise DensityError("Exactly one scalar dataset per Cube is supported.")
    axes = [row(index, (4,), "Cube voxel axis") for index in (3, 4, 5)]
    signed_counts = [_integer(axis[0], "Voxel count") for axis in axes]
    if not (all(value > 0 for value in signed_counts)
            or all(value < 0 for value in signed_counts)):
        raise DensityError("Voxel counts must have one sign: positive Bohr or negative Å.")
    shape = tuple(abs(value) for value in signed_counts)
    count = math.prod(shape)
    if min(shape) < 2 or count > MAX_GRID_POINTS:
        raise DensityError("Cube needs at least two points per axis and at most 1,000,000 points.")
    coordinate_factor = BOHR_ANGSTROM if signed_counts[0] > 0 else 1.0
    origin = np.array([_number(value, "Origin") for value in header[1:4]]) * coordinate_factor
    vectors = np.array([[_number(value, "Voxel vector") for value in axis[1:]]
                        for axis in axes]) * coordinate_factor
    if np.linalg.cond(vectors) > 1e6 or abs(np.linalg.det(vectors)) == 0:
        raise DensityError("Cube voxel basis is degenerate or too ill-conditioned.")
    if max(np.max(np.abs(origin)), np.max(np.abs(vectors))) > 1e6:
        raise DensityError("Cube coordinates must stay within ±1,000,000 Å.")
    extents = vectors * (np.array(shape) - 1)[:, None]
    if np.any(origin + np.minimum(extents, 0).sum(axis=0) < -1e6) or np.any(
            origin + np.maximum(extents, 0).sum(axis=0) > 1e6):
        raise DensityError("Cube grid extent exceeds ±1,000,000 Å.")
    numbers: list[int] = []
    positions: list[list[float]] = []
    charges: list[float] = []
    for index in range(atom_count):
        tokens = row(6 + index, (5,), f"Cube atom {index + 1}")
        number = _integer(tokens[0], "Atomic number")
        if not 1 <= number <= 118:
            raise DensityError("Cube atomic numbers must be standard elements 1–118.")
        charge = _number(tokens[1], "Cube atom-record charge")
        position = [_number(value, "Atom coordinate") * coordinate_factor for value in tokens[2:]]
        if max(abs(value) for value in position) > 1e6:
            raise DensityError("Cube atom coordinate exceeds ±1,000,000 Å.")
        numbers.append(number)
        positions.append(position)
        charges.append(charge)
    tokens = " ".join(lines[6 + atom_count:]).split()
    if signed_atoms < 0:
        if len(tokens) < 2 or _integer(tokens[0], "Dataset count") != 1:
            raise DensityError("Multi-dataset Cube files must be exported separately.")
        if _integer(tokens[1], "Dataset identifier") < 0:
            raise DensityError("Cube dataset identifier must be nonnegative.")
        tokens = tokens[2:]
    if len(tokens) != count:
        raise DensityError(f"Cube needs exactly {count} scalar values; found {len(tokens)}.")
    values = np.fromiter((_number(token, "Cube scalar") for token in tokens),
                         dtype=np.float64, count=count)
    if kind == "density" and np.any(values < 0):
        raise DensityError("Total electron density must be nonnegative; choose signed difference/spin explicitly.")
    with np.errstate(over="ignore", under="ignore", invalid="ignore"):
        converted = values * choices[units]
    if not np.isfinite(converted).all() or np.any((values != 0) & (converted == 0)):
        raise DensityError("Scalar unit conversion exceeds floating-point precision.")
    normalized_units = ("e/angstrom^3" if kind in _DENSITY_KINDS else
                        "arbitrary" if units == "arbitrary" else "angstrom^-3/2")
    return CubeGrid(_readonly(converted.reshape(shape)), _readonly(origin), _readonly(vectors),
                    tuple(numbers), _readonly(np.array(positions).reshape((-1, 3))), kind,
                    normalized_units, units, sha256(raw).hexdigest(), source_name.strip(), tuple(charges))


def _plane_geometry(grid: CubeGrid, axis: int, normal: Sequence[float] | None) -> dict[str, Any]:
    if isinstance(axis, bool) or axis not in (0, 1, 2):
        raise DensityError("The plane axis must be 0, 1 or 2.")
    others = [value for value in range(3) if value != axis]
    vectors = grid.voxel_vectors_angstrom
    cross = np.cross(vectors[others[0]], vectors[others[1]])
    unit_normal = cross / np.linalg.norm(cross)
    if np.dot(unit_normal, vectors[axis]) < 0:
        unit_normal = -unit_normal
    if normal is not None:
        chosen = np.asarray(normal, dtype=np.float64)
        if chosen.shape != (3,) or not np.isfinite(chosen).all() or np.max(np.abs(chosen)) == 0:
            raise DensityError("Slab normal must be a finite nonzero three-vector.")
        chosen = chosen / np.max(np.abs(chosen))
        chosen = chosen / np.linalg.norm(chosen)
        if any(abs(np.dot(chosen, vectors[index])) > 1e-8 * np.linalg.norm(vectors[index])
               for index in others):
            raise DensityError("Grid planes are not parallel to the supplied slab plane; resampling is not inferred.")
        unit_normal = chosen
    step = float(np.dot(vectors[axis], unit_normal))
    area = float(np.linalg.norm(cross) * grid.shape[others[0]] * grid.shape[others[1]])
    positions = float(np.dot(grid.origin_angstrom, unit_normal)) + np.arange(grid.shape[axis]) * step
    return {"axis": axis, "normal": unit_normal.tolist(), "positions": positions,
            "step": step, "area": area, "voxel_volume": float(abs(np.linalg.det(vectors)))}


def _profile(grid: CubeGrid, averages: np.ndarray, geometry: dict[str, Any],
             execution: dict[str, Any]) -> dict[str, Any]:
    order = np.argsort(geometry["positions"])
    positions = geometry["positions"][order]
    ordered_averages = averages[order]
    area, step = geometry["area"], abs(geometry["step"])
    # This makes the N-step rectangle-rule domain explicit and keeps it invariant
    # when the normal is reversed: each sampled plane represents a centered slab.
    boundaries = np.concatenate((positions - step / 2, [positions[-1] + step / 2]))
    with np.errstate(over="ignore", invalid="ignore"):
        plane_e = ordered_averages * area * step
        cumulative_e = np.concatenate(([0.0], np.cumsum(plane_e, dtype=np.float64)))
        voxel_volume = geometry["voxel_volume"]
        positive_e = float(np.sum(np.maximum(grid.values, 0), dtype=np.float64) * voxel_volume)
        negative_e = float(np.sum(np.minimum(grid.values, 0), dtype=np.float64) * voxel_volume)
        absolute_e = positive_e - negative_e
        integral_e = float(np.sum(plane_e, dtype=np.float64))
    if not (np.isfinite(plane_e).all() and np.isfinite(cumulative_e).all()
            and all(math.isfinite(value) for value in (positive_e, negative_e, absolute_e, integral_e))):
        raise DensityError("Density integration exceeds floating-point precision.")
    return {
        "field_kind": grid.kind, "axis": geometry["axis"],
        "normal_unit_vector": geometry["normal"],
        "positions_angstrom": positions.tolist(),
        "average_e_per_angstrom3": ordered_averages.tolist(),
        "line_density_e_per_angstrom": (ordered_averages * area).tolist(),
        "plane_area_angstrom2": geometry["area"],
        "plane_step_angstrom": abs(geometry["step"]),
        "integral_e": integral_e,
        "integration": {
            "schema_version": 1,
            "boundary_positions_angstrom": boundaries.tolist(),
            "plane_integral_e": plane_e.tolist(),
            "cumulative_e": cumulative_e.tolist(),
            "positive_voxel_integral_e": positive_e,
            "negative_voxel_integral_e": negative_e,
            "absolute_voxel_integral_e": absolute_e,
            "voxel_volume_angstrom3": voxel_volume,
            "convention": "piecewise-constant centered slabs; cumulative electron count from the lowest projected boundary",
            "positive_negative_scope": "positive and negative parts of the original 3D voxel field, before planar averaging",
            "interpretation": "Signed electron counts, not electric charge or atom-partitioned charge transfer; interval values assume constant density within each sampled slab.",
        },
        "quadrature": "equal-volume voxel rectangle rule; domain spans N voxel steps, not N-1",
        "units": "e/angstrom^3", "execution": execution,
        "limitations": ["External electronic calculations are not rerun or independently validated.",
                        "A density difference is not an atom-partitioned charge transfer.",
                        "No grid interpolation, alignment, relaxation or endpoint correction is inferred."],
    }


def integrate_profile_interval(profile: dict[str, Any], lower_angstrom: float,
                               upper_angstrom: float) -> float:
    """Integrate a closed display interval using the declared centered-slab rule.

    A cut through a slab contributes its fractional width. This is a transparent
    quadrature convention, not an interpolation of unsampled electronic density.
    Bounds outside the sampled domain are rejected rather than extrapolated.
    """
    integration = profile.get("integration", {})
    try:
        edges = np.asarray(integration["boundary_positions_angstrom"], dtype=np.float64)
        counts = np.asarray(integration["plane_integral_e"], dtype=np.float64)
        lower, upper = float(lower_angstrom), float(upper_angstrom)
    except (KeyError, TypeError, ValueError) as error:
        raise DensityError("A supported density integration profile and finite interval are required.") from error
    if (type(integration.get("schema_version")) is not int or integration.get("schema_version") != 1
            or edges.ndim != 1 or counts.ndim != 1
            or len(edges) != len(counts) + 1 or len(counts) < 2
            or not np.isfinite(edges).all() or not np.isfinite(counts).all()
            or np.any(np.diff(edges) <= 0) or not math.isfinite(lower) or not math.isfinite(upper)
            or not edges[0] <= lower <= upper <= edges[-1]):
        raise DensityError("Integration interval must stay within the finite sampled slab boundaries.")
    widths = np.maximum(0, np.minimum(edges[1:], upper) - np.maximum(edges[:-1], lower))
    return float(np.sum(counts * (widths / np.diff(edges)), dtype=np.float64))


def planar_average(grid: CubeGrid, *, axis: int = 2, normal: Sequence[float] | None = None,
                   device: str = "cpu", remote: Any = None) -> dict[str, Any]:
    """Average equal-area samples on grid planes parallel to the declared slab plane."""
    if grid.kind not in _DENSITY_KINDS or grid.units != "e/angstrom^3":
        raise DensityError("Physical density averages require density, difference_density or spin_density, not orbital amplitude.")
    geometry = _plane_geometry(grid, axis, normal)
    from .compute_devices import compute_arrays
    _, averages, execution = compute_arrays([grid.values], axis=axis, device=device, remote=remote)
    result = _profile(grid, averages, geometry, execution)
    result["provenance"] = grid.metadata()
    return result


def density_difference(ab: CubeGrid, a: CubeGrid, b: CubeGrid, *,
                       a_indices: Sequence[int], b_indices: Sequence[int], method: str,
                       reference_conditions: str, frozen_geometry: bool, axis: int = 2,
                       normal: Sequence[float] | None = None, device: str = "cpu",
                       remote: Any = None) -> DensityComputation:
    """Compute rho_AB-rho_A-rho_B only for matching grids and a frozen atom partition."""
    if frozen_geometry is not True:
        raise DensityError("Confirm all fragment calculations use the same frozen AB geometry.")
    for label, value in (("Common calculation method", method),
                         ("Common reference conditions", reference_conditions)):
        if not isinstance(value, str) or not value.strip() or len(value) > 4000:
            raise DensityError(f"{label} must be explicitly declared (1–4000 characters).")
    for grid in (ab, a, b):
        if grid.kind != "density" or grid.units != "e/angstrom^3":
            raise DensityError("AB−A−B requires three total electron densities; orbital/spin/difference fields cannot substitute.")
        if grid.shape != ab.shape or not np.allclose(grid.origin_angstrom, ab.origin_angstrom,
                                                  atol=GRID_TOLERANCE_ANGSTROM, rtol=0):
            raise DensityError("AB, A and B must have identical grid counts and origins.")
        if not np.allclose(grid.voxel_vectors_angstrom, ab.voxel_vectors_angstrom,
                           atol=GRID_TOLERANCE_ANGSTROM, rtol=0):
            raise DensityError("AB, A and B must have the same voxel basis; no registration/resampling is inferred.")
    indices = [list(a_indices), list(b_indices)]
    flattened = indices[0] + indices[1]
    if any(isinstance(value, bool) or not isinstance(value, (int, np.integer)) for value in flattened):
        raise DensityError("Fragment atom indices must be one-based integers.")
    if not all(indices) or sorted(flattened) != list(range(1, len(ab.atom_numbers) + 1)):
        raise DensityError("A and B indices must disjointly partition all AB atoms exactly once.")
    for grid, mapping in zip((a, b), indices, strict=True):
        if len(mapping) != len(grid.atom_numbers):
            raise DensityError("Fragment index count must match its Cube atom count.")
        selected = np.array(mapping) - 1
        if tuple(ab.atom_numbers[index] for index in selected) != grid.atom_numbers:
            raise DensityError("Fragment atom elements/order do not match the explicit AB subset.")
        distances = np.linalg.norm(ab.atom_positions_angstrom[selected]
                                   - grid.atom_positions_angstrom, axis=1)
        if np.any(distances > FROZEN_POSITION_TOLERANCE_ANGSTROM):
            raise DensityError("Fragment nuclei differ from frozen AB positions; relaxed fragments are not accepted.")
    geometry = _plane_geometry(ab, axis, normal)
    from .compute_devices import compute_arrays
    values, averages, execution = compute_arrays([ab.values, a.values, b.values], axis=axis,
                                                device=device, remote=remote)
    provenance = {
        "operation": "rho_AB-rho_A-rho_B", "common_method_declared": method.strip(),
        "common_reference_conditions_declared": reference_conditions.strip(),
        "frozen_geometry_confirmed": True, "a_indices_one_based": indices[0],
        "b_indices_one_based": indices[1], "sources": [grid.metadata() for grid in (ab, a, b)],
        "grid_plane_axis": axis, "normal_unit_vector": geometry["normal"],
        "output_scalar_units": "e/angstrom^3",
        "grid_tolerance_angstrom": GRID_TOLERANCE_ANGSTROM,
        "frozen_position_tolerance_angstrom": FROZEN_POSITION_TOLERANCE_ANGSTROM,
        "declaration_limit": "Matching declarations and nuclei do not prove identical electronic settings or electron reference states.",
    }
    derived_hash = sha256(json.dumps(provenance, sort_keys=True).encode()
                          + np.asarray(values, dtype="<f8").tobytes()).hexdigest()
    grid = CubeGrid(_readonly(values), ab.origin_angstrom, ab.voxel_vectors_angstrom,
                    ab.atom_numbers, ab.atom_positions_angstrom, "difference_density",
                    "e/angstrom^3", "e/angstrom^3", derived_hash, "AB−A−B derived density",
                    ab.atom_record_charges)
    return DensityComputation(grid, _profile(grid, averages, geometry, execution), execution, provenance)


def cube_bytes(grid: CubeGrid, *, metadata: dict[str, Any] | None = None) -> bytes:
    """Export normalized scalar units with explicit Å coordinate convention."""
    if grid.atom_record_charges is None:
        raise DensityError("Cube export requires the original atom-record charges; they are not inferred from elements.")
    identity = f"{grid.kind}; {grid.units}; source {grid.source_sha256}"
    if metadata is not None:
        identity += "; " + json.dumps(metadata, ensure_ascii=False, sort_keys=True, allow_nan=False)
    lines = ["CalcLens derived/exported scalar field", identity,
             " ".join([str(len(grid.atom_numbers)), *(f"{value:.17g}" for value in grid.origin_angstrom)])]
    lines.extend(" ".join([str(-count), *(f"{value:.17g}" for value in vector)])
                 for count, vector in zip(grid.shape, grid.voxel_vectors_angstrom, strict=True))
    lines.extend(" ".join([str(number), f"{charge:.17g}", *(f"{value:.17g}" for value in position)])
                 for number, charge, position in zip(grid.atom_numbers, grid.atom_record_charges,
                                                      grid.atom_positions_angstrom, strict=True))
    flat = grid.values.ravel()
    lines.extend(" ".join(f"{value:.17g}" for value in flat[index:index + 6])
                 for index in range(0, len(flat), 6))
    return ("\n".join(lines) + "\n").encode("utf-8")
