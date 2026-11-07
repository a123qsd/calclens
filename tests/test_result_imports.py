"""Public original outputs plus explicitly synthetic/modified parser edge cases."""
from copy import deepcopy
from hashlib import sha256
from io import StringIO
import json
import re
from pathlib import Path

import numpy as np
import pytest
from ase.io import read

from slab_preflight.research_logs import ResearchError, parse_log
from slab_preflight.result_geometry import BOHR_ANGSTROM, geometry_report
from slab_preflight.result_sources import output_record, read_output_record, result_entries, saved_output_records
from slab_preflight.structure_compare import compare_coordinates, energy_comparison

ROOT = Path(__file__).resolve().parents[1]
VASP = ROOT / "examples/research_cases/vasp_reference/OUTCAR_Ni_reference"
GAUSSIAN = ROOT / "examples/research_cases/gaussian_reference/dvb_gopt.out"


def test_public_outcar_original_has_distinct_energies_real_geometry_and_provenance():
    source = json.loads(VASP.with_name("sources.json").read_text())["files"][0]
    original = VASP.read_bytes()
    report = parse_log(original, source_name=VASP.name, source_url=source["source_url"])
    step = report["steps"][0]
    assert report["kind"] == "vasp_outcar" and report["status"] == "normal"
    assert report["program"]["version"] == "5.3.3"
    assert report["provenance"]["sha256"] == source["sha256"] == sha256(original).hexdigest()
    assert step["scf"]["status"] == "converged"
    assert len(step["energies"]) == 64
    assert sum(e["stage"] == "electronic_iteration" for e in step["energies"]) == 63
    assert len(step["ionic_steps"]) == 1 and step["ionic_steps"][0]["index"] == 1
    assert step["ionic_steps"][0]["electronic_iterations"] == 63
    assert step["scf"]["converged_energy_count"] == 1
    assert step["optimization"]["status"] == "not_requested"
    assert step["final_scf_energy"] is None  # VASP free energy is not Gaussian E(SCF).
    assert step["final_energies"]["free_energy_TOTEN"]["value"] == pytest.approx(-68.22868532)
    assert step["final_energies"]["energy_without_entropy"]["value"] == pytest.approx(-68.23570214)
    assert step["final_energies"]["energy_sigma_to_zero"]["value"] == pytest.approx(-68.23102426)
    assert step["final_energy"]["unit"] == "eV"
    geometry = step["final_geometry"]
    assert geometry["elements"] == ["Ni"] * 18 and geometry["periodic_axes"] == [True] * 3
    independent = read(VASP, format="vasp-out", index=-1)
    np.testing.assert_allclose(geometry["cell"], independent.cell.array, atol=1e-10)
    np.testing.assert_allclose(geometry["positions"], independent.positions, atol=1e-10)
    np.testing.assert_allclose(geometry["forces"], independent.get_forces(), atol=1e-10)
    lines = original.decode().splitlines()
    assert "POSITION" in lines[geometry["line_start"] - 1]
    assert "TOTEN" in lines[step["final_energy"]["line"] - 1]
    assert "direct lattice vectors" in lines[geometry["cell_line"] - 1]
    json.dumps(report, allow_nan=False)


def test_public_gaussian_output_geometry_is_nonperiodic_and_matches_independent_reader():
    raw = GAUSSIAN.read_bytes()
    step = parse_log(raw)["steps"][0]
    assert len(step["geometries"]) > 5
    geometry = step["final_geometry"]
    assert geometry["cell"] is None and geometry["periodic_axes"] == [False] * 3
    assert len(geometry["positions"]) == 20
    independent = read(StringIO(raw.decode()), format="gaussian-out", index=-1)
    # ASE retains input orientation; the last printed standard orientation has
    # the same internal distances with a different rigid reference frame.
    positions = np.asarray(geometry["positions"])
    distances = np.linalg.norm(positions[:, None, :] - positions[None, :, :], axis=-1)
    independent_distances = np.linalg.norm(independent.positions[:, None, :] - independent.positions[None, :, :], axis=-1)
    np.testing.assert_allclose(distances, independent_distances, atol=2e-6)
    assert geometry["elements"] == independent.get_chemical_symbols()
    assert geometry_report(geometry)["cell"] is None


def synthetic_orientation(*, units="Angstroms", atomic_number=1, truncated=False):
    return f""" Standard orientation:
 ---------------------------------------------------------------------
 Center     Atomic      Atomic             Coordinates ({units})
 Number     Number       Type             X           Y           Z
 ---------------------------------------------------------------------
      1          {atomic_number}           0        1.000000    0.000000    0.000000
""" + ("" if truncated else " ---------------------------------------------------------------------\n")


@pytest.mark.parametrize("units,factor", [("Angstroms", 1), ("Bohr", BOHR_ANGSTROM)])
def test_explicit_gaussian_orientation_units_are_normalized(units, factor):
    raw = ("Gaussian 16\n # HF/STO-3G\n ----\n NAtoms=1\n" +
           synthetic_orientation(units=units)).encode()
    step = parse_log(raw)["steps"][0]
    assert step["final_geometry"]["positions"][0][0] == pytest.approx(factor)


@pytest.mark.parametrize("table", [synthetic_orientation(units="unknown"),
                                  synthetic_orientation(atomic_number=0),
                                  synthetic_orientation(atomic_number=-1),
                                  synthetic_orientation(truncated=True)])
def test_invalid_final_gaussian_table_does_not_reuse_an_earlier_frame(table):
    raw = ("Gaussian 16\n # HF/STO-3G\n ----\n NAtoms=1\n" +
           synthetic_orientation() + table).encode()
    step = parse_log(raw)["steps"][0]
    assert len(step["geometries"]) == 1
    assert step["final_geometry"] is None and step["warnings"]


def test_truncated_and_unconverged_outcar_do_not_infer_success_from_energy_or_footer():
    text = VASP.read_text()
    truncated = parse_log(text.split("General timing and accounting")[0].encode())
    assert truncated["status"] == "truncated"
    assert truncated["steps"][0]["scf"]["status"] == "converged"
    unconverged = text.replace("aborting loop because EDIFF is reached", "electronic iteration budget exhausted")
    unconverged = unconverged.replace("NELM   =    120", "NELM   =     63")
    report = parse_log(unconverged.encode())
    assert report["status"] == "failure"
    assert report["steps"][0]["scf"]["status"] == "failed"
    assert report["steps"][0]["final_energy"]
    restarted = parse_log((text + "\n ----- Iteration 2( 1) -----\n").encode())
    assert restarted["status"] == "truncated"
    assert restarted["steps"][0]["final_geometry"] is None


def test_outcar_concatenation_cannot_hide_a_later_failure():
    first = VASP.read_bytes()
    second = first.split(b"General timing and accounting")[0] + b"\n ERROR: test failure\n"
    report = parse_log(first + b"\n" + second)
    assert len(report["steps"]) == 2 and report["status"] == "failure"
    assert report["steps"][0]["status"] == "normal"
    assert report["steps"][1]["status"] == "failure"


def test_outcar_ionic_records_follow_outer_summaries_instead_of_electronic_iterations():
    # Explicit synthetic two-ionic-step control-flow case built from the public
    # original; it is not presented as a two-step Ni calculation.
    text = VASP.read_text()
    iteration_start = re.search(r"^-+ Iteration\s+1\(", text, re.M).start()
    second = re.sub(r"\bIteration\s+1\(", "Iteration 2(", text[iteration_start:])
    combined = text.split("General timing and accounting")[0] + second
    step = parse_log(combined.encode())["steps"][0]
    assert [row["index"] for row in step["ionic_steps"]] == [1, 2]
    assert len(step["energies"]) == 128 and len(step["geometries"]) == 2
    assert step["scf"]["converged_energy_count"] == 2
    assert step["final_energy"] is step["ionic_steps"][1]["energy"]


def test_truncated_outcar_never_borrows_electronic_or_previous_ionic_energy_conventions():
    text = VASP.read_text()
    before_final_summary = text[:text.rindex("  FREE ENERGIE OF THE ION-ELECTRON SYSTEM")]
    step = parse_log(before_final_summary.encode())["steps"][0]
    assert len(step["energies"]) == 63 and step["ionic_steps"] == []
    assert step["final_energy"] is None and step["final_energies"] == {}
    assert step["status"] == "truncated"
    # The final TOTEN exists but its entropy/sigma line has not yet been written.
    before_final_entropy = text[:text.rindex("  energy  without entropy=")]
    step = parse_log(before_final_entropy.encode())["steps"][0]
    assert step["final_energy"]["value"] == pytest.approx(-68.22868532)
    assert set(step["final_energies"]) == {"free_energy_TOTEN"}
    assert "energy_without_entropy" not in step["final_energy"]
    assert step["status"] == "truncated"
    unfinished_next_step = (text + "\n----- Iteration 2( 1) -----\n"
                           " Free energy of the ion-electron system (eV)\n"
                           " free energy TOTEN = -60.0 eV\n"
                           " energy without entropy = -59.0 energy(sigma->0) = -59.5\n")
    step = parse_log(unfinished_next_step.encode())["steps"][0]
    assert len(step["ionic_steps"]) == 1 and len(step["energies"]) == 65
    assert step["energies"][-1]["stage"] == "electronic_iteration"
    assert step["final_energy"] is None and step["final_energies"] == {}
    assert step["status"] == "truncated"


def test_concatenated_vasp_versions_are_bound_to_each_job_and_comparison_source():
    first = VASP.read_bytes()
    second = first.replace(b"vasp.5.3.3", b"vasp.6.4.3")
    report = parse_log(first + b"\n" + second, source_name="synthetic-mixed-versions.OUTCAR")
    assert [step["program"]["version"] for step in report["steps"]] == ["5.3.3", "6.4.3"]
    entries = result_entries(report)
    assert [entry["output"]["program"]["version"] for entry in entries] == ["5.3.3", "6.4.3"]
    assert "6.4.3" in entries[1]["filename"]
    assert energy_comparison(*entries, reviewed=True)["status"] == "unavailable"


def test_concatenated_gaussian_versions_are_per_job_and_link1_inherits_current_executable():
    first = ("Gaussian 09: Revision D.01\n # HF/STO-3G\n -----\n NAtoms=1\n" +
             synthetic_orientation() + " Normal termination of Gaussian 09.\n")
    second = first.replace("Gaussian 09", "Gaussian 16").replace("D.01", "C.01")
    report = parse_log((first + second).encode())
    assert len(report["steps"]) == 2
    assert [entry["output"]["program"]["version"] for entry in result_entries(report)] == ["09", "16"]
    link1 = "--Link1--\n # HF/STO-3G Freq\n -----\n Normal termination of Gaussian 16.\n"
    report = parse_log((first + second + link1).encode())
    assert [step["program"]["version"] for step in report["steps"]] == ["09", "16", "16"]
    assert report["steps"][2]["program"] == report["steps"][1]["program"]


@pytest.mark.parametrize("change", [
    lambda t: t.replace("NIONS =     18", "NIONS =     19"),
    lambda t: t.replace("-68.22868532 eV", "************* eV"),
    lambda t: t.replace("-68.22868532 eV", "1D999 eV"),
])
def test_unsafe_numeric_outcar_records_fail_clearly(change):
    with pytest.raises(ResearchError):
        parse_log(change(VASP.read_text()).encode())


def test_outcar_missing_atom_identity_or_final_positions_does_not_fabricate_geometry():
    text = VASP.read_text()
    missing_species = text.replace("POTCAR:", "UNKNOWN:")
    assert parse_log(missing_species.encode())["steps"][0]["final_geometry"] is None
    broken_table = text[:text.index(" POSITION ")] + " POSITION TOTAL-FORCE (eV/Angst)\n -----\n0 0 0 0 0 0\n"
    report = parse_log(broken_table.encode())
    assert report["status"] == "truncated" and report["steps"][0]["final_geometry"] is None


def test_ionic_completion_requires_optimization_marker_and_does_not_certify_a_minimum():
    text = VASP.read_text().replace("NSW    =      0", "NSW    =     50").replace("IBRION =     -1", "IBRION =      2")
    step = parse_log(text.encode())["steps"][0]
    assert step["optimization"]["status"] == "incomplete"
    completed = parse_log((text + "\n reached required accuracy - stopping structural energy minimisation\n").encode())["steps"][0]
    assert completed["optimization"]["status"] == "completed"
    assert completed["frequencies"]["minimum_certified"] is False


def molecule(positions):
    return {"positions": positions, "elements": ["C", "H", "O", "N"],
            "cell": None, "periodic_axes": [False] * 3, "units": {"length": "angstrom"}}


def test_displacement_requires_correspondence_units_and_explicit_registration():
    a = molecule([[0, 0, 0], [1, 0, 0], [0, 2, 0], [0, 0, 3]])
    b = deepcopy(a)
    rotation = np.array([[0, -1, 0], [1, 0, 0], [0, 0, 1]])
    b["positions"] = (np.asarray(a["positions"]) @ rotation + [5, 6, 7]).tolist()
    assert compare_coordinates(a, b)["status"] == "unavailable"
    assert compare_coordinates(a, b, correspondence=True)["rmsd"] > 5
    assert compare_coordinates(a, b, correspondence=True, mode="rigid")["rmsd"] < 1e-12
    b["positions"] = (-np.asarray(a["positions"])).tolist()
    assert compare_coordinates(a, b, correspondence=True, mode="rigid")["rmsd"] > 0.5
    b["units"] = {"length": "bohr"}
    assert compare_coordinates(a, b, correspondence=True)["status"] == "unavailable"
    b["units"] = a["units"]
    b["elements"] = list(reversed(b["elements"]))
    assert compare_coordinates(a, b, correspondence=True)["status"] == "unavailable"


def test_periodic_mic_handles_skew_cells_and_rejects_changed_cells():
    a = {"elements": ["C"], "positions": [[0, 0, 0]],
         "cell": [[2, 0, 0], [1.9, 0.2, 0], [0, 0, 5]],
         "periodic_axes": [True] * 3, "units": {"length": "angstrom"}}
    b = deepcopy(a)
    b["positions"] = [[1.9, 0.2, 0]]
    assert compare_coordinates(a, b, correspondence=True, mode="minimum_image")["rmsd"] < 1e-12
    assert compare_coordinates(a, b, correspondence=True, mode="rigid")["status"] == "unavailable"
    b["cell"][2][2] += 0.1
    assert compare_coordinates(a, b, correspondence=True, mode="minimum_image")["status"] == "unavailable"


def test_energy_subtraction_has_explicit_units_conventions_and_condition_review():
    a = result_entries(parse_log(VASP.read_bytes()))[0]
    b = deepcopy(a)
    assert energy_comparison(a, b)["status"] == "unavailable"
    b["output"]["step"]["final_energy"]["value"] += 0.5
    assert energy_comparison(a, b, reviewed=True)["delta"] == pytest.approx(0.5)
    b["output"]["step"]["conditions"]["settings"]["ENCUT"] += 50
    assert energy_comparison(a, b, reviewed=True)["status"] == "unavailable"
    b = deepcopy(a)
    b["output"]["step"]["conditions"]["kpoints_reciprocal_and_weights"][0][0] = 0.5
    assert energy_comparison(a, b, reviewed=True)["status"] == "unavailable"
    b = deepcopy(a)
    b["output"]["step"]["final_energy"]["kind"] = "energy_sigma_to_zero"
    assert energy_comparison(a, b, reviewed=True)["status"] == "unavailable"
    gaussian = result_entries(parse_log(GAUSSIAN.read_bytes()))[0]
    assert energy_comparison(a, gaussian, reviewed=True)["status"] == "unavailable"
    b = deepcopy(gaussian)
    b["output"]["step"]["final_energy"]["value"] *= 27.211386245988
    b["output"]["step"]["final_energy"]["unit"] = "eV"
    assert energy_comparison(gaussian, b, reviewed=True)["delta"] == pytest.approx(0, abs=1e-10)


def test_legacy_single_log_and_library_originals_are_reparsed_and_checked():
    record = output_record(VASP.read_bytes(), "OUTCAR")
    assert saved_output_records({"log": record}) == [record]
    assert saved_output_records({"logs": [record], "log": record}) == [record]
    parsed = read_output_record(record)
    assert len(result_entries(parsed)) == 1
    record["data"] = output_record(b"bad", "wrong")["data"]
    with pytest.raises(ValueError, match="checksum"):
        read_output_record(record)
