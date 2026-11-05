"""Preparation is explicit and bounded; the analysis core remains P1-only."""
from hashlib import sha256
import json
from pathlib import Path

import numpy as np
import pytest
from ase.spacegroup import Spacegroup

from slab_preflight.core import UnsupportedStructure, analyze_cif
from slab_preflight.preparation import (
    OCCUPANCY_DEFAULT, OCCUPANCY_EXPLICIT, PreparationError, _STANDARD_HALL_SYMBOLS, prepare_p1,
)

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "examples/public_case/source/9011577-rev291877.cif"


def source_cif(*, group=2, sites=None, extra="", columns=(), values=None):
    sites = sites or [("C1", "C", 0.1, 0.2, 0.3)]
    header = """data_source
_cell_length_a 4
_cell_length_b 5
_cell_length_c 6
_cell_angle_alpha 90
_cell_angle_beta 90
_cell_angle_gamma 90
"""
    if group is not None:
        header += f"_space_group_IT_number {group}\n"
    header += extra + "\nloop_\n_atom_site_label\n_atom_site_type_symbol\n"
    header += "_atom_site_fract_x\n_atom_site_fract_y\n_atom_site_fract_z\n"
    header += "".join(f"{key}\n" for key in columns)
    for index, site in enumerate(sites):
        row = list(site)
        if columns:
            row.extend(values[index])
        header += " ".join(map(str, row)) + "\n"
    return header.encode()


def test_public_graphite_expands_to_four_exact_deposited_sites_without_slab_edits():
    original = SOURCE.read_bytes()
    with pytest.raises(UnsupportedStructure):
        analyze_cif(original)
    prepared = prepare_p1(original)
    assert original == SOURCE.read_bytes()
    assert prepared.cif == prepare_p1(original).cif
    report = analyze_cif(prepared.cif)
    assert report["atom_count"] == 4
    assert prepared.source_site_count == 2
    assert prepared.prepared_site_count == 4
    assert prepared.source_spacegroup_number == 194
    assert prepared.occupancy_policy == OCCUPANCY_DEFAULT
    assert prepared.source_sha256 == sha256(original).hexdigest()
    metadata = prepared.metadata()
    assert metadata["source_cell"] == metadata["prepared_cell"] == [2.464, 2.464, 6.711, 90, 90, 120]
    assert metadata["symmetry_operation_count"] == 24
    assert metadata["prepared_sha256"] == sha256(prepared.cif).hexdigest()
    assert "omitted" in " ".join(metadata["warnings"])
    assert b"C3 C 0.33333 0.66667 0.25 1" in prepared.cif
    assert b"C4 C 0.66667 0.33334 0.75 1" in prepared.cif


def test_standard_group_without_operations_is_expanded_and_full_occupancy_retained():
    raw = source_cif(columns=("_atom_site_occupancy",), values=[(1,)])
    result = prepare_p1(raw)
    assert result.prepared_site_count == 2
    assert result.occupancy_policy == OCCUPANCY_EXPLICIT
    assert "generated" in " ".join(result.warnings)
    assert analyze_cif(result.cif)["atom_count"] == 2
    fcc = source_cif(group=225, sites=[("Na1", "Na", 0, 0, 0)]).replace(
        b"_cell_length_b 5\n_cell_length_c 6", b"_cell_length_b 4\n_cell_length_c 4",
    )
    assert prepare_p1(fcc).prepared_site_count == 4


@pytest.mark.parametrize("occupancy", ["?", ".", 0.5, 0, 1.01, "nan", "inf"])
def test_unknown_partial_and_nonfinite_occupancy_never_receive_default(occupancy):
    raw = source_cif(columns=("_atom_site_occupancy",), values=[(occupancy,)])
    with pytest.raises(PreparationError, match="[Oo]ccupancy|finite"):
        prepare_p1(raw)


@pytest.mark.parametrize("tag", ["_atom_site_disorder_group", "_atom_site_disorder_assembly"])
@pytest.mark.parametrize("value", ["?", 1, "A"])
def test_disorder_and_unknown_disorder_are_rejected(tag, value):
    with pytest.raises(PreparationError, match="Disordered|unknown"):
        prepare_p1(source_cif(columns=(tag,), values=[(value,)]))


@pytest.mark.parametrize("tag", [
    "_space_group_ssg_name", "_cell_modulation_dimension", "_cell_wave_vector_seq_id",
    "_atom_site_subsystem_code", "_space_group_symop_magn_operation.xyz",
])
def test_modulated_composite_and_magnetic_metadata_are_rejected(tag):
    with pytest.raises(PreparationError, match="Modulated|magnetic"):
        prepare_p1(source_cif(extra=f"{tag} 1"))


@pytest.mark.parametrize("extra", [
    "_symmetry_Int_Tables_number 1",
    "_space_group_name_H-M_alt 'P 1'",
    "_space_group_name_Hall 'P 1'",
    "_symmetry_space_group_setting 2",
    "_space_group_IT_coordinate_system_code 2",
    "_space_group_crystal_system cubic",
    "_symmetry_cell_setting rhombohedral",
    "loop_\n_space_group_symop_operation_xyz\n'x,y,z'",
    "loop_\n_space_group_symop_operation_xyz\n'x,y,z'\n'x,y,z'",
    "loop_\n_space_group_symop_operation_xyz\n'x,y,z'\n'-x,-y,z'",
    "loop_\n_space_group_symop_operation_xyz\n'x,y,z'\n'-x,-y,-z+1/2'",
])
def test_conflicting_incomplete_or_alternate_symmetry_metadata_is_rejected(extra):
    with pytest.raises(PreparationError, match="[Cc]onflict|setting|standard|ambiguous"):
        prepare_p1(source_cif(extra=extra))


def test_operation_expressions_are_validated_before_ase_expansion():
    for operation in ("2x,y,z", "x+garbage,y,z", "x,y", "x+1/0,y,z", "x,x,z"):
        with pytest.raises(PreparationError):
            prepare_p1(source_cif(extra=(
                "loop_\n_space_group_symop_operation_xyz\n'x,y,z'\n'" + operation + "'"
            )))
    raw = source_cif(extra="loop_\n_space_group_symop_operation_xyz\n'x,y,z'\n'-x,-y,-z'")
    assert prepare_p1(raw).prepared_site_count == 2


def test_explicit_declaration_is_required_and_hall_only_standard_declaration_is_unambiguous():
    with pytest.raises(PreparationError, match="required"):
        prepare_p1(source_cif(group=None))
    raw = source_cif(group=None, extra="_space_group_name_Hall '-P 1'")
    assert prepare_p1(raw).source_spacegroup_number == 2
    with pytest.raises(PreparationError, match="standard"):
        prepare_p1(source_cif(group=None, extra="_space_group_name_Hall 'unknown'"))


@pytest.mark.parametrize("name", ["unknown", "P 999", "R 3:R"])
def test_unknown_or_unsupported_hm_name_returns_preparation_error(name):
    with pytest.raises(PreparationError, match="standard-setting"):
        prepare_p1(source_cif(extra=f"_space_group_name_H-M_alt '{name}'"))


def test_geometry_multiple_blocks_duplicate_aliases_and_malformed_site_columns_are_rejected():
    raw = source_cif()
    for invalid in (
        raw + b"\ndata_second\n_a 1\n",
        raw.replace(b"_cell_angle_beta 90", b"_cell_angle_beta 89"),
        raw.replace(b"_cell_length_a 4", b"_cell_length_a 4\n_cell.length_a 4"),
        raw.replace(b"C1 C 0.1 0.2 0.3", b"C1 Fe3+ 0.1 0.2 0.3"),
        raw.replace(b"C1 C 0.1 0.2 0.3", b"C1 C ? 0.2 0.3"),
        raw.replace(b"C1 C 0.1 0.2 0.3", b"C1 C 1000001 0.2 0.3"),
        raw.replace(b"_atom_site_fract_x", b"_atom_site_cartn_x"),
    ):
        with pytest.raises(PreparationError):
            prepare_p1(invalid)
    with pytest.raises(PreparationError, match="geometry"):
        prepare_p1(source_cif(group=225))


def test_symmetry_equivalent_source_sites_are_rejected_instead_of_silently_merged():
    raw = source_cif(sites=[("C1", "C", 0.1, 0.2, 0.3), ("C2", "C", 0.9, 0.8, 0.7)])
    with pytest.raises(PreparationError, match="equivalent|overlapping"):
        prepare_p1(raw)


def test_multiplicity_is_checked_and_expansion_cap_is_enforced():
    with pytest.raises(PreparationError, match="multiplicity"):
        prepare_p1(source_cif(columns=("_atom_site_symmetry_multiplicity",), values=[(1,)]))
    assert prepare_p1(source_cif(
        columns=("_atom_site_symmetry_multiplicity",), values=[(2,)],
    )).prepared_site_count == 2
    sites = [(f"C{i}", "C", 0.01 + i * 0.0001, 0.123, 0.27) for i in range(201)]
    with pytest.raises(PreparationError, match="400-site"):
        prepare_p1(source_cif(sites=sites))


@pytest.mark.parametrize("source", [b"", b"x" * (2 * 1024 * 1024 + 1), b"\x00CIF", b"#\\#CIF_2.0\n"])
def test_source_input_size_and_format_are_bounded(source):
    with pytest.raises(PreparationError):
        prepare_p1(source)


def test_hall_reference_table_covers_all_standard_groups_with_stable_facts():
    assert set(_STANDARD_HALL_SYMBOLS) == set(range(1, 231))
    assert _STANDARD_HALL_SYMBOLS[1] == ("P 1",)
    assert _STANDARD_HALL_SYMBOLS[2] == ("-P 1",)
    assert _STANDARD_HALL_SYMBOLS[194] == ("-P 6c 2c",)
    assert "-F 4 2 3" in _STANDARD_HALL_SYMBOLS[225]
    # Every standard group has a bounded, finite full operation set. The exact
    # reference-table fingerprint makes changes to these generated facts explicit.
    assert all(1 <= len(Spacegroup(number).get_symop()) <= 192 for number in _STANDARD_HALL_SYMBOLS)
    canonical = json.dumps(_STANDARD_HALL_SYMBOLS, sort_keys=True, separators=(",", ":")).encode()
    assert sha256(canonical).hexdigest() == "6d8aa8170e528a0d841c8cd2abddbc0828d874140e565b527d5271f943819061"
    assert np.isfinite(prepare_p1(SOURCE.read_bytes()).symmetry_tolerance_fractional)
