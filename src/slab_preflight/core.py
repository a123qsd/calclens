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
OVERLAP_TOLERANCE = 1e-5
PERPENDICULAR_ANGLE_TOLERANCE = 1e-5
AMBIGUOUS_GAP_MIN = 3.0
AMBIGUOUS_GAP_MAX_FRACTION = 0.5
COMPETING_GAP_MIN = 3.0
COMPETING_GAP_RATIO = 0.5


class UnsupportedStructure(ValueError):
    """The input cannot be interpreted within this tool's supported scope."""


def _issue(
    code: str,
    severity: str,
    message: str,
    *,
    atom_indices: list[int] | None = None,
    area_id: str | None = None,
) -> dict[str, Any]:
    issue: dict[str, Any] = {"code": code, "severity": severity, "message": message}
    if atom_indices is not None:
        issue["atom_indices"] = atom_indices
    if area_id is not None:
        issue["area_id"] = area_id
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
    block = blocks[0]
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
    cell = Cell.fromcellpar(parameters)
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
    if "_atom_site_occupancy" in block:
        occupancy = _values(block["_atom_site_occupancy"])
        if len(occupancy) != count or any(abs(_numeric(value, "Occupancy") - 1) > 1e-8 for value in occupancy):
            raise UnsupportedStructure("Only fully occupied sites (occupancy 1) are supported.")
    else:
        issues.append(_issue("ASSUMED_FULL_OCCUPANCY", "info", "Occupancies were omitted; every explicit site is assumed fully occupied.", atom_indices=list(range(count))))
    for key in ("_atom_site_disorder_assembly", "_atom_site_disorder_group"):
        if key in block and any(str(value) not in (".", "0") for value in _values(block[key])):
            raise UnsupportedStructure("Disordered or ambiguous site groups are unsupported.")
    if "_atom_site_symmetry_multiplicity" in block:
        values = _values(block["_atom_site_symmetry_multiplicity"])
        if any(_numeric(value, "Site multiplicity") != 1 for value in values):
            raise UnsupportedStructure("Site multiplicity must be 1 in an explicitly expanded P1 structure.")
    atoms = Atoms(symbols=symbols, scaled_positions=np.mod(coordinates, 1.0), cell=cell, pbc=True)
    return atoms, issues


def _distances(atoms: Atoms, threshold: float) -> tuple[dict[str, Any], list[dict[str, Any]], int, list[dict[str, Any]]]:
    cell = np.asarray(atoms.cell)
    elements = atoms.get_chemical_symbols()
    reduced, operation = minkowski_reduce(cell, pbc=True)
    # A reduced basis has its shortest vector among its basis vectors. This
    # explicitly includes self-images, which an ordinary NxN distance matrix
    # would otherwise omit along its zero diagonal.
    index = int(np.argmin(np.linalg.norm(reduced, axis=1)))
    self_distance = float(np.linalg.norm(reduced[index]))
    self_shift = np.asarray(operation[index], dtype=int).tolist()
    minimum = {"i": 0, "j": 0, "element_i": elements[0], "element_j": elements[0], "shift": self_shift, "distance_angstrom": self_distance, "is_self_image": True}
    contacts: list[dict[str, Any]] = []
    contact_count = 0
    overlap_count = 0
    short_pair_count = 0
    overlap_sites: set[int] = set()
    short_sites: set[int] = set()
    inverse = np.linalg.inv(cell)
    pairs_i, pairs_j = np.triu_indices(len(atoms), k=1)
    # Chunking bounds temporary arrays even for the maximum 400 sites.
    for offset in range(0, len(pairs_i), 2048):
        ii = pairs_i[offset:offset + 2048]
        jj = pairs_j[offset:offset + 2048]
        original = atoms.positions[jj] - atoms.positions[ii]
        vectors, lengths = find_mic(original, reduced, pbc=True)
        shifts = np.rint((vectors - original) @ inverse).astype(int)
        for i, j, length, shift in zip(ii, jj, lengths, shifts):
            entry = {"i": int(i), "j": int(j), "element_i": elements[i], "element_j": elements[j], "shift": shift.tolist(), "distance_angstrom": float(length), "is_self_image": False}
            if length < minimum["distance_angstrom"]:
                minimum = entry
            if length <= OVERLAP_TOLERANCE:
                overlap_count += 1
                overlap_sites.update((int(i), int(j)))
            if length < threshold:
                short_pair_count += 1
                short_sites.update((int(i), int(j)))
                contact_count += 1
                if len(contacts) < MAX_CONTACTS:
                    contacts.append(entry)
    if self_distance < threshold:
        for i in range(len(atoms)):
            contact_count += 1
            if len(contacts) < MAX_CONTACTS:
                contacts.append({"i": i, "j": i, "element_i": elements[i], "element_j": elements[i], "shift": self_shift, "distance_angstrom": self_distance, "is_self_image": True})
    issues = []
    if overlap_count:
        issues.append(_issue("OVERLAPPING_SITES", "error", f"{overlap_count} distinct site pair(s) overlap within {OVERLAP_TOLERANCE:g} angstrom, including periodic images. Sites have been preserved.", atom_indices=sorted(overlap_sites)))
    if short_pair_count:
        issues.append(_issue("SHORT_DISTANCE", "warning", f"{short_pair_count} distinct site pair(s) have a nearest image below the {threshold:g} angstrom screening threshold. This is an element-independent heuristic, not a bond or stability judgment.", atom_indices=sorted(short_sites)))
    if self_distance < threshold:
        issues.append(_issue("SELF_IMAGE_CONTACT", "warning", f"Each site has a periodic image only {self_distance:.6g} angstrom away. Inspect the cell dimensions and units.", atom_indices=list(range(len(atoms)))))
    return minimum, contacts, contact_count, issues


def analyze_cif(data: str | bytes, short_distance: float = 1.0, normal_axis: str = "c") -> dict[str, Any]:
    """Return JSON-compatible geometric observations, without modifying input.

    Distances use all three periodic directions. The contact list retains one
    nearest image per unordered site pair and one shortest self-image per site,
    up to 200 entries; it is not a complete coordination/bond list.

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
            "Contacts retain only one nearest image per unordered site pair and one shortest self-image per site, at most 200 records.",
        ],
    }
