"""Selected slab normals and the link between issues and their geometric sites."""

from pathlib import Path
import runpy

from ase.cell import Cell
import numpy as np
import pytest

from slab_preflight import UnsupportedStructure, analyze_cif


ROOT = Path(__file__).resolve().parents[1]
make_cif = runpy.run_path(str(ROOT / "scripts" / "generate_examples.py"))["cif"]
PERMUTATIONS = {"a": [2, 0, 1], "b": [0, 2, 1], "c": [0, 1, 2]}


def load(name):
    return (ROOT / "examples" / name).read_text(encoding="utf-8")


def reoriented_cif(report, axis, translation=None):
    permutation = PERMUTATIONS[axis]
    cell = Cell(np.asarray(report["cell"])[permutation])
    fractional = np.asarray(report["scaled_positions"])[:, permutation]
    if translation is not None:
        fractional = fractional + np.asarray(translation)
    sites = [(element, *point, 1) for element, point in zip(report["elements"], fractional)]
    return make_cif("reoriented", cell.cellpar(), sites)


@pytest.mark.parametrize("axis", ["a", "b", "c"])
@pytest.mark.parametrize("filename", ["graphene.cif", "mos2.cif", "mos2_wrapped.cif"])
def test_permuted_slab_has_same_geometry_for_each_selected_normal(axis, filename):
    original = analyze_cif(load(filename))
    report = analyze_cif(reoriented_cif(original, axis), normal_axis=axis)
    assert report["normal_axis"] == axis
    assert report["normal_axis_index"] == "abc".index(axis)
    assert report["in_plane_axes"] == [other for other in "abc" if other != axis]
    for key in (
        "minimum_distance_angstrom", "normal_height_angstrom", "nuclei_thickness_angstrom",
        "nuclei_gap_angstrom", "gap_fraction", "second_largest_gap_angstrom",
    ):
        assert report["metrics"][key] == pytest.approx(original["metrics"][key], abs=1e-8)
    assert not report["gap_review_required"]
    assert not report["review_required"]
    assert report["applicability"]["gap_interpretation"] == "geometric_candidate"


@pytest.mark.parametrize("axis", ["a", "b", "c"])
def test_gap_survives_normal_translation_and_boundary_crossing(axis):
    original = analyze_cif(load("mos2.cif"))
    translation = [1.0, -2.0, 3.0]
    translation["abc".index(axis)] += 0.499
    report = analyze_cif(reoriented_cif(original, axis, translation), normal_axis=axis)
    assert report["metrics"]["nuclei_gap_angstrom"] == pytest.approx(16.88)
    assert report["metrics"]["nuclei_thickness_angstrom"] == pytest.approx(3.12)
    selected = np.asarray(report["scaled_positions"])[:, report["normal_axis_index"]]
    assert np.ptp(selected) > 0.8


@pytest.mark.parametrize("axis", ["a", "b"])
def test_legacy_c_height_keeps_its_physical_meaning(axis):
    original = analyze_cif(load("mos2.cif"))
    report = analyze_cif(reoriented_cif(original, axis), normal_axis=axis)
    cell = np.asarray(report["cell"])
    expected_c_height = abs(np.linalg.det(cell)) / np.linalg.norm(np.cross(cell[0], cell[1]))
    assert report["metrics"]["c_height_angstrom"] == pytest.approx(expected_c_height)
    assert report["metrics"]["c_height_angstrom"] == pytest.approx(3.18 * np.sin(np.pi / 3))
    assert report["metrics"]["normal_height_angstrom"] == pytest.approx(20.0)


def test_default_axis_preserves_existing_c_analysis():
    text = load("mos2.cif")
    assert analyze_cif(text) == analyze_cif(text, normal_axis="c")
    assert analyze_cif(text, normal_axis="C") == analyze_cif(text)


@pytest.mark.parametrize("axis", [None, 0, "", "auto", "z", "ab", " c "])
def test_axis_selection_is_explicit_and_validated(axis):
    with pytest.raises(UnsupportedStructure, match="a, b, or c"):
        analyze_cif(load("graphene.cif"), normal_axis=axis)


@pytest.mark.parametrize(
    "axis,angles",
    [("a", (90, 89, 90)), ("a", (90, 90, 89)),
     ("b", (89, 90, 90)), ("b", (90, 90, 89)),
     ("c", (89, 90, 90)), ("c", (90, 89, 90))],
)
def test_selected_axis_tilt_is_rejected(axis, angles):
    text = make_cif("tilted", (10, 10, 20, *angles), [("C", 0.5, 0.5, 0.5, 1)])
    with pytest.raises(UnsupportedStructure, match=f"selected {axis} axis must be perpendicular"):
        analyze_cif(text, normal_axis=axis)


@pytest.mark.parametrize("axis", ["a", "b"])
def test_wrong_default_axis_is_not_silently_auto_detected(axis):
    original = analyze_cif(load("mos2.cif"))
    text = reoriented_cif(original, axis)
    with pytest.raises(UnsupportedStructure, match="selected c axis"):
        analyze_cif(text)


@pytest.mark.parametrize("axis", ["a", "b", "c"])
def test_contacts_keep_elements_and_original_lattice_image_shifts(axis):
    original = analyze_cif(load("mos2.cif"))
    report = analyze_cif(reoriented_cif(original, axis), short_distance=3.0, normal_axis=axis)
    positions = np.asarray(report["positions"])
    cell = np.asarray(report["cell"])
    assert report["short_contacts"]
    for contact in [report["metrics"]["minimum_pair"], *report["short_contacts"]]:
        assert contact["element_i"] == report["elements"][contact["i"]]
        assert contact["element_j"] == report["elements"][contact["j"]]
        image_displacement = positions[contact["j"]] + np.asarray(contact["shift"]) @ cell - positions[contact["i"]]
        assert np.linalg.norm(image_displacement) == pytest.approx(contact["distance_angstrom"], abs=1e-9)


def test_duplicate_highlights_are_separate_from_merely_short_contacts():
    text = make_cif("distinct_causes", (10, 10, 20, 90, 90, 90), [
        ("C", 0, 0, 0.5, 1), ("C", 1, 0, 0.5, 1),
        ("H", 0.05, 0, 0.5, 1), ("N", 0.5, 0.5, 0.5, 1),
    ])
    report = analyze_cif(text, short_distance=0.9)
    issues = {issue["code"]: issue for issue in report["issues"]}
    assert report["atom_count"] == 4  # The duplicate record has not been removed.
    assert issues["OVERLAPPING_SITES"]["atom_indices"] == [0, 1]
    assert issues["SHORT_DISTANCE"]["atom_indices"] == [0, 1, 2]
    assert report["criteria"]["short_distance_threshold_angstrom"] == 0.9
    assert report["criteria"]["overlap_tolerance_angstrom"] == 1e-5
    assert report["criteria"]["overlap_comparison"] == "<="
    assert report["criteria"]["short_distance_comparison"] == "<"


def test_truncated_contact_table_still_highlights_all_involved_sites():
    sites = [("C", 0, 0, 0.5, 1)] * 30
    report = analyze_cif(make_cif("many_duplicates", (10, 10, 20, 90, 90, 90), sites))
    assert report["short_contacts_truncated"]
    assert report["short_contact_count"] == 435
    for issue in report["issues"]:
        if issue["code"] in ("OVERLAPPING_SITES", "SHORT_DISTANCE"):
            assert issue["atom_indices"] == list(range(30))


def test_self_image_issue_identifies_all_sites():
    text = make_cif("self_images", (0.5, 10, 20, 90, 90, 90), [
        ("C", 0, 0, 0.5, 1), ("N", 0, 0.5, 0.5, 1),
    ])
    report = analyze_cif(text)
    issue = next(item for item in report["issues"] if item["code"] == "SELF_IMAGE_CONTACT")
    assert issue["atom_indices"] == [0, 1]
    for contact in report["short_contacts"]:
        assert contact["is_self_image"]
        assert contact["element_i"] == contact["element_j"]


@pytest.mark.parametrize("axis", ["a", "b", "c"])
def test_gap_ambiguity_requires_review_for_every_axis(axis):
    text = make_cif("two_slabs", (3, 3, 20, 90, 90, 90), [
        ("C", 0, 0, 0.3, 1), ("C", 0, 0, 0.7, 1),
    ])
    original = analyze_cif(text)
    report = analyze_cif(reoriented_cif(original, axis), normal_axis=axis)
    assert report["gap_review_required"] is True
    assert report["review_required"] is True
    assert report["applicability"] == {"gap_interpretation": "review_required", "review_required": True}
    gap_issue = next(issue for issue in report["issues"] if issue["code"] == "MULTIPLE_LARGE_GAPS")
    assert gap_issue["area_id"] == "normal_gap"
    assert f"{axis}-direction" in gap_issue["message"]
    assert report["criteria"]["competing_gap_min_angstrom"] == 3.0
    assert report["criteria"]["competing_gap_ratio"] == 0.5


def test_gap_review_flag_is_not_a_general_safety_or_stability_pass():
    report = analyze_cif(load("graphene_duplicate.cif"))
    assert not report["gap_review_required"]
    assert report["review_required"]
    assert not report["applicability"]["review_required"]
    assert any(issue["code"] == "OVERLAPPING_SITES" for issue in report["issues"])
    assert any(issue["code"] == "GEOMETRY_ONLY" for issue in report["issues"])
    assert report["applicability"]["gap_interpretation"] == "geometric_candidate"
