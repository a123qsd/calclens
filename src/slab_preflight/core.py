"""Conservative geometric preflight for explicitly expanded P1 slab CIFs.

ASE supplies CIF tokenization, lattice reduction and minimum-image geometry.
Site records are never symmetrized, merged, repaired or deleted.
"""

from __future__ import annotations

import io
import math
import re
import warnings
from typing import Any

import numpy as np
from ase import Atoms
from ase.cell import Cell
from ase.data import atomic_numbers
from ase.geometry import find_mic, minkowski_reduce
from ase.io.cif import parse_cif

MAX_FILE_BYTES = 2 * 1024 * 1024
MAX_ATOMS = 400
MAX_CONTACTS = 200
OCCUPANCY_TOLERANCE = 1e-8
OVERLAP_TOLERANCE = 1e-5
PERPENDICULAR_ANGLE_TOLERANCE = 1e-5
AMBIGUOUS_GAP_MIN = 3.0
AMBIGUOUS_GAP_MAX_FRACTION = 0.5
COMPETING_GAP_MIN = 3.0
COMPETING_GAP_RATIO = 0.5


class UnsupportedStructure(ValueError):
    """The input cannot be interpreted within this tool's supported scope."""


# Only declared aliases are interchangeable. Replacing every dot with an
# underscore can silently reinterpret unknown data names as supported fields.
# IUCr coreCIF: https://www.iucr.org/__data/iucr/cifdic_html/3/CORE_DIC/index.html
_CIF_ALIAS_FIELDS = {
    "cell": ("length_a", "length_b", "length_c", "angle_alpha", "angle_beta", "angle_gamma"),
    "atom_site": (
        "label", "type_symbol", "fract_x", "fract_y", "fract_z",
        "cartn_x", "cartn_y", "cartn_z", "occupancy",
        "disorder_assembly", "disorder_group", "symmetry_multiplicity",
    ),
    "space_group": (
        "it_number", "name_h-m_alt", "name_h-m_ref", "name_hall",
        "it_coordinate_system_code", "origin_choice", "crystal_system",
    ),
    "space_group_symop": ("operation_xyz",),
    "symmetry": (
        "int_tables_number", "space_group_name_h-m", "space_group_name_hall",
        "space_group_setting", "cell_setting",
    ),
    "symmetry_equiv": ("pos_as_xyz",),
}
_CIF_TAG_ALIASES = {
    alias: f"_{category}_{field}"
    for category, fields in _CIF_ALIAS_FIELDS.items()
    for field in fields
    for alias in (f"_{category}_{field}", f"_{category}.{field}")
}
_CIF_TAG_ALIASES.update({
    "_atom_site_site_symmetry_multiplicity": "_atom_site_symmetry_multiplicity",
    "_atom_site.site_symmetry_multiplicity": "_atom_site_symmetry_multiplicity",
})
for _legacy, _canonical in (
    ("symmetry.int_tables_number", "_space_group_it_number"),
    ("symmetry.space_group_name_h-m", "_space_group_name_h-m_alt"),
    ("symmetry.space_group_name_hall", "_space_group_name_hall"),
    ("symmetry_equiv.pos_as_xyz", "_space_group_symop_operation_xyz"),
):
    _CIF_TAG_ALIASES[f"_{_legacy}"] = _canonical
    _CIF_TAG_ALIASES[f"_{_legacy.replace('.', '_')}"] = _canonical
# These describe uncertainty/refinement, not the occupancy value itself.
_OCCUPANCY_ANNOTATIONS = {
    f"_atom_site{separator}{field}"
    for separator in ("_", ".")
    for field in ("occupancy_su", "occupancy_esd", "refinement_flags_occupancy")
}


def _normalize_cif_tags(block: Any) -> dict[str, Any]:
    """Resolve the same supported names at both analysis and preparation entrypoints."""
    normalized: dict[str, Any] = {}
    for original in block:
        raw = original.lower()
        key = _CIF_TAG_ALIASES.get(raw, raw)
        if raw not in _CIF_TAG_ALIASES and raw not in _OCCUPANCY_ANNOTATIONS:
            compact = re.sub(r"[_.-]", "", raw)
            if compact.startswith("atomsite") and any(
                marker in compact for marker in ("occupancy", "disorder", "multiplicity")
            ):
                raise UnsupportedStructure(
                    f"Unsupported occupancy, disorder, or multiplicity CIF tag: {original}."
                )
        if key in normalized:
            raise UnsupportedStructure("Repeated CIF tag aliases are ambiguous and unsupported.")
        normalized[key] = block[original]
    return normalized


def _issue(
    code: str,
    severity: str,
    message: str,
    *,
    atom_indices: list[int] | None = None,
    area_id: str | None = None,
    contact_count: int | None = None,
    representative_contact: dict[str, Any] | None = None,
) -> dict[str, Any]:
    issue: dict[str, Any] = {"code": code, "severity": severity, "message": message}
    if atom_indices is not None:
        issue["atom_indices"] = atom_indices
    if area_id is not None:
        issue["area_id"] = area_id
    if contact_count is not None:
        issue["contact_count"] = contact_count
    if representative_contact is not None:
        issue["representative_contact"] = representative_contact
    return issue


def _values(value: Any) -> list[Any]:
    return value if isinstance(value, list) else [value]


def _numeric(value: Any, description: str) -> float:
    try:
        result = float(value)
    except (ValueError, TypeError, OverflowError):
        raise UnsupportedStructure(f"{description} must be a finite number.") from None
    if not math.isfinite(result):
        raise UnsupportedStructure(f"{description} must be a finite number.")
    return result


def _site_metadata_column(block: Any, key: str, count: int) -> list[Any]:
    values = block[key]
    if not isinstance(values, list) or len(values) != count:
        raise UnsupportedStructure(
            "Occupancy, disorder, and multiplicity must be site-loop columns matching the site count."
        )
    return values


def _validate_site_metadata(block: Any, count: int) -> bool:
    """Validate occupancy/disorder; return whether occupancy was explicitly provided."""
    explicit_occupancy = "_atom_site_occupancy" in block
    if explicit_occupancy:
        values = _site_metadata_column(block, "_atom_site_occupancy", count)
        if any(abs(_numeric(value, "Occupancy") - 1) > OCCUPANCY_TOLERANCE for value in values):
            raise UnsupportedStructure("Only fully occupied sites (occupancy 1) are supported.")
    for key in ("_atom_site_disorder_assembly", "_atom_site_disorder_group"):
        if key in block and any(str(value) not in (".", "0")
                                for value in _site_metadata_column(block, key, count)):
            raise UnsupportedStructure("Disordered or ambiguous site groups are unsupported.")
    return explicit_occupancy


def _validate_site_multiplicity(block: Any, expected: list[int], *, prepared: bool = False) -> None:
    key = "_atom_site_symmetry_multiplicity"
    if key not in block:
        return
    values = _site_metadata_column(block, key, len(expected))
    if any(_numeric(value, "Site multiplicity") != count
           for value, count in zip(values, expected)):
        if prepared:
            raise UnsupportedStructure("Declared site multiplicity disagrees with symmetry expansion.")
        raise UnsupportedStructure("Site multiplicity must be 1 in an explicitly expanded P1 structure.")


def _reject_duplicate_tags(text: str) -> None:
    # ASE warns for repeated loop headers, but can overwrite repeated scalar
    # tags. Reject either form before parsing, outside CIF multiline strings.
    seen: set[str] = set()
    multiline = False
    for line in text.splitlines():
        if line.startswith(";"):
            multiline = not multiline
            continue
        if multiline:
            continue
        match = re.match(r"^\s*(_[A-Za-z0-9_.-]+)(?:\s|$)", line)
        if match:
            key = match.group(1).lower()
            if key in seen:
                raise UnsupportedStructure("Repeated CIF tags are ambiguous and unsupported.")
            seen.add(key)


def _validate_symmetry(block: Any) -> None:
    # msCIF can contain ordinary-looking average fractional coordinates as well
    # as superspace operations, modulation waves and composite subsystems. Those
    # coordinates alone do not describe the full structure. Reject this metadata
    # rather than silently interpreting the average as an ordinary P1 crystal.
    for raw_key in block:
        key = raw_key.replace(".", "_")
        if (
            any(marker in key for marker in ("modulat", "superspace", "fourier"))
            or key.startswith((
                "_space_group_ssg_", "_space_group_symop_ssg_",
                "_cell_wave_vector_", "_cell_subsystem_",
                "_atom_site_subsystem_", "_atom_site_phason_",
                "_atom_site_displace_special_func_", "_atom_site_occ_special_func_",
            ))
            or key == "_cell_reciprocal_basis_description"
        ):
            raise UnsupportedStructure(
                "Modulated, superspace, and composite-structure CIF metadata are unsupported; "
                "average site coordinates are not an explicit ordinary periodic structure."
            )
    number_tags = (
        "_space_group.it_number", "_space_group_it_number",
        "_symmetry_int_tables_number",
    )
    name_tags = (
        "_space_group_name_h-m_alt", "_space_group.name_h-m_alt",
        "_space_group_name_h-m_ref", "_space_group.name_h-m_ref",
        "_symmetry_space_group_name_h-m", "_space_group_name_hall",
        "_space_group.name_hall", "_symmetry_space_group_name_hall",
    )
    operation_tags = (
        "_space_group_symop_operation_xyz", "_space_group_symop.operation_xyz",
        "_symmetry_equiv_pos_as_xyz",
    )
    declared = False
    for key in number_tags:
        if key in block:
            declared = True
            if _numeric(block[key], "Space-group number") != 1:
                raise UnsupportedStructure("Only explicitly expanded P1 (space group 1) CIFs are supported.")
    for key in name_tags:
        if key in block:
            declared = True
            if re.sub(r"\s+", "", str(block[key])).lower() != "p1":
                raise UnsupportedStructure("Only P1 symmetry is supported; export all sites as P1 first.")
    if not declared:
        raise UnsupportedStructure("Explicit P1 space-group name or number is required; symmetry is not guessed.")
    for key in operation_tags:
        if key in block:
            ops = _values(block[key])
            if len(ops) != 1 or re.sub(r"\s+", "", str(ops[0])).lower() != "x,y,z":
                raise UnsupportedStructure("Only the identity symmetry operation 'x,y,z' is supported.")
    if "_symmetry_space_group_setting" in block:
        if _numeric(block["_symmetry_space_group_setting"], "Space-group setting") != 1:
            raise UnsupportedStructure("Nonstandard space-group settings are unsupported.")
    for key in ("_space_group_it_coordinate_system_code", "_space_group_origin_choice"):
        if key in block and str(block[key]) != "1":
            raise UnsupportedStructure("Nonstandard space-group settings are unsupported.")
    if any("magn" in key and ("symop" in key or "space_group" in key) for key in block):
        raise UnsupportedStructure("Magnetic symmetry CIFs are unsupported.")


def _read_cif(data: str | bytes, normal_axis: str) -> tuple[Atoms, list[dict[str, Any]]]:
    if not isinstance(data, (str, bytes)):
        raise UnsupportedStructure("Provide CIF text or bytes, not a filename or another object.")
    size = len(data) if isinstance(data, bytes) else len(data.encode("utf-8"))
    if size > MAX_FILE_BYTES:
        raise UnsupportedStructure("CIF exceeds the 2 MiB input limit.")
    if isinstance(data, bytes):
        try:
            text = data.decode("utf-8-sig")
        except UnicodeDecodeError:
            text = data.decode("latin-1")
    else:
        text = data.lstrip("\ufeff")
    if not text.strip() or "\x00" in text:
        raise UnsupportedStructure("Input is empty or contains binary/null data.")
    if "#\\#CIF_2.0" in text:
        raise UnsupportedStructure("CIF 2.0 is unsupported; export a simple CIF 1.1 P1 structure.")
    _reject_duplicate_tags(text)
    try:
        with warnings.catch_warnings():
            warnings.simplefilter("error")
            blocks = list(parse_cif(io.StringIO(text), reader="ase"))
    except Exception:
        raise UnsupportedStructure("ASE could not parse this as an unambiguous CIF 1.1 file.") from None
    if len(blocks) != 1:
        raise UnsupportedStructure("Exactly one CIF data block is required.")
    block = _normalize_cif_tags(blocks[0])
    _validate_symmetry(block)

    cell_tags = (
        "_cell_length_a", "_cell_length_b", "_cell_length_c",
        "_cell_angle_alpha", "_cell_angle_beta", "_cell_angle_gamma",
    )
    if any(key not in block for key in cell_tags):
        raise UnsupportedStructure("All six cell lengths/angles are required (angstrom and degrees).")
    parameters = [_numeric(block[key], "Cell parameter") for key in cell_tags]
    if any(length < 0.001 or length > 10000 for length in parameters[:3]):
        raise UnsupportedStructure("Cell lengths must lie between 0.001 and 10000 angstrom.")
    normal_index = "abc".index(normal_axis)
    angles = parameters[3:]
    if any(not 0 < angle < 180 for angle in angles):
        raise UnsupportedStructure("All cell angles must be strictly between 0 and 180 degrees.")
    # alpha is between b,c; beta between a,c; gamma between a,b. The
    # angle opposite the selected normal may be oblique within the slab plane.
    constrained = [index for index in range(3) if index != normal_index]
    if any(abs(angles[index] - 90) > PERPENDICULAR_ANGLE_TOLERANCE for index in constrained):
        angle_names = ["alpha", "beta", "gamma"]
        required_angles = " = ".join(angle_names[index] for index in constrained)
        other_axes = " and ".join("abc"[index] for index in constrained)
        raise UnsupportedStructure(
            f"The selected {normal_axis} axis must be perpendicular to {other_axes} "
            f"({required_angles} = 90 degrees). Tilted slab normals are unsupported."
        )
    try:
        cell = Cell.fromcellpar(parameters)
    except (AssertionError, ValueError):
        # ASE asserts when otherwise bounded angles cannot form real vectors.
        # Keep this conversion local so unrelated programming errors propagate.
        raise UnsupportedStructure(
            "Cell lengths and angles cannot form a valid three-dimensional cell."
        ) from None
    if not np.isfinite(cell).all() or np.linalg.cond(cell) > 1e4 or cell.volume <= 0:
        raise UnsupportedStructure("Degenerate or ill-conditioned cells are unsupported (condition number > 10000).")

    coordinate_tags = ("_atom_site_fract_x", "_atom_site_fract_y", "_atom_site_fract_z")
    required = ("_atom_site_type_symbol",) + coordinate_tags
    if any(key not in block or not isinstance(block[key], list) for key in required):
        raise UnsupportedStructure("An explicit site loop with element symbols and fractional x, y, z is required.")
    symbols = block["_atom_site_type_symbol"]
    count = len(symbols)
    if count < 1 or count > MAX_ATOMS:
        raise UnsupportedStructure("The supported size is 1 to 400 explicit atomic sites.")
    if any(len(block[key]) != count for key in required):
        raise UnsupportedStructure("Site-loop columns must have equal lengths.")
    if any(not isinstance(symbol, str) or symbol not in atomic_numbers or symbol == "X" for symbol in symbols):
        raise UnsupportedStructure("Use canonical element symbols (for example C, B, Mo); mixed species, charges and isotope labels are unsupported.")
    coordinates = np.array([
        [_numeric(value, "Fractional coordinate") for value in block[key]]
        for key in coordinate_tags
    ]).T
    if np.any(np.abs(coordinates) > 1e6):
        raise UnsupportedStructure("Fractional coordinates above 1000000 in magnitude are unsupported.")
    if any(key.startswith("_atom_site_cartn_") for key in block):
        raise UnsupportedStructure("CIFs containing Cartesian site coordinates are unsupported; provide fractional coordinates only.")
    issues: list[dict[str, Any]] = []
    if not _validate_site_metadata(block, count):
        issues.append(_issue("ASSUMED_FULL_OCCUPANCY", "info", "Occupancies were omitted; every explicit site is assumed fully occupied.", atom_indices=list(range(count))))
    _validate_site_multiplicity(block, [1] * count)
    atoms = Atoms(symbols=symbols, scaled_positions=np.mod(coordinates, 1.0), cell=cell, pbc=True)
    return atoms, issues


def _contact_order(contact: dict[str, Any]) -> tuple:
    """Rank bounded contact evidence by severity, distance, then stable identity."""
    overlap = not contact["is_self_image"] and contact["distance_angstrom"] <= OVERLAP_TOLERANCE
    return (
        not overlap,
        contact["distance_angstrom"],
        contact["is_self_image"],
        contact["i"],
        contact["j"],
        *contact["shift"],
    )


def _contact_record(
    i: int,
    j: int,
    elements: list[str],
    shift: np.ndarray,
    distance: float,
    *,
    is_self_image: bool = False,
) -> dict[str, Any]:
    """Build one retained JSON contact after numeric screening is complete."""
    return {
        "i": int(i),
        "j": int(j),
        "element_i": elements[int(i)],
        "element_j": elements[int(j)],
        "shift": np.asarray(shift, dtype=int).tolist(),
        "distance_angstrom": float(distance),
        "is_self_image": is_self_image,
    }


def _pair_chunks(count: int, chunk_size: int = 2048):
    """Yield upper-triangle index pairs without allocating quadratic arrays."""
    if chunk_size < 1:
        raise ValueError("Pair chunk size must be positive.")
    buffer_i = np.empty(chunk_size, dtype=np.intp)
    buffer_j = np.empty(chunk_size, dtype=np.intp)
    used = 0
    for i in range(max(0, count - 1)):
        start = i + 1
        while start < count:
            take = min(chunk_size - used, count - start)
            buffer_i[used:used + take] = i
            buffer_j[used:used + take] = np.arange(start, start + take, dtype=np.intp)
            used += take
            start += take
            if used == chunk_size:
                yield buffer_i.copy(), buffer_j.copy()
                used = 0
    if used:
        yield buffer_i[:used].copy(), buffer_j[:used].copy()


def _distances(atoms: Atoms, threshold: float) -> tuple[dict[str, Any], list[dict[str, Any]], int, list[dict[str, Any]]]:
    cell = np.asarray(atoms.cell)
    elements = atoms.get_chemical_symbols()
    reduced, operation = minkowski_reduce(cell, pbc=True)
    # A reduced basis has its shortest vector among its basis vectors. This
    # explicitly includes self-images, which an ordinary NxN distance matrix
    # would otherwise omit along its zero diagonal.
    index = int(np.argmin(np.linalg.norm(reduced, axis=1)))
    self_distance = float(np.linalg.norm(reduced[index]))
    self_shift = np.asarray(operation[index], dtype=int)
    self_representative = _contact_record(
        0, 0, elements, self_shift, self_distance, is_self_image=True
    )
    minimum = self_representative
    contacts: list[dict[str, Any]] = []

    def retain_contacts(entries: list[dict[str, Any]]) -> None:
        # Keep memory bounded independently of the number of screened pairs.
        # Later overlaps or shorter pairs can displace earlier ordinary ones.
        nonlocal contacts
        contacts = sorted([*contacts, *entries], key=_contact_order)[:MAX_CONTACTS]

    contact_count = 0
    overlap_count = 0
    short_pair_count = 0
    overlap_representative = None
    short_representative = None
    overlap_sites: set[int] = set()
    short_sites: set[int] = set()
    inverse = np.linalg.inv(cell)
    for ii, jj in _pair_chunks(len(atoms)):
        original = atoms.positions[jj] - atoms.positions[ii]
        vectors, lengths = find_mic(original, reduced, pbc=True)
        shifts = np.rint((vectors - original) @ inverse).astype(int)

        nearest_index = int(np.argmin(lengths))
        if lengths[nearest_index] < minimum["distance_angstrom"]:
            minimum = _contact_record(
                ii[nearest_index], jj[nearest_index], elements, shifts[nearest_index],
                lengths[nearest_index]
            )

        overlap_mask = lengths <= OVERLAP_TOLERANCE
        if np.any(overlap_mask):
            overlap_indices = np.flatnonzero(overlap_mask)
            overlap_count += len(overlap_indices)
            overlap_sites.update(map(int, ii[overlap_indices]))
            overlap_sites.update(map(int, jj[overlap_indices]))
            candidate = overlap_indices[int(np.argmin(lengths[overlap_indices]))]
            if (overlap_representative is None
                    or lengths[candidate] < overlap_representative["distance_angstrom"]):
                overlap_representative = _contact_record(
                    ii[candidate], jj[candidate], elements, shifts[candidate], lengths[candidate]
                )

        short_mask = lengths < threshold
        if np.any(short_mask):
            short_indices = np.flatnonzero(short_mask)
            short_pair_count += len(short_indices)
            contact_count += len(short_indices)
            short_sites.update(map(int, ii[short_indices]))
            short_sites.update(map(int, jj[short_indices]))
            candidate = short_indices[int(np.argmin(lengths[short_indices]))]
            if (short_representative is None
                    or lengths[candidate] < short_representative["distance_angstrom"]):
                short_representative = _contact_record(
                    ii[candidate], jj[candidate], elements, shifts[candidate], lengths[candidate]
                )

            # Only the best MAX_CONTACTS entries in a chunk can enter the
            # bounded global result. Numeric arrays carry all other pairs.
            order = np.lexsort((
                shifts[short_indices, 2],
                shifts[short_indices, 1],
                shifts[short_indices, 0],
                jj[short_indices],
                ii[short_indices],
                lengths[short_indices],
                ~overlap_mask[short_indices],
            ))
            retained = short_indices[order[:MAX_CONTACTS]]
            retain_contacts([
                _contact_record(ii[k], jj[k], elements, shifts[k], lengths[k])
                for k in retained
            ])
    if self_distance < threshold:
        contact_count += len(atoms)
        retain_contacts([
            _contact_record(i, i, elements, self_shift, self_distance, is_self_image=True)
            for i in range(min(len(atoms), MAX_CONTACTS))
        ])
    # Neither dense overlaps nor many shorter self-images may hide another
    # distance issue's witness. These witnesses include the global minimum,
    # and need at most two distinct records (shortest pair and self-image).
    reserved = {
        (entry["i"], entry["j"]): entry
        for entry in (minimum, overlap_representative, short_representative, self_representative)
        if entry is not None and entry["distance_angstrom"] < threshold
    }
    remaining = [entry for entry in contacts if (entry["i"], entry["j"]) not in reserved]
    contacts = sorted(list(reserved.values()) + remaining[:MAX_CONTACTS - len(reserved)],
                      key=_contact_order)
    issues = []
    if overlap_count:
        issues.append(_issue("OVERLAPPING_SITES", "error", f"{overlap_count} distinct site pair(s) overlap within {OVERLAP_TOLERANCE:g} angstrom, including periodic images. Sites have been preserved.", atom_indices=sorted(overlap_sites), contact_count=overlap_count, representative_contact=overlap_representative))
    if short_pair_count:
        issues.append(_issue("SHORT_DISTANCE", "warning", f"{short_pair_count} distinct site pair(s) have a nearest image below the {threshold:g} angstrom screening threshold. This is an element-independent heuristic, not a bond or stability judgment.", atom_indices=sorted(short_sites), contact_count=short_pair_count, representative_contact=short_representative))
    if self_distance < threshold:
        issues.append(_issue("SELF_IMAGE_CONTACT", "warning", f"Each site has a periodic image only {self_distance:.6g} angstrom away. Inspect the cell dimensions and units.", atom_indices=list(range(len(atoms))), contact_count=len(atoms), representative_contact=self_representative))
    return minimum, contacts, contact_count, issues


def _image_shift(value: Any, description: str) -> np.ndarray:
    """Validate one absolute display-image shift."""
    array = np.asarray(value)
    if array.shape != (3,):
        raise ValueError(f"{description} must contain exactly three integers.")
    try:
        numeric = array.astype(float)
    except (TypeError, ValueError, OverflowError):
        raise ValueError(f"{description} must contain exactly three integers.") from None
    if not np.isfinite(numeric).all() or not np.equal(numeric, np.rint(numeric)).all():
        raise ValueError(f"{description} must contain exactly three integers.")
    return np.rint(numeric).astype(int)


def measure_atom_pair(
    report: dict[str, Any],
    i: int,
    j: int,
    first_shift: tuple[int, int, int] | list[int] = (0, 0, 0),
    second_shift: tuple[int, int, int] | list[int] = (0, 0, 0),
) -> dict[str, Any]:
    """Measure two displayed images and the sites' true minimum image.

    The two nested contact records can be passed directly to
    :func:`slab_preflight.plotting.structure_figure` as ``selected_contact``.
    Their ``shift`` is the relative original-lattice image shift from ``i`` to
    ``j``; ``start_shift`` and ``end_shift`` locate the displayed endpoints.
    """
    positions = np.asarray(report.get("positions"), dtype=float)
    cell = np.asarray(report.get("cell"), dtype=float)
    elements = report.get("elements")
    if (positions.ndim != 2 or positions.shape[1:] != (3,) or cell.shape != (3, 3)
            or not isinstance(elements, list) or len(elements) != len(positions)
            or not np.isfinite(positions).all() or not np.isfinite(cell).all()):
        raise ValueError("Measurement requires a complete finite CalcLens report.")
    for index, name in ((i, "First atom index"), (j, "Second atom index")):
        if (isinstance(index, (bool, np.bool_))
                or not isinstance(index, (int, np.integer))
                or not 0 <= int(index) < len(positions)):
            raise ValueError(f"{name} is outside the report's atom index range.")
    i, j = int(i), int(j)
    if i == j:
        raise ValueError("Select two distinct atom indices for a pair measurement.")
    first = _image_shift(first_shift, "First display shift")
    second = _image_shift(second_shift, "Second display shift")
    pbc = np.asarray(report.get("periodic_axes", [True, True, True]), dtype=bool)
    if pbc.shape != (3,):
        raise ValueError("The report's periodic-axis metadata must contain three values.")
    try:
        inverse = np.linalg.inv(cell)
    except np.linalg.LinAlgError:
        raise ValueError("Measurement requires a nonsingular cell.") from None

    base = positions[j] - positions[i]
    displayed_shift = second - first
    displayed_vector = base + displayed_shift @ cell
    mic_vector, mic_distance = find_mic(base, cell, pbc=pbc)
    mic_shift = np.rint((mic_vector - base) @ inverse).astype(int)

    def contact(
        relative_shift: np.ndarray,
        start_shift: np.ndarray,
        end_shift: np.ndarray,
        vector: np.ndarray,
        distance: float,
        kind: str,
    ) -> dict[str, Any]:
        record = _contact_record(i, j, elements, relative_shift, distance)
        record.update({
            "start_shift": start_shift.tolist(),
            "end_shift": end_shift.tolist(),
            "displacement_cartesian": np.asarray(vector, dtype=float).tolist(),
            "distance_kind": kind,
        })
        return record

    return {
        "i": i,
        "j": j,
        "element_i": elements[i],
        "element_j": elements[j],
        "displayed": contact(
            displayed_shift, first, second, displayed_vector,
            float(np.linalg.norm(displayed_vector)), "displayed"
        ),
        "minimum_image": contact(
            mic_shift, first, first + mic_shift, mic_vector,
            float(mic_distance), "minimum_image"
        ),
    }


def analyze_cif(data: str | bytes, short_distance: float = 1.0, normal_axis: str = "c") -> dict[str, Any]:
    """Return JSON-compatible geometric observations, without modifying input.

    Distances use all three periodic directions, counting one nearest image per
    unordered site pair and one shortest self-image per site. Up to 200 contact
    records are retained, prioritizing overlaps then shorter distances while
    preserving minimum-distance and self-image evidence below the threshold.
    Each distance issue also includes an exact count and representative contact;
    this is not a complete coordination/bond list.

    The explicitly selected a, b or c lattice vector must be perpendicular to
    the other two vectors. Gap screening follows that fractional coordinate;
    it does not infer the physical slab normal from the geometry.
    """
    threshold = _numeric(short_distance, "Short-distance threshold")
    if not 0.1 <= threshold <= 3.0:
        raise UnsupportedStructure("Short-distance threshold must be between 0.1 and 3.0 angstrom.")
    if not isinstance(normal_axis, str) or normal_axis.lower() not in ("a", "b", "c"):
        raise UnsupportedStructure("Select the candidate slab-normal lattice axis explicitly as a, b, or c.")
    normal_axis = normal_axis.lower()
    normal_index = "abc".index(normal_axis)
    in_plane_indices = [index for index in range(3) if index != normal_index]
    in_plane_axes = ["abc"[index] for index in in_plane_indices]
    atoms, issues = _read_cif(data, normal_axis)
    try:
        minimum, contacts, contact_count, distance_issues = _distances(atoms, threshold)
    except (ValueError, RuntimeError, np.linalg.LinAlgError):
        raise UnsupportedStructure("Periodic geometry could not be resolved reliably for this cell.") from None
    issues.extend(distance_issues)
    scaled = atoms.get_scaled_positions(wrap=True)
    heights = np.sort(scaled[:, normal_index])
    gaps = np.diff(np.r_[heights, heights[0] + 1.0])
    largest = int(np.argmax(gaps))
    gap_fraction = float(gaps[largest])
    c_height = float(abs(np.dot(atoms.cell[2], np.cross(atoms.cell[0], atoms.cell[1]))) / np.linalg.norm(np.cross(atoms.cell[0], atoms.cell[1])))
    plane_cross = np.cross(atoms.cell[in_plane_indices[0]], atoms.cell[in_plane_indices[1]])
    normal_height = float(abs(np.dot(atoms.cell[normal_index], plane_cross)) / np.linalg.norm(plane_cross))
    nuclei_gap = gap_fraction * normal_height
    nuclei_thickness = max(0.0, normal_height - nuclei_gap)
    second_gap = float(np.sort(gaps)[-2] * normal_height) if len(gaps) > 1 else 0.0
    if nuclei_gap < AMBIGUOUS_GAP_MIN or gap_fraction <= AMBIGUOUS_GAP_MAX_FRACTION + 1e-12:
        issues.append(_issue("AMBIGUOUS_SLAB", "warning", f"The largest {normal_axis}-direction nuclei gap is below 3 angstrom or at most half the normal repeat height. A single isolated slab cannot be inferred from this geometric screening heuristic.", area_id="normal_gap"))
    if second_gap >= COMPETING_GAP_MIN and second_gap >= COMPETING_GAP_RATIO * nuclei_gap - 1e-12:
        issues.append(_issue("MULTIPLE_LARGE_GAPS", "warning", f"More than one substantial {normal_axis}-direction gap exists. A multilayer, multiple slabs, or a different orientation may be present; the chosen gap is not a unique physical vacuum assignment.", area_id="normal_gap"))
    gap_review_required = any(issue["code"] in ("AMBIGUOUS_SLAB", "MULTIPLE_LARGE_GAPS") for issue in issues)
    issues.extend([
        _issue("GEOMETRY_ONLY", "info", "This report measures supplied nuclei and cell geometry. It does not establish material stability, bonding, physical dimensionality, or calculation accuracy."),
        _issue("VACUUM_CONVERGENCE", "info", "The largest nuclei gap is not an electron-density vacuum boundary. Whether the vacuum is sufficient requires convergence tests for the intended calculation.", area_id="normal_gap"),
    ])
    return {
        "schema_version": "1.1",
        "formula": atoms.get_chemical_formula(),
        "atom_count": len(atoms),
        "elements": atoms.get_chemical_symbols(),
        "cell": np.asarray(atoms.cell).tolist(),
        "positions": atoms.positions.tolist(),
        "scaled_positions": scaled.tolist(),
        "periodic_axes": [True, True, True],
        "normal_axis": normal_axis,
        "normal_axis_index": normal_index,
        "in_plane_axes": in_plane_axes,
        "review_required": any(issue["severity"] in ("warning", "error") for issue in issues),
        "gap_review_required": gap_review_required,
        "applicability": {
            "gap_interpretation": "review_required" if gap_review_required else "geometric_candidate",
            "review_required": gap_review_required,
        },
        "criteria": {
            "short_distance_threshold_angstrom": threshold,
            "short_distance_comparison": "<",
            "overlap_tolerance_angstrom": OVERLAP_TOLERANCE,
            "overlap_comparison": "<=",
            "perpendicular_angle_tolerance_degree": PERPENDICULAR_ANGLE_TOLERANCE,
            "ambiguous_gap_min_angstrom": AMBIGUOUS_GAP_MIN,
            "ambiguous_gap_max_fraction": AMBIGUOUS_GAP_MAX_FRACTION,
            "competing_gap_min_angstrom": COMPETING_GAP_MIN,
            "competing_gap_ratio": COMPETING_GAP_RATIO,
        },
        "units": {"length": "angstrom", "angle": "degree"},
        "metrics": {
            "minimum_distance_angstrom": minimum["distance_angstrom"],
            "minimum_pair": minimum,
            "c_height_angstrom": c_height,
            "normal_height_angstrom": normal_height,
            "nuclei_thickness_angstrom": nuclei_thickness,
            "nuclei_gap_angstrom": nuclei_gap,
            "gap_fraction": gap_fraction,
            "gap_start_fraction": float(heights[largest]),
            "gap_end_fraction": float(heights[(largest + 1) % len(heights)]),
            "second_largest_gap_angstrom": second_gap,
        },
        "short_distance_threshold_angstrom": threshold,
        "short_contacts": contacts,
        "short_contact_count": contact_count,
        "short_contacts_truncated": contact_count > MAX_CONTACTS,
        "issues": issues,
        "assumptions": [
            "Exactly one explicitly expanded P1 structure with full occupancy and fractional coordinates.",
            f"{normal_axis} is perpendicular to the {'-'.join(in_plane_axes)} plane; {normal_axis} is the user-supplied candidate slab-normal direction.",
            "All three cell directions are periodic for distance screening.",
            "CIF cell lengths are in angstrom and angles in degrees; reported uncertainties are not propagated.",
        ],
        "limitations": [
            "No energy, electronic structure, bonds, forces, stability, or convergence calculation is performed.",
            "The thickness is a nuclei-center span; an ideal planar monolayer has zero nuclei-span thickness.",
            "The largest cyclic nuclei gap may be an interlayer gap or empty space in a molecule or bulk cell. Physical slab assignment is not verified.",
            "Ambiguity and short-distance thresholds are screening heuristics; absence of warnings is not validation.",
            "Screening counts one nearest image per unordered site pair and one shortest self-image per site. The contact list retains at most 200 records, prioritizing overlaps then shorter distances and preserving minimum-distance and self-image evidence when below the threshold.",
        ],
    }
