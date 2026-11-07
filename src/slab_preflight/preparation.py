"""Explicit, bounded symmetry expansion before the conservative P1 analyser.

This preparation never selects layers, adds vacuum, changes the cell, relaxes
sites, or interprets partial occupancy. Standard ASE setting 1 is required;
redundant symmetry declarations must describe exactly the same operation set.

ASE reference: https://ase.gitlab.io/ase/_modules/ase/spacegroup/spacegroup.html
Omitted-occupancy default: https://www.iucr.org/__data/iucr/cifdic_html/1/cif_core.dic/Iatom_site_occupancy.html
Hall reference: https://github.com/spglib/spglib/blob/2d0b73cc3b556282e35f9ae51de01268f5d88e5a/database/spg.csv
The Hall-symbol facts below were obtained from the 530-setting upstream table
(SHA-256 4457df1042b14a65ea62af0bad7b5b609a4fc33592df245802cfe005b221f95e,
retrieved 2026-11-05), matching the complete rotation/translation sets produced
by database/hall2operations.py to ASE 3.29.0 setting 1 for each IT number. Symbols
are crystallographic reference data; no spglib code or runtime dependency is
included. Upstream spglib is BSD-3-Clause: https://github.com/spglib/spglib/blob/develop/COPYING
"""
from __future__ import annotations

from dataclasses import dataclass
from fractions import Fraction
from hashlib import sha256
from io import StringIO
import re
import warnings

import ase
from ase.data import atomic_numbers
from ase.io.cif import parse_cif
from ase.spacegroup import Spacegroup
from ase.spacegroup.spacegroup import SpacegroupError, spacegroup_from_data
import numpy as np

from .core import MAX_ATOMS, MAX_FILE_BYTES, UnsupportedStructure, _numeric, _read_cif
from .core import (
    _normalize_cif_tags, _reject_duplicate_tags, _validate_site_metadata,
    _validate_site_multiplicity,
)

MAX_SYMMETRY_OPERATIONS = 192
SYMMETRY_TOLERANCE_ANGSTROM = 0.001
CELL_TAGS = (
    "_cell_length_a", "_cell_length_b", "_cell_length_c",
    "_cell_angle_alpha", "_cell_angle_beta", "_cell_angle_gamma",
)
COORDINATE_TAGS = ("_atom_site_fract_x", "_atom_site_fract_y", "_atom_site_fract_z")
OCCUPANCY_EXPLICIT = "explicit source occupancy 1.0 retained"
OCCUPANCY_DEFAULT = "omitted in source; coreCIF default 1.0 made explicit"


class PreparationError(ValueError):
    """A source cannot be expanded without unsupported assumptions."""


@dataclass(frozen=True)
class PreparedP1:
    cif: bytes
    source_sha256: str
    source_site_count: int
    prepared_site_count: int
    source_spacegroup_number: int
    source_spacegroup_symbol: str
    source_cell: tuple[float, ...]
    occupancy_policy: str
    symmetry_operation_count: int
    symmetry_tolerance_fractional: float
    warnings: tuple[str, ...]

    def metadata(self) -> dict:
        return {
            "method": "symmetry_expansion_to_p1",
            "source_sha256": self.source_sha256,
            "prepared_sha256": sha256(self.cif).hexdigest(),
            "source_site_count": self.source_site_count,
            "prepared_site_count": self.prepared_site_count,
            "source_spacegroup": {
                "number": self.source_spacegroup_number, "symbol": self.source_spacegroup_symbol,
            },
            "source_cell": list(self.source_cell),
            "prepared_cell": list(self.source_cell),
            "occupancy_policy": self.occupancy_policy,
            "symmetry_operation_count": self.symmetry_operation_count,
            "symmetry_tolerance_fractional": self.symmetry_tolerance_fractional,
            "symmetry_tolerance_angstrom": SYMMETRY_TOLERANCE_ANGSTROM,
            "ase_version": ase.__version__,
            "warnings": list(self.warnings),
            "changes": [
                "Symmetry-equivalent sites expanded in the original conventional cell.",
                "All resulting sites written explicitly as P1 with occupancy 1.",
                "Original cell retained; no vacuum, layer selection, or relaxation performed.",
            ],
        }


def _explicit_p1(parameters: list[float], symbols: list[str], positions: np.ndarray,
                 source_hash: str) -> bytes:
    lines = [
        "# CalcLens explicit P1 preparation; original source is retained in the project.",
        f"# Original source SHA-256: {source_hash}",
        "# Cell unchanged; no layer selection, vacuum insertion, or relaxation.",
        "data_calclens_prepared_p1",
    ]
    lines.extend(f"{tag} {value:.15g}" for tag, value in zip(CELL_TAGS, parameters))
    lines.extend([
        "_space_group_IT_number 1", "_space_group_name_H-M_alt 'P 1'",
        "loop_", "_space_group_symop_operation_xyz", "'x,y,z'", "loop_",
        "_atom_site_label", "_atom_site_type_symbol", "_atom_site_fract_x",
        "_atom_site_fract_y", "_atom_site_fract_z", "_atom_site_occupancy",
    ])
    for index, (symbol, point) in enumerate(zip(symbols, positions), 1):
        x, y, z = np.mod(point, 1.0)
        lines.append(f"{symbol}{index} {symbol} {x:.15g} {y:.15g} {z:.15g} 1")
    return ("\n".join(lines) + "\n").encode("utf-8")


def _block(source: bytes) -> dict:
    if not isinstance(source, bytes) or not 1 <= len(source) <= MAX_FILE_BYTES:
        raise PreparationError("Provide between 1 byte and 2 MiB of original CIF content.")
    try:
        text = source.decode("utf-8-sig")
    except UnicodeDecodeError:
        text = source.decode("latin-1")
    if not text.strip() or "\x00" in text or "#\\#CIF_2.0" in text:
        raise PreparationError("Preparation requires nonempty CIF 1.1 text without binary/null data.")
    _reject_duplicate_tags(text)
    try:
        with warnings.catch_warnings():
            warnings.simplefilter("error")
            blocks = list(parse_cif(StringIO(text), reader="ase"))
    except Exception as exc:
        raise PreparationError("ASE could not parse an unambiguous CIF 1.1 source.") from exc
    if len(blocks) != 1:
        raise PreparationError("Exactly one CIF data block is required for preparation.")
    block = _normalize_cif_tags(blocks[0])
    for original in block:
        # Forbidden metadata remains forbidden regardless of dictionary spelling.
        key = original.replace(".", "_")
        if (
            any(marker in key for marker in ("modulat", "superspace", "fourier"))
            or key.startswith((
                "_space_group_ssg_", "_space_group_symop_ssg_", "_cell_wave_vector_",
                "_cell_subsystem_", "_atom_site_subsystem_", "_atom_site_phason_",
                "_atom_site_displace_special_func_", "_atom_site_occ_special_func_",
            ))
            or key == "_cell_reciprocal_basis_description"
            or ("magn" in key and ("symop" in key or "space_group" in key))
        ):
            raise PreparationError("Modulated, magnetic, superspace, and composite CIFs cannot be prepared.")
    return block


def _column(block: dict, key: str, count: int | None = None) -> list:
    value = block.get(key)
    if not isinstance(value, list) or not value or (count is not None and len(value) != count):
        raise PreparationError(f"{key} must be a nonempty site-loop column of the expected length.")
    return value


def _sites(block: dict) -> tuple[list[str], np.ndarray, str]:
    coordinates = [_column(block, key) for key in COORDINATE_TAGS]
    count = len(coordinates[0])
    if not 1 <= count <= MAX_ATOMS or any(len(values) != count for values in coordinates):
        raise PreparationError("The source requires 1 to 400 sites and equal-length fractional columns.")
    if any(key.startswith("_atom_site_cartn_") for key in block):
        raise PreparationError("Use fractional coordinates only; mixed Cartesian coordinates are unsupported.")
    if "_atom_site_type_symbol" in block:
        symbols = _column(block, "_atom_site_type_symbol", count)
    else:
        labels = _column(block, "_atom_site_label", count)
        symbols = []
        for label in labels:
            match = re.fullmatch(r"([A-Z][a-z]?)(?:[0-9]+[A-Za-z0-9_]*)?", str(label))
            if match is None:
                raise PreparationError("Without type symbols, each site label must identify a canonical element.")
            symbols.append(match.group(1))
    if any(not isinstance(symbol, str) or symbol not in atomic_numbers or symbol == "X"
           for symbol in symbols):
        raise PreparationError("Canonical element symbols are required; isotope, mixed, and charged labels are unsupported.")
    if "_atom_site_label" in block:
        labels = _column(block, "_atom_site_label", count)
        if len(set(map(str, labels))) != count:
            raise PreparationError("Source site labels must be unique.")
    occupancy_policy = (OCCUPANCY_EXPLICIT if _validate_site_metadata(block, count)
                        else OCCUPANCY_DEFAULT)
    positions = np.array([[_numeric(value, "Fractional coordinate") for value in column]
                          for column in coordinates], dtype=float).T
    if np.any(np.abs(positions) > 1e6):
        raise PreparationError("Fractional coordinates above 1000000 in magnitude are unsupported.")
    return list(symbols), positions, occupancy_policy


def _operation(value: object) -> tuple[np.ndarray, np.ndarray]:
    if not isinstance(value, str) or len(value) > 200:
        raise PreparationError("Symmetry operations must be bounded x,y,z expressions.")
    components = re.sub(r"\s+", "", value).lower().split(",")
    if len(components) != 3:
        raise PreparationError("Each symmetry operation must contain exactly three coordinates.")
    rotation = np.zeros((3, 3), dtype=int)
    translation = np.zeros(3)
    for row, component in enumerate(components):
        terms = re.findall(r"[+-]?(?:[xyz]|(?:[0-9]+(?:\.[0-9]*)?|\.[0-9]+)(?:/[0-9]+)?)", component)
        if not terms or "".join(terms) != component:
            raise PreparationError("Unsupported or ambiguous symmetry-operation expression.")
        shift = Fraction(0)
        for term in terms:
            token = term.lstrip("+-")
            sign = -1 if term.startswith("-") else 1
            if token in ("x", "y", "z"):
                rotation[row, "xyz".index(token)] += sign
            else:
                try:
                    shift += sign * Fraction(token)
                except (ValueError, ZeroDivisionError) as exc:
                    raise PreparationError("Invalid symmetry translation.") from exc
        if abs(shift) > 10:
            raise PreparationError("Symmetry translations above 10 unit cells are unsupported.")
        translation[row] = float(shift % 1)
    if np.any(abs(rotation) > 1) or abs(round(float(np.linalg.det(rotation)))) != 1:
        raise PreparationError("Symmetry rotations must be invertible crystallographic integer matrices.")
    return rotation, translation


def _operation_key(operation: tuple[np.ndarray, np.ndarray]) -> tuple:
    rotation, translation = operation
    return (*map(int, rotation.flat), *np.round(np.mod(translation, 1.0), 10))


def _symmetry(block: dict) -> tuple[Spacegroup, list[str] | None]:
    groups = []
    for key in ("_space_group_it_number", "_symmetry_int_tables_number"):
        if key in block:
            value = _numeric(block[key], "Space-group number")
            if not value.is_integer() or not 1 <= value <= 230:
                raise PreparationError("Space-group number must be an integer from 1 to 230.")
            groups.append(Spacegroup(int(value), setting=1))
    for key in ("_space_group_name_h-m_alt", "_space_group_name_h-m_ref",
                "_symmetry_space_group_name_h-m"):
        if key in block:
            value = block[key]
            if not isinstance(value, str) or not 1 <= len(value) <= 80:
                raise PreparationError("Space-group names must be unambiguous standard Hermann–Mauguin symbols.")
            try:
                groups.append(Spacegroup(value, setting=1))
            except (SpacegroupError, ValueError, KeyError) as exc:
                raise PreparationError("Only ASE standard-setting Hermann–Mauguin symbols are supported.") from exc
    for key in ("_space_group_name_hall", "_symmetry_space_group_name_hall"):
        if key in block:
            value = block[key]
            if not isinstance(value, str) or len(value) > 80:
                raise PreparationError("Invalid Hall-symbol declaration.")
            hall = re.sub(r"\s+", "", value).lower()
            matches = [number for number, symbols in _STANDARD_HALL_SYMBOLS.items()
                       if hall in {re.sub(r"\s+", "", symbol).lower() for symbol in symbols}]
            if len(matches) != 1:
                raise PreparationError("Hall symbols must match an unambiguous ASE standard setting 1.")
            groups.append(Spacegroup(matches[0], setting=1))
    if not groups:
        raise PreparationError("An explicit standard space-group number or symbol is required; symmetry is not guessed.")
    group = groups[0]
    if any(item.no != group.no or item.setting != 1 for item in groups):
        raise PreparationError("Conflicting space-group declarations are ambiguous.")
    if "_symmetry_space_group_setting" in block:
        if _numeric(block["_symmetry_space_group_setting"], "Space-group setting") != 1:
            raise PreparationError("Only standard space-group setting 1 is supported.")
    for key in ("_space_group_it_coordinate_system_code", "_space_group_origin_choice"):
        if key in block and str(block[key]) != "1":
            raise PreparationError("Alternate or unknown coordinate/origin settings are unsupported.")
    crystal_system = next(name for maximum, name in (
        (2, "triclinic"), (15, "monoclinic"), (74, "orthorhombic"),
        (142, "tetragonal"), (167, "trigonal"), (194, "hexagonal"), (230, "cubic"),
    ) if group.no <= maximum)
    for key in ("_space_group_crystal_system", "_symmetry_cell_setting"):
        if key in block:
            allowed = {crystal_system}
            if crystal_system == "trigonal":
                allowed.add("hexagonal")  # ASE setting 1 uses hexagonal axes.
            if not isinstance(block[key], str) or block[key].lower() not in allowed:
                raise PreparationError("Crystal-system metadata conflicts with the declared standard setting.")
    reference = {_operation_key(operation) for operation in group.get_symop()}
    operation_columns = []
    for key in ("_space_group_symop_operation_xyz", "_symmetry_equiv_pos_as_xyz"):
        if key in block:
            values = block[key] if isinstance(block[key], list) else [block[key]]
            if not 1 <= len(values) <= MAX_SYMMETRY_OPERATIONS:
                raise PreparationError("Provide 1 to 192 explicit symmetry operations.")
            parsed = [_operation(value) for value in values]
            actual = {_operation_key(operation) for operation in parsed}
            if len(actual) != len(values) or actual != reference:
                raise PreparationError("Explicit symmetry operations conflict with the declared standard space group.")
            operation_columns.append(values)
    return group, operation_columns[0] if operation_columns else None


def _prepare_p1(source: bytes, normal_axis: str) -> PreparedP1:
    if normal_axis not in ("a", "b", "c"):
        raise PreparationError("Normal axis must be a, b, or c.")
    block = _block(source)
    symbols, positions, occupancy_policy = _sites(block)
    if any(key not in block for key in CELL_TAGS):
        raise PreparationError("All six original cell lengths and angles are required.")
    parameters = [_numeric(block[key], "Cell parameter") for key in CELL_TAGS]
    digest = sha256(source).hexdigest()
    # Validate the source geometry using the unchanged analysis boundary before
    # performing symmetry expansion. This temporary explicit file is not saved.
    source_atoms, _ = _read_cif(_explicit_p1(parameters, symbols, positions, digest), normal_axis)
    group, operations = _symmetry(block)
    metric = np.asarray(source_atoms.cell) @ np.asarray(source_atoms.cell).T
    if any(not np.allclose(rotation.T @ metric @ rotation, metric, rtol=1e-5, atol=1e-8)
           for rotation, _ in group.get_symop()):
        raise PreparationError("Declared symmetry operations are inconsistent with the original cell geometry.")
    # Bound the physical ambiguity of ASE's fractional equivalent-site test.
    tolerance = min(1e-3, SYMMETRY_TOLERANCE_ANGSTROM /
                    (np.sqrt(3) * np.linalg.norm(np.asarray(source_atoms.cell), 2)))
    if operations is not None:
        expansion = spacegroup_from_data(
            no=group.no, setting=1, sitesym=operations,
            subtrans=[(0, 0, 0)], centrosymmetric=False,
        )
    else:
        expansion = group
    expanded_sites: list[np.ndarray] = []
    expanded_symbols: list[str] = []
    orbit_counts = []
    # Expand deposited fractional values directly. A Cartesian round trip here
    # would introduce platform-dependent rounding into the portable derivative.
    for symbol, position in zip(symbols, np.mod(positions, 1.0)):
        orbit, _ = expansion.equivalent_sites([position], onduplicates="error", symprec=tolerance)
        orbit_counts.append(len(orbit))
        if len(expanded_sites) + len(orbit) > MAX_ATOMS:
            raise PreparationError("Symmetry expansion exceeds the 400-site supported limit.")
        if expanded_sites:
            differences = orbit[:, None, :] - np.asarray(expanded_sites)[None, :, :]
            differences -= np.rint(differences)
            if np.any(np.all(np.abs(differences) < tolerance, axis=2)):
                raise PreparationError("Source sites are symmetry-equivalent or overlapping; preparation cannot merge them.")
        expanded_sites.extend(orbit)
        expanded_symbols.extend([symbol] * len(orbit))
    _validate_site_multiplicity(block, orbit_counts, prepared=True)
    # Stable source-site/orbit ordering preserves representatives selected from
    # deposited coordinates rather than rounding them onto ideal special sites.
    prepared = _explicit_p1(parameters, expanded_symbols, np.array(expanded_sites), digest)
    _read_cif(prepared, normal_axis)
    notices = [
        "The original cell is retained. This is symmetry expansion, not slab construction or relaxation.",
        "Equivalent symmetry images are identified within at most 0.001 angstrom; deposited representative coordinates are retained.",
    ]
    if occupancy_policy == OCCUPANCY_DEFAULT:
        notices.append("Occupancy was omitted; the coreCIF default 1.0 is made explicit for every resulting site.")
    if operations is None:
        notices.append("Symmetry operations are generated from the explicit ASE standard-setting space group.")
    return PreparedP1(
        prepared, digest, len(symbols), len(expanded_sites), group.no, group.symbol,
        tuple(parameters), occupancy_policy, len(group.get_symop()), float(tolerance), tuple(notices),
    )


def prepare_p1(source: bytes, normal_axis: str = "c") -> PreparedP1:
    """Return a detached explicit-P1 preview; reject unsupported assumptions."""
    try:
        return _prepare_p1(source, normal_axis)
    except PreparationError:
        raise
    except (UnsupportedStructure, SpacegroupError, ValueError, TypeError, KeyError, AssertionError,
            OverflowError, RuntimeError) as exc:
        raise PreparationError(str(exc) or "Source could not be prepared as an unambiguous P1 structure.") from exc


# Hall symbols whose full operations match ASE setting 1.
# Reference data: spglib database/spg.csv (530 settings), generated by
# matching exact rotation/fractional-translation sets, not name guessing.
_STANDARD_HALL_SYMBOLS = {
    1: ('P 1',),
    2: ('-P 1',),
    3: ('P 2y',),
    4: ('P 2yb',),
    5: ('C 2y',),
    6: ('P -2y',),
    7: ('P -2yc',),
    8: ('C -2y',),
    9: ('C -2yc',),
    10: ('-P 2y',),
    11: ('-P 2yb',),
    12: ('-C 2y',),
    13: ('-P 2yc',),
    14: ('-P 2ybc',),
    15: ('-C 2yc',),
    16: ('P 2 2',),
    17: ('P 2c 2',),
    18: ('P 2 2ab',),
    19: ('P 2ac 2ab',),
    20: ('C 2c 2',),
    21: ('C 2 2',),
    22: ('F 2 2',),
    23: ('I 2 2',),
    24: ('I 2b 2c',),
    25: ('P 2 -2',),
    26: ('P 2c -2',),
    27: ('P 2 -2c',),
    28: ('P 2 -2a',),
    29: ('P 2c -2ac',),
    30: ('P 2 -2bc',),
    31: ('P 2ac -2',),
    32: ('P 2 -2ab',),
    33: ('P 2c -2n',),
    34: ('P 2 -2n',),
    35: ('C 2 -2',),
    36: ('C 2c -2',),
    37: ('C 2 -2c',),
    38: ('A 2 -2',),
    39: ('A 2 -2b',),
    40: ('A 2 -2a',),
    41: ('A 2 -2ab',),
    42: ('F 2 -2',),
    43: ('F 2 -2d',),
    44: ('I 2 -2',),
    45: ('I 2 -2c',),
    46: ('I 2 -2a',),
    47: ('-P 2 2',),
    48: ('P 2 2 -1n',),
    49: ('-P 2 2c',),
    50: ('P 2 2 -1ab',),
    51: ('-P 2a 2a',),
    52: ('-P 2a 2bc',),
    53: ('-P 2ac 2',),
    54: ('-P 2a 2ac',),
    55: ('-P 2 2ab',),
    56: ('-P 2ab 2ac',),
    57: ('-P 2c 2b',),
    58: ('-P 2 2n',),
    59: ('P 2 2ab -1ab',),
    60: ('-P 2n 2ab',),
    61: ('-P 2ac 2ab',),
    62: ('-P 2ac 2n',),
    63: ('-C 2c 2',),
    64: ('-C 2ac 2',),
    65: ('-C 2 2',),
    66: ('-C 2 2c',),
    67: ('-C 2a 2',),
    68: ('C 2 2 -1ac', 'C 2 2 -1ac'),
    69: ('-F 2 2',),
    70: ('F 2 2 -1d',),
    71: ('-I 2 2',),
    72: ('-I 2 2c',),
    73: ('-I 2b 2c',),
    74: ('-I 2b 2',),
    75: ('P 4',),
    76: ('P 4w',),
    77: ('P 4c',),
    78: ('P 4cw',),
    79: ('I 4',),
    80: ('I 4bw',),
    81: ('P -4',),
    82: ('I -4',),
    83: ('-P 4',),
    84: ('-P 4c',),
    85: ('P 4ab -1ab',),
    86: ('P 4n -1n',),
    87: ('-I 4',),
    88: ('I 4bw -1bw',),
    89: ('P 4 2',),
    90: ('P 4ab 2ab',),
    91: ('P 4w 2c',),
    92: ('P 4abw 2nw',),
    93: ('P 4c 2',),
    94: ('P 4n 2n',),
    95: ('P 4cw 2c',),
    96: ('P 4nw 2abw',),
    97: ('I 4 2',),
    98: ('I 4bw 2bw',),
    99: ('P 4 -2',),
    100: ('P 4 -2ab',),
    101: ('P 4c -2c',),
    102: ('P 4n -2n',),
    103: ('P 4 -2c',),
    104: ('P 4 -2n',),
    105: ('P 4c -2',),
    106: ('P 4c -2ab',),
    107: ('I 4 -2',),
    108: ('I 4 -2c',),
    109: ('I 4bw -2',),
    110: ('I 4bw -2c',),
    111: ('P -4 2',),
    112: ('P -4 2c',),
    113: ('P -4 2ab',),
    114: ('P -4 2n',),
    115: ('P -4 -2',),
    116: ('P -4 -2c',),
    117: ('P -4 -2ab',),
    118: ('P -4 -2n',),
    119: ('I -4 -2',),
    120: ('I -4 -2c',),
    121: ('I -4 2',),
    122: ('I -4 2bw',),
    123: ('-P 4 2',),
    124: ('-P 4 2c',),
    125: ('P 4 2 -1ab',),
    126: ('P 4 2 -1n',),
    127: ('-P 4 2ab',),
    128: ('-P 4 2n',),
    129: ('P 4ab 2ab -1ab',),
    130: ('P 4ab 2n -1ab',),
    131: ('-P 4c 2',),
    132: ('-P 4c 2c',),
    133: ('P 4n 2c -1n',),
    134: ('P 4n 2 -1n',),
    135: ('-P 4c 2ab',),
    136: ('-P 4n 2n',),
    137: ('P 4n 2n -1n',),
    138: ('P 4n 2ab -1n',),
    139: ('-I 4 2',),
    140: ('-I 4 2c',),
    141: ('I 4bw 2bw -1bw',),
    142: ('I 4bw 2aw -1bw',),
    143: ('P 3',),
    144: ('P 31',),
    145: ('P 32',),
    146: ('R 3',),
    147: ('-P 3',),
    148: ('-R 3',),
    149: ('P 3 2',),
    150: ('P 3 2"',),
    151: ('P 31 2 (0 0 4)',),
    152: ('P 31 2"',),
    153: ('P 32 2 (0 0 2)',),
    154: ('P 32 2"',),
    155: ('R 3 2"',),
    156: ('P 3 -2"',),
    157: ('P 3 -2',),
    158: ('P 3 -2"c',),
    159: ('P 3 -2c',),
    160: ('R 3 -2"',),
    161: ('R 3 -2"c',),
    162: ('-P 3 2',),
    163: ('-P 3 2c',),
    164: ('-P 3 2"',),
    165: ('-P 3 2"c',),
    166: ('-R 3 2"',),
    167: ('-R 3 2"c',),
    168: ('P 6',),
    169: ('P 61',),
    170: ('P 65',),
    171: ('P 62',),
    172: ('P 64',),
    173: ('P 6c',),
    174: ('P -6',),
    175: ('-P 6',),
    176: ('-P 6c',),
    177: ('P 6 2',),
    178: ('P 61 2 (0 0 5)',),
    179: ('P 65 2 (0 0 1)',),
    180: ('P 62 2 (0 0 4)',),
    181: ('P 64 2 (0 0 2)',),
    182: ('P 6c 2c',),
    183: ('P 6 -2',),
    184: ('P 6 -2c',),
    185: ('P 6c -2',),
    186: ('P 6c -2c',),
    187: ('P -6 2',),
    188: ('P -6c 2',),
    189: ('P -6 -2',),
    190: ('P -6c -2c',),
    191: ('-P 6 2',),
    192: ('-P 6 2c',),
    193: ('-P 6c 2',),
    194: ('-P 6c 2c',),
    195: ('P 2 2 3',),
    196: ('F 2 2 3',),
    197: ('I 2 2 3',),
    198: ('P 2ac 2ab 3',),
    199: ('I 2b 2c 3',),
    200: ('-P 2 2 3',),
    201: ('P 2 2 3 -1n',),
    202: ('-F 2 2 3',),
    203: ('F 2 2 3 -1d',),
    204: ('-I 2 2 3',),
    205: ('-P 2ac 2ab 3',),
    206: ('-I 2b 2c 3',),
    207: ('P 4 2 3',),
    208: ('P 4n 2 3',),
    209: ('F 4 2 3',),
    210: ('F 4d 2 3',),
    211: ('I 4 2 3',),
    212: ('P 4acd 2ab 3',),
    213: ('P 4bd 2ab 3',),
    214: ('I 4bd 2c 3',),
    215: ('P -4 2 3',),
    216: ('F -4 2 3',),
    217: ('I -4 2 3',),
    218: ('P -4n 2 3',),
    219: ('F -4a 2 3',),
    220: ('I -4bd 2c 3',),
    221: ('-P 4 2 3',),
    222: ('P 4 2 3 -1n',),
    223: ('-P 4n 2 3',),
    224: ('P 4n 2 3 -1n',),
    225: ('-F 4 2 3',),
    226: ('-F 4a 2 3',),
    227: ('F 4d 2 3 -1d',),
    228: ('F 4d 2 3 -1ad',),
    229: ('-I 4 2 3',),
    230: ('-I 4bd 2c 3',),
}
