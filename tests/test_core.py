"""Independent geometric expectations, periodic references, and input guards."""

from itertools import product
from pathlib import Path
import runpy

import numpy as np
import pytest

from slab_preflight.core import UnsupportedStructure, analyze_cif


ROOT = Path(__file__).resolve().parents[1]
EXAMPLES = ROOT / "examples"
GENERATOR = runpy.run_path(str(ROOT / "scripts" / "generate_examples.py"))
make_cif = GENERATOR["cif"]


def load(name):
    return (EXAMPLES / name).read_text(encoding="utf-8")


def codes(report):
    return {issue["code"] for issue in report["issues"]}


def brute_periodic_minimum(cell, fractional, extent=3):
    """Explicit lattice enumeration, independent of ASE/MIC implementation."""
    fractional = np.asarray(fractional)
    shifts = np.array(list(product(range(-extent, extent + 1), repeat=3)))
    best = np.inf
    for i, first in enumerate(fractional):
        for j, second in enumerate(fractional):
            valid_shifts = shifts[np.any(shifts != 0, axis=1)] if i == j else shifts
            vectors = (second - first + valid_shifts) @ np.asarray(cell)
            best = min(best, float(np.linalg.norm(vectors, axis=1).min()))
    return best


@pytest.mark.parametrize(
    "name,count,nearest,thickness,gap",
    [
        ("graphene.cif", 2, 2.46 / np.sqrt(3), 0.0, 20.0),
        ("hbn.cif", 2, 2.50 / np.sqrt(3), 0.0, 20.0),
        ("mos2.cif", 3, np.sqrt(3.18**2 / 3 + 1.56**2), 3.12, 16.88),
    ],
)
def test_ideal_models_have_analytical_geometry(name, count, nearest, thickness, gap):
    report = analyze_cif(load(name))
    assert report["atom_count"] == count
    assert report["metrics"]["minimum_distance_angstrom"] == pytest.approx(nearest, abs=1e-8)
    assert report["metrics"]["nuclei_thickness_angstrom"] == pytest.approx(thickness, abs=1e-8)
    assert report["metrics"]["nuclei_gap_angstrom"] == pytest.approx(gap, abs=1e-8)
    assert not any(issue["severity"] == "error" for issue in report["issues"])
    assert "OVERLAPPING_SITES" not in codes(report)
    assert "SHORT_DISTANCE" not in codes(report)


def test_hexagonal_distance_uses_periodic_images_not_cartesian_wrapping():
    report = analyze_cif(load("graphene.cif"))
    actual = report["metrics"]["minimum_distance_angstrom"]
    assert actual == pytest.approx(
        brute_periodic_minimum(report["cell"], report["scaled_positions"]), abs=1e-9
    )


@pytest.mark.parametrize("name", ["graphene_duplicate.cif", "graphene_boundary_duplicate.cif"])
def test_duplicate_sites_are_retained_and_detected(name):
    report = analyze_cif(load(name))
    assert report["atom_count"] == 3
    assert len(report["positions"]) == 3
    assert report["metrics"]["minimum_distance_angstrom"] == pytest.approx(0, abs=1e-9)
    assert "OVERLAPPING_SITES" in codes(report)
    assert any(issue["severity"] == "error" for issue in report["issues"])


def test_anomalous_short_contact_has_correct_unit():
    report = analyze_cif(load("graphene_short_contact.cif"))
    assert report["metrics"]["minimum_distance_angstrom"] == pytest.approx(0.0492)
    assert "SHORT_DISTANCE" in codes(report)
    assert "OVERLAPPING_SITES" not in codes(report)


def test_boundary_crossing_sandwich_keeps_thickness_and_gap():
    regular = analyze_cif(load("mos2.cif"))["metrics"]
    wrapped = analyze_cif(load("mos2_wrapped.cif"))["metrics"]
    for field in ("minimum_distance_angstrom", "nuclei_thickness_angstrom", "nuclei_gap_angstrom"):
        assert wrapped[field] == pytest.approx(regular[field], abs=1e-9)
    # Ordinary max(z)-min(z) would incorrectly report an almost cell-wide layer.
    report = analyze_cif(load("mos2_wrapped.cif"))
    assert np.ptp(np.asarray(report["positions"])[:, 2]) > 16
    assert wrapped["nuclei_thickness_angstrom"] == pytest.approx(3.12)


@pytest.mark.parametrize("offset", [(0.12, 0.83, 0.47), (7.25, -2.50, 0.501), (0, 0, 1)])
def test_translation_invariance_including_out_of_cell_fractional_sites(offset):
    original = analyze_cif(load("mos2.cif"))
    shifted = np.array(original["scaled_positions"]) + offset
    sites = [(element, *xyz, 1) for element, xyz in zip(original["elements"], shifted)]
    report = analyze_cif(make_cif("shifted", (3.18, 3.18, 20, 90, 90, 120), sites))
    for field in ("minimum_distance_angstrom", "nuclei_thickness_angstrom", "nuclei_gap_angstrom"):
        assert report["metrics"][field] == pytest.approx(original["metrics"][field], abs=1e-8)


def test_lengths_are_angstrom_and_scale_linearly():
    sites = [("Mo", 0, 0, 0.5, 1), ("S", 1 / 3, 2 / 3, 0.578, 1), ("S", 1 / 3, 2 / 3, 0.422, 1)]
    first = analyze_cif(make_cif("one", (3.18, 3.18, 20, 90, 90, 120), sites))
    second = analyze_cif(make_cif("two", (6.36, 6.36, 40, 90, 90, 120), sites))
    for field in ("minimum_distance_angstrom", "nuclei_thickness_angstrom", "nuclei_gap_angstrom", "c_height_angstrom"):
        assert second["metrics"][field] == pytest.approx(2 * first["metrics"][field], abs=1e-8)


@pytest.mark.parametrize("seed", [3, 12, 41, 123])
def test_skew_in_plane_cells_against_explicit_periodic_enumeration(seed):
    rng = np.random.default_rng(seed)
    a, b = rng.uniform(2, 6, size=2)
    gamma = rng.uniform(35, 140)
    xyz = rng.uniform(size=(5, 3))
    xyz[:, 2] = 0.42 + 0.16 * xyz[:, 2]
    sites = [("C", *point, 1) for point in xyz]
    report = analyze_cif(make_cif("skew", (a, b, 20, 90, 90, gamma), sites))
    expected = brute_periodic_minimum(report["cell"], report["scaled_positions"], extent=4)
    assert report["metrics"]["minimum_distance_angstrom"] == pytest.approx(expected, abs=1e-9)


def test_extremely_skew_basis_uses_nonlocal_periodic_image():
    # b is nearly 0.9a; the shortest lattice vector needs more than ±1 shifts.
    b = np.hypot(9.0, 0.1)
    gamma = np.degrees(np.arctan2(0.1, 9.0))
    report = analyze_cif(make_cif("very_skew", (10, b, 20, 90, 90, gamma), [("C", 0, 0, 0.5, 1)]))
    expected = brute_periodic_minimum(report["cell"], report["scaled_positions"], extent=12)
    assert report["metrics"]["minimum_distance_angstrom"] == pytest.approx(expected, abs=1e-8)
    assert report["metrics"]["minimum_distance_angstrom"] < 1.01


def test_single_atom_cell_detects_short_periodic_self_image():
    report = analyze_cif(load("tiny_self_image.cif"))
    assert report["atom_count"] == 1
    assert report["metrics"]["minimum_distance_angstrom"] == pytest.approx(0.5)
    assert "SELF_IMAGE_CONTACT" in codes(report)
    assert any(contact["is_self_image"] for contact in report["short_contacts"])
    assert "OVERLAPPING_SITES" not in codes(report)


def test_two_atom_minimum_can_still_be_a_self_image():
    sites = [("C", 0, 0, 0.4, 1), ("C", 0, 0, 0.6, 1)]
    report = analyze_cif(make_cif("self", (0.5, 3, 20, 90, 90, 90), sites))
    assert report["metrics"]["minimum_distance_angstrom"] == pytest.approx(0.5)
    assert report["metrics"]["minimum_pair"]["i"] == report["metrics"]["minimum_pair"]["j"]


def test_reported_image_shifts_reconstruct_contact_distances():
    sites = [("C", 0.1, 0.2, 0.45, 1), ("C", 0.9, 0.8, 0.55, 1), ("N", 0.01, 0.99, 0.5, 1)]
    report = analyze_cif(make_cif("witness", (3, 3.2, 20, 90, 90, 15), sites), short_distance=3)
    positions, cell = np.asarray(report["positions"]), np.asarray(report["cell"])
    for pair in [report["metrics"]["minimum_pair"], *report["short_contacts"]]:
        displacement = positions[pair["j"]] - positions[pair["i"]] + np.asarray(pair["shift"]) @ cell
        assert np.linalg.norm(displacement) == pytest.approx(pair["distance_angstrom"], abs=1e-9)


def test_contact_truncation_preserves_total_count_and_reports_limit():
    sites = [("C", 0, 0, 0.5, 1)] * 21
    report = analyze_cif(make_cif("many_overlaps", (3, 3, 20, 90, 90, 90), sites))
    assert report["atom_count"] == 21
    assert report["short_contact_count"] == 21 * 20 // 2
    assert len(report["short_contacts"]) == 200
    assert report["short_contacts_truncated"] is True
    assert "OVERLAPPING_SITES" in codes(report)


def test_multiple_large_empty_intervals_require_review():
    report = analyze_cif(load("bilayer_graphene.cif"))
    assert report["metrics"]["nuclei_thickness_angstrom"] == pytest.approx(8)
    assert report["metrics"]["nuclei_gap_angstrom"] == pytest.approx(12)
    assert "MULTIPLE_LARGE_GAPS" in codes(report)


def test_no_unique_vacuum_gap_requires_review():
    report = analyze_cif(load("no_unique_gap.cif"))
    assert report["metrics"]["nuclei_gap_angstrom"] == pytest.approx(2)
    assert "AMBIGUOUS_SLAB" in codes(report)


@pytest.mark.parametrize("filename", ["partial_occupancy.cif", "tilted_c.cif", "symmetry_unsupported.cif", "multiple_blocks.cif"])
def test_unsupported_examples_fail_explicitly(filename):
    with pytest.raises(UnsupportedStructure):
        analyze_cif(load(filename))


@pytest.mark.parametrize("replacement", ["?", ".", "nan", "inf"])
def test_unknown_or_nonfinite_fractional_coordinates_rejected(replacement):
    original = load("graphene.cif")
    with pytest.raises(UnsupportedStructure):
        analyze_cif(original.replace("C1 C 0 0 0.5 1", f"C1 C {replacement} 0 0.5 1"))


@pytest.mark.parametrize("length", ["0", "-1", "nan", "inf"])
def test_invalid_cell_length_rejected(length):
    with pytest.raises(UnsupportedStructure):
        analyze_cif(load("graphene.cif").replace("_cell_length_c 20", f"_cell_length_c {length}"))


def test_missing_p1_declaration_rejected():
    text = load("graphene.cif").replace("_space_group_IT_number 1\n", "").replace("_space_group_name_H-M_alt 'P 1'\n", "")
    with pytest.raises(UnsupportedStructure):
        analyze_cif(text)


def test_nonidentity_symmetry_operation_rejected():
    text = load("graphene.cif").replace("'x,y,z'", "'x,y,z'\n'-x,-y,-z'")
    with pytest.raises(UnsupportedStructure):
        analyze_cif(text)


def test_unknown_element_rejected_instead_of_guessed_from_label():
    with pytest.raises(UnsupportedStructure):
        analyze_cif(load("graphene.cif").replace("C1 C 0", "C1 Xx 0"))


def test_duplicate_labels_do_not_deduplicate_positions():
    text = load("graphene.cif").replace("C2 C", "C1 C")
    report = analyze_cif(text)
    assert report["atom_count"] == 2
    assert report["metrics"]["minimum_distance_angstrom"] == pytest.approx(2.46 / np.sqrt(3), abs=1e-8)


def test_occupancy_omission_is_documented_assumption():
    text = load("graphene.cif").replace("_atom_site_occupancy\n", "")
    text = "\n".join(line.rsplit(" ", 1)[0] if line.startswith(("C1 ", "C2 ")) else line for line in text.splitlines())
    report = analyze_cif(text)
    assert report["atom_count"] == 2
    assert report["assumptions"]


def test_cif_standard_uncertainty_numbers_are_parsed():
    text = load("graphene.cif").replace("_cell_length_a 2.46", "_cell_length_a 2.46(1)").replace("C1 C 0 0 0.5 1", "C1 C 0 0 0.500(3) 1")
    report = analyze_cif(text)
    assert report["metrics"]["minimum_distance_angstrom"] == pytest.approx(2.46 / np.sqrt(3), abs=1e-8)


def test_large_atom_count_is_rejected():
    sites = [("C", i / 401, 0, 0.5, 1) for i in range(401)]
    with pytest.raises(UnsupportedStructure):
        analyze_cif(make_cif("too_many", (100, 100, 20, 90, 90, 90), sites))


def test_oversized_text_is_rejected():
    with pytest.raises(UnsupportedStructure):
        analyze_cif("#" * (2 * 1024 * 1024 + 1))


@pytest.mark.parametrize("threshold", [0, -1, float("nan"), float("inf"), 3.1])
def test_invalid_threshold_rejected(threshold):
    with pytest.raises(ValueError):
        analyze_cif(load("graphene.cif"), short_distance=threshold)


def test_contact_threshold_changes_warning_without_changing_geometry():
    low = analyze_cif(load("graphene.cif"), short_distance=1)
    high = analyze_cif(load("graphene.cif"), short_distance=1.5)
    assert "SHORT_DISTANCE" not in codes(low)
    assert "SHORT_DISTANCE" in codes(high)
    assert high["metrics"]["minimum_distance_angstrom"] == low["metrics"]["minimum_distance_angstrom"]


def test_utf8_bytes_and_text_have_identical_results():
    text = load("graphene.cif")
    assert analyze_cif(text.encode("utf-8")) == analyze_cif(text)


def test_report_is_json_serializable_and_has_limitations():
    import json

    report = analyze_cif(load("mos2.cif"))
    encoded = json.dumps(report, allow_nan=False)
    assert json.loads(encoded)["atom_count"] == 3
    assert report["limitations"]
    assert report["assumptions"]


def test_committed_examples_are_reproducibly_generated():
    for filename, content in GENERATOR["examples"]().items():
        assert load(filename) == content
