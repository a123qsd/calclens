"""Actual small molecular SCF sources, independent Cube readback and reproduction."""
import importlib.util
import json
from pathlib import Path

import numpy as np
import pytest

from slab_preflight.density import density_difference, parse_cube

ROOT = Path(__file__).resolve().parents[1]
CASE = ROOT / "examples" / "research_cases" / "h2_density"
SPEC = importlib.util.spec_from_file_location("prepare_density_case", ROOT / "scripts" / "prepare_density_case.py")
PREPARE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(PREPARE)


def test_real_h2_case_sources_and_scf_matrix_checks_are_consistent():
    case = json.loads((CASE / "case.json").read_text())
    assert case["pyscf_version"] == "2.12.0"
    assert "actual local SCF" in case["source_status"]
    assert case["a_indices"] == [1] and case["b_indices"] == [2]
    assert "ghost" in case["common_basis"]
    for state, electrons, spin_squared in zip(case["scf"], [2, 1, 1], [0, .75, .75], strict=True):
        assert state["converged"] is True
        assert state["electrons"] == electrons
        assert sum(state["alpha_beta_electrons"]) == electrons
        assert state["overlap_electron_count"] == pytest.approx(electrons, abs=1e-10)
        assert state["energy_hartree"] == pytest.approx(state["independent_energy_hartree"], abs=1e-10)
        assert state["stationary_commutator_norm"] < 1e-8
        assert state["spin_squared"] == pytest.approx(spin_squared, abs=1e-10)
        assert state["ao_count"] == 2
        log = (CASE / f"{state['role'].lower()}.log").read_text()
        assert "converged SCF energy" in log
        assert "Independent CPU matrix checks" in log
        assert "/Users/" not in log


def test_real_case_independent_cpu_readback_and_source_hashes_pass_without_pyscf():
    report = PREPARE.check_case(CASE)
    assert report["status"] == "passed"
    assert report["sources_sha256_verified"] == 10
    assert report["shape"] == [49, 49, 49]
    assert report["maximum_density_difference_error_e_per_angstrom3"] < 1e-12
    # This checks this fixed finite-grid example, not general density convergence.
    assert abs(report["difference_integral_e"]) < 1e-5


def test_actual_h2_difference_has_accumulation_and_depletion_with_frozen_subsets():
    case = json.loads((CASE / "case.json").read_text())
    fields = [parse_cube((CASE / name).read_bytes(), kind="density", units="e/bohr^3", source_name=name)
              for name in ("ab.cube", "a.cube", "b.cube")]
    assert [len(field.atom_numbers) for field in fields] == [2, 1, 1]
    np.testing.assert_allclose(fields[0].atom_positions_angstrom, [[5.63, 6, 6], [6.37, 6, 6]], atol=1e-12)
    result = density_difference(*fields, a_indices=[1], b_indices=[2], method=case["common_method"],
                                reference_conditions=case["reference_conditions"], frozen_geometry=True)
    assert result.grid.values.max() > 0
    assert result.grid.values.min() < 0
    assert result.grid.values[24, 24, 24] > 0
    assert result.execution["effective_device"] == "cpu"


def test_optional_actual_pyscf_regeneration_reproduces_the_scf_states(tmp_path):
    pyscf = pytest.importorskip("pyscf", reason="Optional regeneration requires the isolated PySCF environment")
    if pyscf.__version__ != "2.12.0":
        pytest.skip("Reference regeneration explicitly requires PySCF 2.12.0")
    result = PREPARE.regenerate(tmp_path, points=17)
    assert result["status"] == "passed"
    regenerated = json.loads((tmp_path / "case.json").read_text())
    reference = json.loads((CASE / "case.json").read_text())
    assert regenerated["grid"]["shape"] == [17, 17, 17]
    assert [state["energy_hartree"] for state in regenerated["scf"]] == pytest.approx(
        [state["energy_hartree"] for state in reference["scf"]], abs=1e-10)
