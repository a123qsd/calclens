"""The public diffraction-derived example has auditable preparation and geometry."""

from hashlib import sha256
import json
from pathlib import Path
import runpy

import numpy as np
import pytest

from slab_preflight.core import UnsupportedStructure, analyze_cif


ROOT = Path(__file__).resolve().parents[1]
CASE = runpy.run_path(str(ROOT / "scripts" / "prepare_public_case.py"))
DIRECTORY = ROOT / "examples" / "public_case"


def test_public_source_stays_unmodified_and_requires_preparation():
    source = CASE["SOURCE"].read_bytes()
    assert sha256(source).hexdigest() == CASE["SOURCE_SHA256"]
    assert b"#$Revision: 291877 $" in source
    # Non-P1 source data must never be mistaken for two explicit carbon atoms.
    with pytest.raises(UnsupportedStructure):
        analyze_cif(source)


def test_expansion_preserves_four_sites_and_selects_one_two_atom_sheet():
    bulk, slab, policy = CASE["prepare_structures"](CASE["SOURCE"].read_bytes())
    assert len(bulk) == 4
    assert len(slab) == 2
    assert np.allclose(bulk.get_scaled_positions(), CASE["REFERENCE_BULK"], atol=1e-10)
    assert np.allclose(slab.get_scaled_positions(), CASE["REFERENCE_SLAB"], atol=1e-10)
    assert bulk.cell.cellpar()[2] == pytest.approx(6.711)
    assert slab.cell.cellpar()[2] == pytest.approx(20)
    assert "default 1.0" in policy
    text = CASE["explicit_p1"](slab, "test_sheet", "Unrelaxed source-derived sheet.")
    report = analyze_cif(text, normal_axis="c")
    assert report["atom_count"] == 2
    assert report["normal_axis"] == "c"
    assert "ASSUMED_FULL_OCCUPANCY" not in {issue["code"] for issue in report["issues"]}
    with pytest.raises(UnsupportedStructure):
        analyze_cif(text, normal_axis="a")
    with pytest.raises(UnsupportedStructure):
        analyze_cif(text, normal_axis="b")


@pytest.mark.parametrize("occupancy", [0.5, 0, "?", ".", float("nan"), float("inf")])
def test_preparation_rejects_partial_or_unknown_occupancy(occupancy):
    block = {"_atom_site_label": ["C1", "C2"], "_atom_site_occupancy": [occupancy, 1]}
    with pytest.raises(ValueError, match="occupancy|occupied"):
        CASE["validate_occupancy"](block)


def test_preparation_rejects_disorder_before_expansion():
    block = {"_atom_site_label": ["C1", "C2"], "_atom_site_disorder_group": ["1", "2"]}
    with pytest.raises(ValueError, match="Disordered"):
        CASE["validate_occupancy"](block)


def test_preparation_rejects_source_hash_changes():
    with pytest.raises(ValueError, match="SHA-256"):
        CASE["build_artifacts"](CASE["SOURCE"].read_bytes() + b"\n# edited\n")


def test_public_case_matches_independent_reference_and_bulk_warning():
    artifacts = CASE["build_artifacts"](CASE["SOURCE"].read_bytes())
    results = json.loads(artifacts["case_results.json"])
    benchmarks = results["benchmark"]["cases"]
    for case in benchmarks.values():
        for error in case["absolute_errors"].values():
            assert error < 1e-9
        assert case["short_contact_count"] == 0
        assert case["calclens_metrics"]["minimum_distance_angstrom"] == pytest.approx(
            CASE["A"] / np.sqrt(3), abs=3e-5,
        )
    bulk = benchmarks["graphite_p1.cif"]
    assert bulk["calclens_metrics"]["nuclei_gap_angstrom"] == pytest.approx(6.711 / 2)
    assert {"AMBIGUOUS_SLAB", "MULTIPLE_LARGE_GAPS"} <= set(bulk["issue_codes"])
    assert bulk["gap_review_required"] is True
    slab = benchmarks["graphene_from_graphite_p1.cif"]
    assert slab["calclens_metrics"]["nuclei_thickness_angstrom"] == pytest.approx(0)
    assert slab["calclens_metrics"]["nuclei_gap_angstrom"] == pytest.approx(20)
    assert slab["gap_review_required"] is False


def test_bundled_prepared_cifs_are_reproducible():
    artifacts = CASE["build_artifacts"](CASE["SOURCE"].read_bytes())
    # Numerical results carry the executing library versions; CIF coordinates
    # remain the source-preserving, version-independent preparation contract.
    for name in ("graphite_p1.cif", "graphene_from_graphite_p1.cif"):
        assert (DIRECTORY / name).read_text(encoding="utf-8") == artifacts[name]
