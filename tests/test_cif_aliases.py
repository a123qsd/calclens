"""CIF spelling must never change a structure's supported physical semantics."""

from itertools import combinations

import pytest

from slab_preflight.core import UnsupportedStructure, analyze_cif
from slab_preflight.preparation import (
    OCCUPANCY_DEFAULT,
    OCCUPANCY_EXPLICIT,
    PreparationError,
    prepare_p1,
)


OCCUPANCY_TAGS = ("_atom_site_occupancy", "_atom_site.occupancy")
DISORDER_TAGS = (
    "_atom_site_disorder_group", "_atom_site.disorder_group",
    "_atom_site_disorder_assembly", "_atom_site.disorder_assembly",
)
MULTIPLICITY_TAGS = (
    "_atom_site_symmetry_multiplicity", "_atom_site.symmetry_multiplicity",
    "_atom_site_site_symmetry_multiplicity", "_atom_site.site_symmetry_multiplicity",
)
CRITICAL_TAGS = OCCUPANCY_TAGS + DISORDER_TAGS + MULTIPLICITY_TAGS
ENTRYPOINTS = ("analysis", "preparation")


def source_cif(*, columns=(), values=(), group=1, site_count=2, extra=""):
    """Build valid geometry; vary metadata without depending on parser internals."""
    lines = [
        "data_alias_regression",
        "_cell_length_a 4", "_cell_length_b 5", "_cell_length_c 20",
        "_cell_angle_alpha 90", "_cell_angle_beta 90", "_cell_angle_gamma 90",
        f"_space_group_IT_number {group}", extra,
        "loop_", "_atom_site_label", "_atom_site_type_symbol",
        "_atom_site_fract_x", "_atom_site_fract_y", "_atom_site_fract_z",
        *columns,
    ]
    sites = ("C1 C 0.1 0.2 0.3", "C2 C 0.4 0.3 0.3")
    suffix = " ".join(map(str, values))
    lines.extend(f"{site} {suffix}" for site in sites[:site_count])
    return ("\n".join(lines) + "\n").encode()


def evaluate(entrypoint, source):
    return analyze_cif(source) if entrypoint == "analysis" else prepare_p1(source)


def assert_rejected(entrypoint, source):
    error = UnsupportedStructure if entrypoint == "analysis" else PreparationError
    with pytest.raises(error):
        evaluate(entrypoint, source)


def geometry_report(entrypoint, result):
    return result if entrypoint == "analysis" else analyze_cif(result.cif)


@pytest.mark.parametrize("entrypoint", ENTRYPOINTS)
@pytest.mark.parametrize("tag", OCCUPANCY_TAGS)
@pytest.mark.parametrize("value", ["0.5", "?", ".", "nan", "inf", "-inf"])
def test_invalid_occupancy_never_becomes_an_omission(entrypoint, tag, value):
    assert_rejected(entrypoint, source_cif(columns=(tag,), values=(value,)))


@pytest.mark.parametrize("entrypoint", ENTRYPOINTS)
@pytest.mark.parametrize("tag", OCCUPANCY_TAGS)
def test_full_occupancy_aliases_preserve_geometry_and_explicit_policy(entrypoint, tag):
    baseline = evaluate(entrypoint, source_cif(columns=(OCCUPANCY_TAGS[0],), values=(1,)))
    result = evaluate(entrypoint, source_cif(columns=(tag,), values=(1,)))
    report = geometry_report(entrypoint, result)
    assert report == geometry_report(entrypoint, baseline)
    assert "ASSUMED_FULL_OCCUPANCY" not in {issue["code"] for issue in report["issues"]}
    if entrypoint == "preparation":
        assert result.occupancy_policy == OCCUPANCY_EXPLICIT
        assert "omitted" not in " ".join(result.warnings).lower()


@pytest.mark.parametrize("entrypoint", ENTRYPOINTS)
def test_actual_occupancy_omission_keeps_documented_default(entrypoint):
    result = evaluate(entrypoint, source_cif())
    if entrypoint == "analysis":
        assert "ASSUMED_FULL_OCCUPANCY" in {issue["code"] for issue in result["issues"]}
    else:
        assert result.occupancy_policy == OCCUPANCY_DEFAULT
        assert "omitted" in " ".join(result.warnings).lower()
    explicit = evaluate(entrypoint, source_cif(columns=(OCCUPANCY_TAGS[0],), values=(1,)))
    actual = geometry_report(entrypoint, result)
    expected = geometry_report(entrypoint, explicit)
    for key in ("atom_count", "cell", "scaled_positions", "metrics"):
        assert actual[key] == expected[key]


@pytest.mark.parametrize("entrypoint", ENTRYPOINTS)
@pytest.mark.parametrize("tag", DISORDER_TAGS)
@pytest.mark.parametrize("value", ["1", "A", "?"])
def test_disorder_aliases_reject_disordered_and_unknown_sites(entrypoint, tag, value):
    assert_rejected(entrypoint, source_cif(columns=(tag,), values=(value,)))


@pytest.mark.parametrize("entrypoint", ENTRYPOINTS)
@pytest.mark.parametrize("tag", DISORDER_TAGS)
@pytest.mark.parametrize("value", ["0", "."])
def test_explicit_no_disorder_aliases_preserve_geometry(entrypoint, tag, value):
    expected = geometry_report(entrypoint, evaluate(entrypoint, source_cif()))
    actual = evaluate(entrypoint, source_cif(columns=(tag,), values=(value,)))
    assert geometry_report(entrypoint, actual) == expected


@pytest.mark.parametrize("entrypoint", ENTRYPOINTS)
@pytest.mark.parametrize("tag", MULTIPLICITY_TAGS)
@pytest.mark.parametrize("value", ["2", "0", "?", ".", "nan", "inf"])
def test_p1_multiplicity_aliases_require_one_finite_image(entrypoint, tag, value):
    assert_rejected(entrypoint, source_cif(columns=(tag,), values=(value,)))


@pytest.mark.parametrize("entrypoint", ENTRYPOINTS)
@pytest.mark.parametrize("tag", MULTIPLICITY_TAGS)
def test_p1_unit_multiplicity_aliases_preserve_geometry(entrypoint, tag):
    expected = geometry_report(entrypoint, evaluate(entrypoint, source_cif()))
    result = evaluate(entrypoint, source_cif(columns=(tag,), values=(1,)))
    assert geometry_report(entrypoint, result) == expected


@pytest.mark.parametrize("tag", MULTIPLICITY_TAGS)
def test_preparation_multiplicity_matches_actual_group_two_orbit(tag):
    prepared = prepare_p1(source_cif(
        group=2, site_count=1, columns=(tag,), values=(2,),
    ))
    assert prepared.source_site_count == 1
    assert prepared.prepared_site_count == 2
    assert analyze_cif(prepared.cif)["atom_count"] == 2
    with pytest.raises(PreparationError):
        prepare_p1(source_cif(group=2, site_count=1, columns=(tag,), values=(1,)))


DUPLICATE_ALIASES = [
    (OCCUPANCY_TAGS, "1", "0.5"),
    (DISORDER_TAGS[:2], "0", "1"),
    (DISORDER_TAGS[2:], ".", "A"),
    *((pair, "1", "2") for pair in combinations(MULTIPLICITY_TAGS, 2)),
]


@pytest.mark.parametrize("entrypoint", ENTRYPOINTS)
@pytest.mark.parametrize("aliases,full,conflict", DUPLICATE_ALIASES)
@pytest.mark.parametrize("conflicting", [False, True], ids=["equal", "conflicting"])
def test_duplicate_semantic_site_aliases_are_always_ambiguous(
    entrypoint, aliases, full, conflict, conflicting,
):
    values = (full, conflict if conflicting else full)
    assert_rejected(entrypoint, source_cif(columns=aliases, values=values))


@pytest.mark.parametrize("entrypoint", ENTRYPOINTS)
@pytest.mark.parametrize("tag", CRITICAL_TAGS)
@pytest.mark.parametrize("shape", ["scalar", "short", "long"])
def test_critical_metadata_is_a_site_column_of_matching_length(entrypoint, tag, shape):
    value = "0" if "disorder" in tag else "1"
    if shape == "scalar":
        extra = f"{tag} {value}"
    else:
        count = 1 if shape == "short" else 3
        extra = f"loop_\n{tag}\n" + "\n".join([value] * count)
    assert_rejected(entrypoint, source_cif(extra=extra))


@pytest.mark.parametrize("entrypoint", ENTRYPOINTS)
@pytest.mark.parametrize("tag", CRITICAL_TAGS)
def test_single_site_does_not_make_scalar_critical_metadata_a_loop_column(entrypoint, tag):
    value = "0" if "disorder" in tag else "1"
    assert_rejected(entrypoint, source_cif(site_count=1, extra=f"{tag} {value}"))


@pytest.mark.parametrize("entrypoint", ENTRYPOINTS)
@pytest.mark.parametrize("different", [False, True], ids=["equal", "conflicting"])
@pytest.mark.parametrize("family", ["cell", "coordinate", "space_group"])
def test_duplicate_geometry_aliases_are_ambiguous(entrypoint, different, family):
    if family == "cell":
        source = source_cif(extra=f"_cell.length_a {5 if different else 4}")
    elif family == "space_group":
        source = source_cif(extra=f"_space_group.IT_number {2 if different else 1}")
    else:
        value = "0.8" if different else "0.1"
        source = source_cif(site_count=1, columns=("_atom_site.fract_x",), values=(value,))
    assert_rejected(entrypoint, source)


@pytest.mark.parametrize("entrypoint", ENTRYPOINTS)
@pytest.mark.parametrize("family", ["cell", "sites", "symmetry", "all"])
def test_documented_dotted_geometry_tags_have_identical_results(entrypoint, family):
    baseline = source_cif(
        columns=(OCCUPANCY_TAGS[0],), values=(1,),
        extra="loop_\n_space_group_symop_operation_xyz\n'x,y,z'",
    )
    source = baseline
    if family in ("cell", "all"):
        source = source.replace(b"_cell_length_", b"_cell.length_")
        source = source.replace(b"_cell_angle_", b"_cell.angle_")
    if family in ("sites", "all"):
        source = source.replace(b"_atom_site_", b"_atom_site.")
    if family in ("symmetry", "all"):
        source = source.replace(b"_space_group_IT_number", b"_space_group.IT_number")
        source = source.replace(
            b"_space_group_symop_operation_xyz", b"_space_group_symop.operation_xyz",
        )
    expected = geometry_report(entrypoint, evaluate(entrypoint, baseline))
    assert geometry_report(entrypoint, evaluate(entrypoint, source)) == expected


@pytest.mark.parametrize("entrypoint", ENTRYPOINTS)
@pytest.mark.parametrize("tag,value", [
    ("_atom_site.occupancy_value", "0.5"),
    ("_atom_site.disorder.group", "0"),
    ("_atom_site.symmetry.multiplicity", "1"),
])
def test_unsupported_critical_spellings_cannot_silently_change_policy(entrypoint, tag, value):
    assert_rejected(entrypoint, source_cif(columns=(tag,), values=(value,)))


@pytest.mark.parametrize("entrypoint", ENTRYPOINTS)
@pytest.mark.parametrize("tag,value", [
    ("_atom_site_occupancy_su", "0.01"),
    ("_atom_site.occupancy_su", "0.01"),
    ("_atom_site_adp_type", "Uiso"),
    ("_atom_site.adp_type", "Uiso"),
])
def test_unrelated_site_metadata_does_not_become_a_critical_alias(entrypoint, tag, value):
    baseline = source_cif(columns=(OCCUPANCY_TAGS[0],), values=(1,))
    source = source_cif(columns=(OCCUPANCY_TAGS[0], tag), values=(1, value))
    expected = geometry_report(entrypoint, evaluate(entrypoint, baseline))
    assert geometry_report(entrypoint, evaluate(entrypoint, source)) == expected


LEGACY_SYMMETRY_ALIASES = (
    ("_space_group_IT_number", "_symmetry_Int_Tables_number", "1", "2"),
    ("_space_group_name_H-M_alt", "_symmetry_space_group_name_H-M", "'P 1'", "'P -1'"),
    ("_space_group_name_Hall", "_symmetry_space_group_name_Hall", "'P 1'", "'-P 1'"),
    ("_space_group_symop_operation_xyz", "_symmetry_equiv_pos_as_xyz", "'x,y,z'", "'-x,-y,-z'"),
)


@pytest.mark.parametrize("entrypoint", ENTRYPOINTS)
@pytest.mark.parametrize("canonical,legacy,value,conflict", LEGACY_SYMMETRY_ALIASES)
@pytest.mark.parametrize("different", [False, True], ids=["equal", "conflicting"])
def test_true_legacy_symmetry_alias_duplicates_are_rejected(
    entrypoint, canonical, legacy, value, conflict, different,
):
    source = source_cif().replace(b"_space_group_IT_number 1\n", b"")
    declarations = f"{canonical} {value}\n{legacy} {conflict if different else value}\n"
    if canonical != "_space_group_IT_number":
        declarations += "_space_group_IT_number 1\n"
    source = source.replace(b"loop_\n", declarations.encode() + b"loop_\n", 1)
    assert_rejected(entrypoint, source)


@pytest.mark.parametrize("entrypoint", ENTRYPOINTS)
@pytest.mark.parametrize("canonical,legacy,value,conflict", LEGACY_SYMMETRY_ALIASES)
def test_sole_true_legacy_symmetry_alias_preserves_original_geometry(
    entrypoint, canonical, legacy, value, conflict,
):
    original = source_cif()
    if canonical == "_space_group_IT_number":
        source = original.replace(b"_space_group_IT_number 1", f"{legacy} {value}".encode())
    else:
        source = source_cif(extra=f"{legacy} {value}")
    expected = geometry_report(entrypoint, evaluate(entrypoint, original))
    assert geometry_report(entrypoint, evaluate(entrypoint, source)) == expected


@pytest.mark.parametrize("entrypoint", ENTRYPOINTS)
@pytest.mark.parametrize("tag", [
    "_space_group_IT_coordinate_system_code", "_space_group.IT_coordinate_system_code",
    "_space_group_origin_choice", "_space_group.origin_choice",
])
@pytest.mark.parametrize("value", ["2", "?", "."])
def test_nonstandard_or_unknown_origin_and_coordinate_settings_are_rejected(
    entrypoint, tag, value,
):
    assert_rejected(entrypoint, source_cif(extra=f"{tag} {value}"))


@pytest.mark.parametrize("entrypoint", ENTRYPOINTS)
@pytest.mark.parametrize("tag", [
    "_space_group_IT_coordinate_system_code", "_space_group.IT_coordinate_system_code",
    "_space_group_origin_choice", "_space_group.origin_choice",
])
def test_explicit_standard_origin_and_coordinate_settings_preserve_geometry(entrypoint, tag):
    source = source_cif(extra=f"{tag} 1")
    expected = geometry_report(entrypoint, evaluate(entrypoint, source_cif()))
    assert geometry_report(entrypoint, evaluate(entrypoint, source)) == expected
