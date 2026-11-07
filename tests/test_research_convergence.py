"""Use committed actual electronic outputs; never run PySCF in normal CI."""

from hashlib import sha256
import json
from pathlib import Path
import runpy
import shutil

import numpy as np
import pytest

from slab_preflight.core import analyze_cif
from slab_preflight.research import (
    ResearchError, build_vacuum_cif, compare_convergence_series, convert_energy,
    load_convergence_series,
)

ROOT = Path(__file__).resolve().parents[1]
CASES = ROOT / "examples" / "research_cases"
SERIES = CASES / "hbn_vacuum"


def bundle(tmp_path):
    directory = tmp_path / "bundle"
    shutil.copytree(SERIES, directory)
    return directory, json.loads((directory / "series.json").read_bytes())


def save_manifest(directory, manifest):
    (directory / "series.json").write_text(json.dumps(manifest) + "\n")


def save_result(directory, case, result):
    path = directory / case["result"]["path"]
    path.write_text(json.dumps(result) + "\n")
    case["result"]["sha256"] = sha256(path.read_bytes()).hexdigest()


def update_artifact(directory, case, key, data):
    path = directory / case[key]["path"]
    path.write_bytes(data)
    case[key]["sha256"] = sha256(data).hexdigest()
    result = json.loads((directory / case["result"]["path"]).read_bytes())
    result["input_cif_sha256" if key == "cif" else "output_sha256"] = case[key]["sha256"]
    save_result(directory, case, result)


def test_actual_periodic_hbn_series_is_hash_bound_and_uses_measured_energies():
    report = compare_convergence_series(SERIES / "series.json")
    assert report["status"] == "accepted"
    assert report["fixed_conditions"]["periodic_dimensions"] == 3
    assert report["fixed_conditions"]["method"] == "RKS"
    assert report["fixed_conditions"]["kpoint_grid"] == [1, 1, 1]
    assert report["tolerance_mev_per_atom"] == 1
    assert report["recommended_sampled_vacuum_angstrom"] == 8
    assert report["excluded"] == []
    assert [case["status"] for case in report["cases"]] == ["normal"] * 3
    assert [case["energy_hartree"] for case in report["cases"]] == pytest.approx(
        [-12.558956805705, -12.559014710620, -12.558996454595], abs=1e-10)
    assert [row["delta_mev_per_atom"] for row in report["comparisons"]] == pytest.approx(
        [0.53945063, 0.24838588, 0], abs=1e-6)
    relative = [case["geometry"]["relative_cartesian_angstrom"] for case in report["cases"]]
    assert np.allclose(relative, [relative[0]] * 3, atol=1e-10, rtol=0)
    assert any("grid" in warning.lower() for warning in report["warnings"])


def test_stricter_chosen_tolerance_exposes_nonconvergence(tmp_path):
    directory, manifest = bundle(tmp_path)
    manifest["tolerance"]["value"] = 0.1
    save_manifest(directory, manifest)
    report = compare_convergence_series(directory / "series.json")
    assert report["status"] == "not_converged"
    assert report["recommended_sampled_vacuum_angstrom"] is None


@pytest.mark.parametrize("status", ["failure", "truncated", "unknown"])
def test_failed_incomplete_and_unknown_runs_are_preserved_but_excluded(tmp_path, status):
    directory, manifest = bundle(tmp_path)
    case = manifest["cases"][-1]
    result = json.loads((directory / case["result"]["path"]).read_bytes())
    result["status"] = status
    result["scf_converged"] = False
    save_result(directory, case, result)
    save_manifest(directory, manifest)
    report = compare_convergence_series(directory / "series.json")
    assert report["status"] == "insufficient_data"
    assert report["excluded"] == [case["id"]]
    assert report["cases"][-1]["status"] == status
    assert report["reference_id"] == "vacuum_12A"


def test_successful_metadata_cannot_hide_a_failed_original_scf(tmp_path):
    directory, manifest = bundle(tmp_path)
    case = manifest["cases"][0]
    raw = (directory / case["output"]["path"]).read_bytes()
    raw = raw.replace(b"converged SCF energy", b"SCF not converged; last energy")
    update_artifact(directory, case, "output", raw)
    save_manifest(directory, manifest)
    report = compare_convergence_series(directory / "series.json")
    assert report["status"] == "insufficient_data"
    assert case["id"] in report["excluded"]
    assert any("SCF" in reason for reason in report["cases"][0]["exclusion_reasons"])


def test_molecular_scf_log_cannot_claim_a_periodic_vacuum_series(tmp_path):
    directory, manifest = bundle(tmp_path)
    case = manifest["cases"][0]
    energy = json.loads((directory / case["result"]["path"]).read_bytes())["energy"]["value"]
    update_artifact(directory, case, "output", f"converged SCF energy = {energy:.12f}\n".encode())
    save_manifest(directory, manifest)
    report = compare_convergence_series(directory / "series.json")
    assert case["id"] in report["excluded"]
    assert any("periodic input" in reason for reason in report["cases"][0]["exclusion_reasons"])


def test_changed_electronic_condition_rejects_incomparable_series(tmp_path):
    directory, manifest = bundle(tmp_path)
    case = manifest["cases"][0]
    result = json.loads((directory / case["result"]["path"]).read_bytes())
    result["fixed_conditions"]["xc"] = "PBE"
    save_result(directory, case, result)
    save_manifest(directory, manifest)
    report = compare_convergence_series(directory / "series.json")
    assert report["status"] == "incomparable"
    assert not report["cases"][0]["comparable"]
    assert report["accepted"] == []


def test_changed_internal_geometry_rejects_incomparable_series(tmp_path):
    directory, manifest = bundle(tmp_path)
    case = manifest["cases"][0]
    path = directory / case["cif"]["path"]
    raw = path.read_bytes().replace(b"N2 N 0.333333333333 0.666666666667 0.500000000000",
                                  b"N2 N 0.333333333333 0.666666666667 0.510000000000")
    assert raw != path.read_bytes()
    update_artifact(directory, case, "cif", raw)
    save_manifest(directory, manifest)
    report = compare_convergence_series(directory / "series.json")
    assert report["status"] == "incomparable"
    assert any("geometry" in reason for reason in report["cases"][0]["exclusion_reasons"])


def test_explicit_total_energy_units_are_normalized_before_comparing(tmp_path):
    directory, manifest = bundle(tmp_path)
    case = manifest["cases"][0]
    result = json.loads((directory / case["result"]["path"]).read_bytes())
    result["energy"]["value"] = convert_energy(result["energy"]["value"], "hartree", "eV")
    result["energy"]["unit"] = "eV"
    save_result(directory, case, result)
    save_manifest(directory, manifest)
    assert compare_convergence_series(directory / "series.json")["status"] == "accepted"


def test_unlabelled_energy_is_never_guessed(tmp_path):
    directory, manifest = bundle(tmp_path)
    case = manifest["cases"][0]
    result = json.loads((directory / case["result"]["path"]).read_bytes())
    del result["energy"]["unit"]
    save_result(directory, case, result)
    save_manifest(directory, manifest)
    with pytest.raises(ResearchError, match="unit"):
        compare_convergence_series(directory / "series.json")


@pytest.mark.parametrize("key", ["source_cif", "cif", "output", "result"])
def test_every_changed_input_or_output_fails_hash_verification(tmp_path, key):
    directory, manifest = bundle(tmp_path)
    record = manifest["source_cif"] if key == "source_cif" else manifest["cases"][0][key]
    path = directory / record["path"]
    path.write_bytes(path.read_bytes() + b"\n")
    with pytest.raises(ResearchError, match="SHA-256"):
        compare_convergence_series(directory / "series.json")


@pytest.mark.parametrize("unsafe_path", ["../outside.log", "/tmp/outside.log", "C:\\outside.log",
                                         "nested/../../outside.log"])
def test_bundle_references_cannot_traverse_outside_selected_directory(tmp_path, unsafe_path):
    directory, manifest = bundle(tmp_path)
    manifest["cases"][0]["output"]["path"] = unsafe_path
    save_manifest(directory, manifest)
    with pytest.raises(ResearchError, match="inside"):
        compare_convergence_series(directory / "series.json")


def test_symlink_escape_is_rejected(tmp_path):
    directory, manifest = bundle(tmp_path)
    source = directory / manifest["cases"][0]["output"]["path"]
    outside = tmp_path / "outside.log"
    shutil.copy(source, outside)
    source.unlink()
    source.symlink_to(outside)
    with pytest.raises(ResearchError, match="inside"):
        compare_convergence_series(directory / "series.json")


def test_duplicate_vacua_do_not_count_as_independent_samples(tmp_path):
    directory, manifest = bundle(tmp_path)
    case = json.loads(json.dumps(manifest["cases"][0]))
    case["id"] = "same_vacuum_again"
    manifest["cases"].append(case)
    save_manifest(directory, manifest)
    assert compare_convergence_series(directory / "series.json")["status"] == "incomparable"


def test_duplicate_json_keys_and_nonfinite_tolerances_are_rejected(tmp_path):
    path = tmp_path / "series.json"
    path.write_bytes(b'{"schema_version": 1, "schema_version": 1}')
    with pytest.raises(ResearchError, match="Repeated"):
        load_convergence_series(path)
    path.write_bytes(b'{"schema_version": NaN}')
    with pytest.raises(ResearchError, match="Non-finite"):
        load_convergence_series(path)


@pytest.mark.parametrize("vacuum", [6, 12, 30])
@pytest.mark.parametrize("center", [0, 0.5, 0.98])
def test_vacuum_edit_preserves_wrapped_mos2_cartesian_internal_structure(vacuum, center):
    original = (ROOT / "examples" / "mos2_wrapped.cif").read_bytes()
    derived = build_vacuum_cif(original, vacuum, center_fraction=center)
    report = analyze_cif(derived)
    assert report["elements"] == ["Mo", "S", "S"]
    assert report["metrics"]["normal_height_angstrom"] == pytest.approx(vacuum + 3.12, abs=1e-9)
    assert report["metrics"]["nuclei_thickness_angstrom"] == pytest.approx(3.12, abs=1e-9)
    assert report["metrics"]["nuclei_gap_angstrom"] == pytest.approx(vacuum, abs=1e-9)
    z = np.array(report["scaled_positions"])[:, 2]
    relative_z = z - z[0]
    relative_z -= np.rint(relative_z)
    assert relative_z * (vacuum + 3.12) == pytest.approx([0, 1.56, -1.56], abs=1e-9)
    assert (ROOT / "examples" / "mos2_wrapped.cif").read_bytes() == original


@pytest.mark.parametrize("axis", ["a", "b", "c"])
def test_normal_axis_variants_preserve_layer_thickness(axis):
    name = "mos2.cif" if axis == "c" else f"mos2_{axis}_normal.cif"
    source = (ROOT / "examples" / name).read_bytes()
    result = analyze_cif(build_vacuum_cif(source, 10, normal_axis=axis), normal_axis=axis)
    assert result["metrics"]["nuclei_gap_angstrom"] == pytest.approx(10, abs=1e-8)
    assert result["metrics"]["nuclei_thickness_angstrom"] == pytest.approx(3.12, abs=1e-8)


def test_ambiguous_gap_and_unsupported_sites_require_explicit_preparation():
    for name in ("no_unique_gap.cif", "partial_occupancy.cif"):
        with pytest.raises(ResearchError):
            build_vacuum_cif((ROOT / "examples" / name).read_bytes(), 15)
    for vacuum in (0, -1, float("inf"), True):
        with pytest.raises(ResearchError):
            build_vacuum_cif((ROOT / "examples" / "hbn.cif").read_bytes(), vacuum)


def test_independent_periodic_matrix_and_geometry_checks_need_no_electronic_engine():
    verifier = runpy.run_path(str(ROOT / "scripts" / "verify_research_cases.py"))
    report = verifier["verify_all"]()
    assert len(report["cif_cases"]) == 10
    assert len(report["gaussian_cases"]) == 3
    assert report["convergence"]["status"] == "accepted"
    assert sum(case["status"] == "expected_rejection" for case in report["cif_cases"]) == 3


def test_independent_matrix_check_detects_corrupt_density_even_with_updated_hashes(tmp_path):
    directory, manifest = bundle(tmp_path)
    case = manifest["cases"][0]
    result = json.loads((directory / case["result"]["path"]).read_bytes())
    result["matrices"]["density"][0][0] += 0.1
    save_result(directory, case, result)
    save_manifest(directory, manifest)
    generator = runpy.run_path(str(ROOT / "scripts" / "prepare_convergence_case.py"))
    with pytest.raises(ValueError, match="electron"):
        generator["check_case"](directory)
