"""Validate attached electronic sources and build bounded Cartesian display meshes."""

from __future__ import annotations

from hashlib import sha256
import json
import math
from pathlib import Path

import numpy as np
from ase.data import atomic_numbers

from .density import CubeGrid

MAX_CHARGE_BYTES = 1024 * 1024
MAX_MESH_FACES = 30_000
KINDS = ("partial_charge", "formal_charge", "ionic_charge", "oxidation_state")


def bounded_read(path: Path, limit: int) -> bytes:
    path = Path(path)
    if not path.is_file():
        raise ValueError("Choose a regular data file.")
    with path.open("rb") as stream:
        data = stream.read(limit + 1)
    if not 0 < len(data) <= limit:
        raise ValueError(f"{path.name} must contain between 1 and {limit:,} bytes.")
    return data


def _unique(pairs):
    values = {}
    for key, value in pairs:
        if key in values:
            raise ValueError(f"Duplicate JSON key: {key}")
        values[key] = value
    return values


def _number(token):
    value = float(token)
    if not math.isfinite(value) or (
        value == 0 and any(c in "123456789" for c in token.lower().split("e")[0])
    ):
        raise ValueError("Numeric value is outside supported precision.")
    return value


def parse_charge(data: bytes, structure, digest: str):
    if not 1 <= len(data) <= MAX_CHARGE_BYTES:
        raise ValueError("Charge JSON exceeds 1 MiB or is empty.")
    obj = json.loads(
        data.decode("utf-8-sig"),
        object_pairs_hook=_unique,
        parse_float=_number,
        parse_constant=_number,
    )
    if (
        not isinstance(obj, dict)
        or type(obj.get("schema_version")) is not int
        or obj["schema_version"] != 1
        or obj.get("kind") not in KINDS
        or not isinstance(obj.get("structure_sha256"), str)
        or obj["structure_sha256"].lower() != digest.lower()
    ):
        raise ValueError("Invalid charge schema, quantity, or original CIF SHA-256.")
    for key in ("method", "source"):
        if not isinstance(obj.get(key), str) or not obj[key].strip() or len(obj[key]) > 500:
            raise ValueError(f"Charge {key} must contain 1–500 characters.")
    count = structure["atom_count"]
    atoms = obj.get("atoms")
    if not isinstance(atoms, list) or len(atoms) != count:
        raise ValueError("Charge records must describe every original atom.")
    seen = set()
    values = [None] * count
    for atom in atoms:
        idx = atom.get("index") if isinstance(atom, dict) else None
        if type(idx) is not int or not 1 <= idx <= count or idx in seen or "value" not in atom:
            raise ValueError("Each original one-based atom index must occur exactly once.")
        seen.add(idx)
        if atom.get("element") != structure["elements"][idx - 1]:
            raise ValueError(f"Element does not match the original CIF at atom {idx}.")
        val = atom["value"]
        if val is not None:
            if (
                type(val) not in (int, float)
                or abs(val) > np.finfo(np.float32).max
                or not math.isfinite(val)
                or (
                    obj["kind"] in ("formal_charge", "ionic_charge") and not float(val).is_integer()
                )
            ):
                raise ValueError("Invalid charge value or non-integral formal/ionic charge.")
            values[idx - 1] = float(val)
    return values, {
        "kind": obj["kind"],
        "method": obj["method"],
        "source": obj["source"],
        "units": "dimensionless" if obj["kind"] == "oxidation_state" else "e",
        "file_sha256": sha256(data).hexdigest(),
    }


def match_cube(grid: CubeGrid, structure):
    numbers = tuple(atomic_numbers[s] for s in structure["elements"])
    xyz = np.asarray(structure["positions"], dtype=float)
    if (
        grid.atom_numbers != numbers
        or xyz.shape != grid.atom_positions_angstrom.shape
        or np.any(np.linalg.norm(xyz - grid.atom_positions_angstrom, axis=1) > 0.01)
    ):
        raise ValueError(
            "Cube atom order, elements, or Cartesian coordinates differ from the CIF (0.01 Å tolerance)."
        )


# Six tetrahedra share a body diagonal. Adjacent voxels triangulate a common face identically.
_CORNERS = np.array(
    ((0, 0, 0), (1, 0, 0), (1, 1, 0), (0, 1, 0), (0, 0, 1), (1, 0, 1), (1, 1, 1), (0, 1, 1))
)
_TETS = ((0, 5, 1, 6), (0, 1, 2, 6), (0, 2, 3, 6), (0, 3, 7, 6), (0, 7, 4, 6), (0, 4, 5, 6))


def isosurfaces(grid: CubeGrid, magnitude: float, opacity: float = 0.45):
    if (
        not math.isfinite(magnitude)
        or magnitude <= 0
        or not math.isfinite(opacity)
        or not 0 <= opacity <= 1
    ):
        raise ValueError("Choose a positive finite isovalue and opacity in [0, 1].")
    values = grid.values
    hi, lo = (
        np.full(tuple(n - 1 for n in grid.shape), -np.inf),
        np.full(tuple(n - 1 for n in grid.shape), np.inf),
    )
    for a, b, c in _CORNERS:
        part = values[a : a + hi.shape[0], b : b + hi.shape[1], c : c + hi.shape[2]]
        np.maximum(hi, part, out=hi)
        np.minimum(lo, part, out=lo)
    surfaces = []
    total_faces = 0
    levels = [magnitude] if grid.kind == "density" else [magnitude, -magnitude]
    for level in levels:
        crossing = np.argwhere((hi >= level) & (lo < level))
        if len(crossing) > 25_000:
            raise ValueError(
                "Isosurface exceeds the native display budget. Choose a larger isovalue."
            )
        if not len(crossing):
            continue
        corners = crossing[:, None, :] + _CORNERS
        scalar = values[tuple(corners.transpose(2, 0, 1))]
        triangles = []
        for tet in _TETS:
            xyz = corners[:, tet, :]
            s = scalar[:, tet]
            codes = (s >= level) @ np.array([1, 2, 4, 8])
            for code in range(1, 15):
                which = np.flatnonzero(codes == code)
                if not len(which):
                    continue
                inside = [i for i in range(4) if code & (1 << i)]
                outside = [i for i in range(4) if i not in inside]
                if len(inside) == 3:
                    inside, outside = outside, inside

                def points(i, j):
                    frac = ((level - s[which, i]) / (s[which, j] - s[which, i]))[:, None]
                    return xyz[which, i] + frac * (xyz[which, j] - xyz[which, i])

                if len(inside) == 1:
                    pieces = [np.stack([points(inside[0], j) for j in outside], axis=1)]
                else:
                    a, b = inside
                    c, d = outside
                    ac, ad, bc, bd = points(a, c), points(a, d), points(b, c), points(b, d)
                    pieces = [np.stack((ac, ad, bd), axis=1), np.stack((ac, bd, bc), axis=1)]
                for tris in pieces:
                    area = np.linalg.norm(
                        np.cross(tris[:, 1] - tris[:, 0], tris[:, 2] - tris[:, 0]), axis=1
                    )
                    tris = tris[area > 0]
                    if len(tris):
                        total_faces += len(tris)
                        if total_faces > MAX_MESH_FACES:
                            raise ValueError(
                                "Isosurface exceeds 30,000 display triangles. Choose a different isovalue."
                            )
                        triangles.append(tris)
        if triangles:
            vertices = (
                np.concatenate(triangles).reshape(-1, 3) @ grid.voxel_vectors_angstrom
                + grid.origin_angstrom
            )
            color = "#4d9db0" if grid.kind == "density" else "#8064ad" if level > 0 else "#1eaa9a"
            surfaces.append(
                {
                    "vertices": vertices,
                    "faces": np.arange(len(vertices)).reshape(-1, 3),
                    "opacity": opacity,
                    "color": color,
                    "label": f"{level:+.6g} {grid.units}",
                }
            )
    if not surfaces:
        raise ValueError("This level does not cross the supplied scalar grid.")
    return surfaces
