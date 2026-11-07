"""Read the first VASP CHGCAR density on its original periodic FFT mesh."""
from __future__ import annotations

from hashlib import sha256
from io import StringIO
import math

import numpy as np
from ase.data import atomic_numbers

from .density import CubeGrid, DensityError, MAX_CUBE_BYTES, MAX_GRID_POINTS
from .native_fields import match_cube


def parse_chgcar(raw: bytes, structure, filename: str) -> CubeGrid:
    """Bind the VASP 5/6 cell and indexed sites to the CIF, allowing rigid rotation."""
    from ase.io.vasp import read_vasp_configuration

    if not isinstance(raw, bytes) or not 0 < len(raw) <= MAX_CUBE_BYTES:
        raise DensityError("A CHGCAR source must be at most 32 MiB.")
    source = StringIO(raw.decode("utf-8-sig"))
    header = [source.readline() for _ in range(7)]
    species = header[5].split()
    counts = header[6].partition("!")[0].split()
    if (not species or any(atomic_numbers.get(s.split("/")[0].split("_")[0], 0) < 1 for s in species)
            or len(counts) != len(species) or not all(n.isascii() and n.isdecimal() for n in counts)
            or not 1 <= sum(map(int, counts)) <= 400):
        raise DensityError("CHGCAR needs explicit VASP 5/6 element names and counts for 1–400 atoms.")
    coordinates = source.readline().strip().lower()
    if coordinates.startswith("s"):
        coordinates = source.readline().strip().lower()
    if coordinates[:1] not in {"d", "c", "k"}:
        raise DensityError("CHGCAR needs Direct or Cartesian ion coordinates.")
    source.seek(0)
    try:
        atoms = read_vasp_configuration(source)
    except (ValueError, IndexError, KeyError, RuntimeError, np.linalg.LinAlgError) as exc:
        raise DensityError("Invalid lattice or ion coordinates in the CHGCAR header.") from exc
    cell = np.asarray(atoms.cell)
    target = np.asarray(structure["cell"], dtype=float)
    if not np.isfinite(cell).all() or np.linalg.cond(cell) > 1e6:
        raise DensityError("CHGCAR cell is degenerate or too ill-conditioned.")
    # The CIF reader chooses a Cartesian orientation. Align the ordered lattice
    # vectors by a proper rigid rotation without rescaling the source field.
    u, _, vt = np.linalg.svd(cell.T @ target)
    rotation = u @ vt
    aligned = cell @ rotation
    if np.linalg.det(rotation) < 0 or not np.allclose(aligned, target, atol=2e-4, rtol=1e-6):
        raise DensityError("CHGCAR lattice vectors do not match the selected CIF cell.")
    sites = atoms.positions @ rotation
    cif_sites = np.asarray(structure["positions"])
    if sites.shape != cif_sites.shape or atoms.get_chemical_symbols() != list(structure["elements"]):
        raise DensityError("CHGCAR atom count, order or elements differ from the selected CIF.")
    images = np.rint(np.linalg.solve(aligned.T, (sites - cif_sites).T).T)
    sites = sites - images @ aligned

    dims = next((line.split() for line in source if line.strip()), [])
    if len(dims) != 3 or not all(n.isascii() and n.isdecimal() for n in dims):
        raise DensityError("Missing CHGCAR FFT grid dimensions.")
    shape = tuple(map(int, dims))
    count = math.prod(shape)
    if min(shape) < 2 or count > MAX_GRID_POINTS:
        raise DensityError("CHGCAR needs 2 or more samples per axis and at most 1,000,000 grid points.")
    values = np.empty(count)
    filled = 0
    for line in source:
        if line.lstrip().lower().startswith("augmentation"):
            raise DensityError("The first CHGCAR density block is incomplete before PAW occupancies.")
        tokens = line.replace("D", "E").replace("d", "e").split()
        if filled + len(tokens) > count:
            raise DensityError("Excess values on the final line of the CHGCAR density block.")
        try:
            values[filled:filled + len(tokens)] = tokens
        except ValueError as exc:
            raise DensityError("Invalid number or incomplete first CHGCAR density block.") from exc
        filled += len(tokens)
        if filled == count:
            break  # PAW occupancies and optional magnetization follow the first block.
    if filled != count or not np.isfinite(values).all():
        raise DensityError("The first CHGCAR density block is incomplete or non-finite.")
    if np.any(values < 0):
        raise DensityError("This reader supports nonnegative total-density grids. The CHGCAR contains negative samples.")
    # NX varies fastest. Integrating the normalized field returns mean(raw).
    values /= abs(np.linalg.det(cell))
    grid = CubeGrid(values.reshape(shape, order="F"), np.zeros(3), aligned / np.array(shape)[:, None],
                    tuple(atoms.numbers), sites, "density", "e/angstrom^3", "CHGCAR density × cell volume",
                    sha256(raw).hexdigest(), filename)
    match_cube(grid, structure)
    return grid
