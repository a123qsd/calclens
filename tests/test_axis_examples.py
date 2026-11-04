"""Physical geometry is invariant under cyclic relabeling of lattice axes."""

from pathlib import Path

import pytest

from slab_preflight.core import UnsupportedStructure, analyze_cif


EXAMPLES = Path(__file__).resolve().parents[1] / "examples"


@pytest.mark.parametrize("axis,filename", [("a", "mos2_a_normal.cif"), ("b", "mos2_b_normal.cif"), ("c", "mos2.cif")])
def test_axis_permuted_mos2_has_identical_physical_metrics(axis, filename):
    reference = analyze_cif((EXAMPLES / "mos2.cif").read_text(), normal_axis="c")
    report = analyze_cif((EXAMPLES / filename).read_text(), normal_axis=axis)
    assert report["normal_axis"] == axis
    assert report["atom_count"] == 3
    assert report["elements"] == reference["elements"]
    for key in ("minimum_distance_angstrom", "nuclei_thickness_angstrom", "nuclei_gap_angstrom", "gap_fraction", "normal_height_angstrom"):
        assert report["metrics"][key] == pytest.approx(reference["metrics"][key], abs=1e-8)
    assert report["metrics"]["normal_height_angstrom"] == pytest.approx(20)
    assert report["metrics"]["nuclei_thickness_angstrom"] == pytest.approx(3.12)
    assert report["metrics"]["nuclei_gap_angstrom"] == pytest.approx(16.88)
    assert not any(issue["severity"] in ("warning", "error") for issue in report["issues"])


@pytest.mark.parametrize("filename", ["mos2_a_normal.cif", "mos2_b_normal.cif"])
def test_axis_permuted_example_rejects_incorrect_default_c_normal(filename):
    with pytest.raises(UnsupportedStructure):
        analyze_cif((EXAMPLES / filename).read_text())
