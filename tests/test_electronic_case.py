"""Real molecular calculation artifacts remain traceable and consistently mapped.

These checks read the committed calculation; they never rerun PySCF in normal
CI or infer chemical accuracy from a small-basis demonstration.
"""

from hashlib import sha256
import json
from pathlib import Path
import runpy
import shutil

import numpy as np
import pytest

from slab_preflight.core import analyze_cif


ROOT = Path(__file__).resolve().parents[1]
DIRECTORY = ROOT / "examples" / "electronic_case"
CASE = runpy.run_path(str(ROOT / "scripts" / "prepare_electronic_case.py"))


def test_actual_molecular_case_has_converged_traceable_results():
    calculation = json.loads((DIRECTORY / "calculation.json").read_bytes())
    assert calculation["program"] == "PySCF"
    assert calculation["program_version"] == "2.12.0"
    assert calculation["method"] == "RHF"
    assert calculation["basis"] == "STO-3G"
    assert calculation["converged"] is True
    assert calculation["periodic_calculation"] is False
    assert calculation["geometry_optimization_performed"] is False
    assert calculation["electron_count"] == 10
    assert calculation["basis_function_count"] == 7
    assert calculation["charge"] == calculation["spin_2s"] == 0
    assert "converged SCF energy" in (DIRECTORY / "scf.log").read_text()
    assert len(calculation["references"]) >= 4
    assert "host" not in calculation and "platform" not in calculation


def test_independent_matrix_and_cube_readback_checks_pass_without_pyscf():
    result = CASE["check_case"](DIRECTORY)
    matrices = result["matrix_check"]
    assert matrices["electron_count_trace_ps"] == pytest.approx(10, abs=1e-10)
    assert matrices["energy_error_hartree"] < 1e-9
    assert matrices["roothaan_max_residual"] < 1e-7
    assert matrices["density_from_occupied_mos_max_error"] < 1e-10
    assert matrices["mo_orthonormality_max_error"] < 1e-10
    for field in result["ase_cube_check"].values():
        assert field["shape"] == [30, 30, 30]
        assert field["point_count"] == 27_000


def test_translated_molecule_is_p1_display_container_with_preserved_atom_order():
    report = analyze_cif((DIRECTORY / "water.cif").read_bytes(), normal_axis="c")
    assert report["elements"] == ["O", "H", "H"]
    assert report["atom_count"] == 3
    elements, original = CASE["source_atoms"]()
    assert elements == report["elements"]
    assert np.allclose(report["positions"], original + [6, 6, 6], atol=1e-10, rtol=0)
    expected_oh = np.sqrt(0.757**2 + 0.587**2)
    assert report["metrics"]["minimum_distance_angstrom"] == pytest.approx(expected_oh)
    assert report["metrics"]["normal_height_angstrom"] == pytest.approx(12)
    assert report["metrics"]["nuclei_thickness_angstrom"] == pytest.approx(0.587)


def test_real_charge_exports_have_distinct_methods_and_identical_cif_identity():
    cif_digest = sha256((DIRECTORY / "water.cif").read_bytes()).hexdigest()
    documents = [json.loads((DIRECTORY / f"charges_{method}.json").read_bytes())
                 for method in ("mulliken", "lowdin")]
    values = []
    for document in documents:
        assert document["schema_version"] == 1
        assert document["kind"] == "partial_charge"
        assert document["structure_sha256"] == cif_digest
        assert document["source"].startswith("PySCF 2.12.0")
        assert [(atom["index"], atom["element"]) for atom in document["atoms"]] == [
            (1, "O"), (2, "H"), (3, "H"),
        ]
        charges = np.array([atom["value"] for atom in document["atoms"]])
        assert np.isfinite(charges).all()
        assert charges.sum() == pytest.approx(0, abs=1e-10)
        assert charges[1] == pytest.approx(charges[2], abs=1e-9)
        values.append(charges)
    assert documents[0]["method"] != documents[1]["method"]
    assert np.max(np.abs(values[0] - values[1])) > 0.01


def test_density_and_homo_are_actual_bounded_scalar_exports_with_explicit_units():
    calculation = json.loads((DIRECTORY / "calculation.json").read_bytes())
    assert calculation["cube"]["density_units"] == "e/bohr^3"
    assert calculation["cube"]["orbital_units"] == "bohr^-3/2"
    assert calculation["cube"]["orbital_index_one_based"] == 5
    assert calculation["cube"]["orbital_occupation"] == 2
    density = CASE["read_cube_independently"](DIRECTORY / "density.cube")
    homo = CASE["read_cube_independently"](DIRECTORY / "homo.cube")
    assert density["data"].min() >= 0
    assert homo["data"].min() < 0 < homo["data"].max()
    assert np.allclose(density["atoms"].positions, homo["atoms"].positions, atol=1e-10)
    assert np.allclose(density["spacing"], homo["spacing"], atol=1e-10)
    for name in ("density.cube", "homo.cube"):
        path = DIRECTORY / name
        assert path.stat().st_size < 1024 * 1024
        counts = [int(line.split()[0]) for line in path.read_text().splitlines()[3:6]]
        assert counts == [30, 30, 30]  # Positive counts: spatial coordinates are Bohr.
    checks = json.loads((DIRECTORY / "independent_check.json").read_bytes())
    assert checks["atom_centered_quadrature"]["electron_count"] == pytest.approx(10, abs=1e-5)
    assert checks["matrix_check"]["energy_error_hartree"] < 1e-9


@pytest.mark.parametrize("filename", [
    "water.cif", "charges_lowdin.json", "homo.cube", "wavefunction.json", "source/water.xyz",
])
def test_check_rejects_any_changed_scientific_artifact(tmp_path, filename):
    case = tmp_path / "case"
    shutil.copytree(DIRECTORY, case)
    path = case / filename
    path.write_bytes(path.read_bytes() + b"\n")
    with pytest.raises(ValueError, match="SHA-256 mismatch"):
        CASE["check_case"](case)


def test_independent_matrix_check_detects_damaged_density_matrix():
    state = json.loads((DIRECTORY / "wavefunction.json").read_bytes())
    state["density_matrix"][0][0] += 0.1
    with pytest.raises(ValueError, match="electron count|energy|consistency"):
        CASE["independent_matrix_check"](state)
