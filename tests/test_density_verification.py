"""CPU verification checks bytes, settings, fields and their portable record."""

from copy import deepcopy
from hashlib import sha256

import pytest

from slab_preflight.density import parse_cube, planar_average
from slab_preflight.density_records import calculation_record, dataset_identity, validate_computation
from slab_preflight.density_verification import (
    verify_planar_record, verify_retained_difference, with_reproducibility,
)
from test_density_records import retained


def planar_record():
    _, entry, bundle, _, _ = retained()
    source = bundle["sources"]["AB"]
    item = {"id": "AB-total", "name": "AB total", "filename": source["filename"],
            "rawText": source["raw"], "kind": "density", "units": "e/angstrom^3",
            "source": "Synthetic analytic fixture"}
    grid = parse_cube(item["rawText"], kind="density", units=item["units"], source_name=item["filename"])
    profile = planar_average(grid, normal=[0, 0, 10])
    record = {"schema_version": 1, "operation": "planar_average",
              "dataset": dataset_identity(item, entry["sha256"], grid), "grid": grid.metadata(),
              "profile": profile, "execution": profile["execution"],
              "calculation": {"structure_sha256": entry["sha256"], "structure_normal_axis": "c",
                              "grid_plane_axis": 2, "normal_vector": [0, 0, 10],
                              "source_scalar_units": "e/angstrom^3", "output_scalar_units": "e/angstrom^3"}}
    return with_reproducibility(record), item, entry


def test_planar_verification_replays_captured_settings_and_preserves_historical_result():
    record, item, entry = planar_record()
    before = deepcopy(record)
    # Current UI normal is irrelevant to the captured original lattice direction.
    entry["normal_axis"] = "a"
    entry["analysis"]["report"]["normal_axis_index"] = 0
    report = verify_planar_record(record, item, entry)
    assert report["status"] == "passed"
    assert report["cpu_replay_execution"]["effective_device"] == "cpu"
    assert report["cpu_replay_integral_e"] == pytest.approx(8)
    assert report["source_identity_and_checksums"][0]["source_sha256"] == sha256(item["rawText"].encode()).hexdigest()
    assert report["captured_settings"]["normal_vector"] == [0, 0, 10]
    assert report["record_manifest_sha256"] == record["reproducibility"]["manifest_sha256"]
    assert record == before


@pytest.mark.parametrize("change", ["bytes", "normal", "units", "values", "integral", "manifest"])
def test_planar_verification_rejects_changed_bytes_settings_or_results(change):
    record, item, entry = planar_record()
    if change == "bytes":
        item["rawText"] += "\n"
    elif change == "normal":
        record["calculation"]["normal_vector"] = [0, 0, -10]
    elif change == "units":
        record["calculation"]["source_scalar_units"] = "e/bohr^3"
    elif change == "values":
        record["profile"]["average_e_per_angstrom3"][0] += 1
    elif change == "integral":
        record["profile"]["integration"]["cumulative_e"][-1] += 1
    else:
        record["reproducibility"]["manifest_sha256"] = "f" * 64
    with pytest.raises(ValueError):
        verify_planar_record(record, item, entry)


def test_difference_verification_checks_original_sources_result_and_3d_integrals():
    _, entry, bundle, item, _ = retained()
    record = with_reproducibility(calculation_record(bundle, item, entry))
    before = deepcopy(bundle)
    report = verify_retained_difference(bundle, item, entry, record)
    assert report["status"] == "passed"
    assert {source["role"] for source in report["source_identity_and_checksums"]} == {"AB", "A", "B"}
    assert report["comparison"]["maximum_absolute_grid_error_e_per_angstrom3"] == 0
    assert report["cpu_replay_integration"]["positive_voxel_integral_e"] == pytest.approx(2.4)
    assert report["captured_settings"]["source_scalar_units"] == "e/angstrom^3"
    assert bundle == before


@pytest.mark.parametrize("change", ["source", "result", "cumulative", "positive", "convention", "identity"])
def test_difference_verification_rejects_tampering(change):
    _, entry, bundle, item, _ = retained()
    if change == "source":
        bundle["sources"]["A"]["raw"] += "\n"
    elif change == "result":
        item["rawText"] += "\n"
    elif change == "identity":
        item["id"] = "other-result"
    elif change == "cumulative":
        bundle["computation"]["profile"]["integration"]["cumulative_e"][1] += 5
    elif change == "positive":
        bundle["computation"]["profile"]["integration"]["positive_voxel_integral_e"] += 5
    else:
        bundle["computation"]["profile"]["integration"]["convention"] = "unrecorded interpolation"
    with pytest.raises(ValueError):
        verify_retained_difference(bundle, item, entry)


def test_older_profiles_still_verify_without_rewriting_their_historical_execution():
    _, entry, bundle, item, replay = retained()
    del bundle["computation"]["profile"]["integration"]
    validate_computation(bundle, replay)
    before = deepcopy(bundle)
    assert verify_retained_difference(bundle, item, entry)["status"] == "passed"
    assert bundle == before
    _, entry, legacy, item, _ = retained(legacy=True)
    report = verify_retained_difference(legacy, item, entry)
    assert report["status"] == "passed" and report["warnings"]
    assert "orientation" in report["warnings"][0]


def test_planar_verification_dispatches_native_chgcar_normalization():
    from slab_preflight.desktop_sources import evaluate_source
    from test_chgcar import source, structure

    item = {"id": "vasp-total", "name": "VASP total density", "filename": "CHGCAR",
            "rawText": source().decode(), "kind": "density", "units": "e/angstrom^3",
            "source": "Synthetic VASP fixture", "source_format": "vasp-chgcar",
            "source_sha256": sha256(source()).hexdigest()}
    entry = {"sha256": "c" * 64, "normal_axis": "c", "analysis": {"report": structure()}}
    grid = evaluate_source(item, "volume", entry["analysis"]["report"], entry["sha256"])
    profile = planar_average(grid, normal=[0, 0, 4])
    record = with_reproducibility({
        "schema_version": 1, "operation": "planar_average", "grid": grid.metadata(),
        "dataset": dataset_identity(item, entry["sha256"], grid),
        "profile": profile, "execution": profile["execution"],
        "calculation": {"structure_sha256": entry["sha256"], "structure_normal_axis": "c",
                        "grid_plane_axis": 2, "normal_vector": [0, 0, 4],
                        "source_scalar_units": grid.original_units,
                        "output_scalar_units": grid.units},
    })
    verified = verify_planar_record(record, item, entry)
    assert verified["status"] == "passed"
    assert verified["cpu_replay_integral_e"] == pytest.approx(5.5)
    assert verified["cpu_replay_integration"]["cumulative_e"][-1] == pytest.approx(5.5)
