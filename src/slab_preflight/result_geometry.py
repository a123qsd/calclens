"""Source coordinates for result inspection; never manufacture a simulation cell."""
from __future__ import annotations

import re

import numpy as np
from ase.data import chemical_symbols
from ase.formula import Formula

BOHR_ANGSTROM = 0.529177210903  # CODATA 2018; same convention as Cube imports
MAX_RESULT_ATOMS = 100_000
_NUM = r"[-+]?(?:\d+\.?\d*|\.\d+)(?:[DdEe][-+]?\d+)?"


def validate_geometry(value):
    if not isinstance(value, dict) or value.get("units") != "angstrom":
        raise ValueError("Result coordinates require explicit angstrom units.")
    elements = value.get("elements")
    positions = np.asarray(value.get("positions"), dtype=float)
    if (not isinstance(elements, list) or not 0 < len(elements) <= MAX_RESULT_ATOMS
            or any(e not in chemical_symbols[1:] for e in elements)
            or positions.shape != (len(elements), 3) or not np.isfinite(positions).all()
            or np.abs(positions).max() > 1e6):
        raise ValueError("Invalid or unsupported result atom coordinates.")
    pbc = value.get("periodic_axes")
    if (not isinstance(pbc, list) or len(pbc) != 3
            or any(type(flag) is not bool for flag in pbc)):
        raise ValueError("Result periodicity must be explicit.")
    cell = value.get("cell")
    if cell is None:
        if any(pbc):
            raise ValueError("Periodic result coordinates have no source lattice.")
    else:
        matrix = np.asarray(cell, dtype=float)
        if (matrix.shape != (3, 3) or not np.isfinite(matrix).all()
                or np.abs(matrix).max() > 1e6 or abs(np.linalg.det(matrix)) < 1e-10):
            raise ValueError("Result lattice must be finite and nonsingular.")
    return value


def geometry_report(geometry):
    """A viewer report, without CIF slab metrics or a fictional molecular box."""
    validate_geometry(geometry)
    return {
        "formula": str(Formula.from_list(geometry["elements"]).format("hill")),
        "atom_count": len(geometry["elements"]),
        "elements": geometry["elements"], "positions": geometry["positions"],
        "cell": geometry["cell"], "periodic_axes": geometry["periodic_axes"],
        "units": {"length": "angstrom"}, "metrics": {}, "normal_axis": None,
        "geometry_source": geometry.get("source"),
    }


def gaussian_geometries(rows, atom_count):
    """Read complete printed orientation tables, retaining one-based lines/centres.

    Dummy/ghost atoms and translation-vector pseudoatoms are deliberately not
    converted into real nuclei. An incomplete final table invalidates the final
    geometry rather than silently presenting an older frame as the last one.
    """
    frames, warnings = [], []
    last_table_complete = True
    for offset, (line_number, line) in enumerate(rows):
        kind = re.search(r"\b(Standard|Input|Z-Matrix) orientation:\s*$", line, re.I)
        if not kind:
            continue
        last_table_complete = False
        separators = []
        for cursor in range(offset + 1, min(offset + 8, len(rows))):
            if re.match(r"^\s*-{5,}\s*$", rows[cursor][1]):
                separators.append(cursor)
                if len(separators) == 2:
                    break
        if len(separators) != 2:
            warnings.append(f"Incomplete orientation header at line {line_number}.")
            continue
        header = " ".join(row for _, row in rows[separators[0]:separators[1]])
        if "Angstroms" in header:
            factor, original_unit = 1.0, "angstrom"
        elif re.search(r"\bBohr\b", header, re.I):
            factor, original_unit = BOHR_ANGSTROM, "bohr"
        else:
            warnings.append(f"Unknown orientation length unit at line {line_number}.")
            continue
        positions, elements, indices = [], [], []
        end_line = None
        malformed = False
        for cursor in range(separators[1] + 1, len(rows)):
            number, record = rows[cursor]
            if re.match(r"^\s*-{5,}\s*$", record):
                end_line = number
                break
            match = re.fullmatch(rf"\s*(\d+)\s+(-?\d+)\s+(-?\d+)\s+({_NUM})\s+({_NUM})\s+({_NUM})\s*", record)
            if not match or not 0 < int(match.group(2)) < len(chemical_symbols):
                malformed = True
                break
            indices.append(int(match.group(1)))
            elements.append(chemical_symbols[int(match.group(2))])
            positions.append([float(match.group(i).replace("D", "E").replace("d", "e")) * factor
                              for i in (4, 5, 6)])
            if len(elements) > MAX_RESULT_ATOMS:
                raise ValueError("Gaussian orientation exceeds the atom limit.")
        if (malformed or end_line is None or not elements
                or indices != list(range(1, len(elements) + 1))
                or (atom_count is not None and len(elements) != atom_count)):
            warnings.append(f"Incomplete/unsupported orientation at line {line_number}; no final structure inferred.")
            continue
        geometry = {"elements": elements, "positions": positions, "cell": None,
                    "periodic_axes": [False, False, False], "units": "angstrom",
                    "source_units": original_unit, "atom_indices": indices,
                    "source": kind.group(1).lower() + " orientation",
                    "line_start": line_number, "line_end": end_line}
        validate_geometry(geometry)
        frames.append(geometry)
        last_table_complete = True
    return frames, (frames[-1] if frames and last_table_complete else None), warnings
