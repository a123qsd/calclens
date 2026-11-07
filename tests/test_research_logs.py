"""Check public originals and clearly labelled synthetic edge-case snippets.

The synthetic strings exercise parser control flow; they are not represented
as Gaussian runs, measured chemical results, or researcher trials.
"""

from hashlib import sha256
import json
from pathlib import Path

import pytest

from slab_preflight.research import ResearchError, convert_energy, parse_log
from slab_preflight.research_logs import HARTREE_EV, MAX_LOG_BYTES

ROOT = Path(__file__).resolve().parents[1]
REFERENCES = ROOT / "examples" / "research_cases" / "gaussian_reference"
SYNTHETIC_HEADER = "Gaussian 16: ES64L-G16RevC.01 test-fixture\n"


def synthetic_job(*, ending="Normal termination of Gaussian 16.", route="HF/STO-3G",
                  energy="-1.000000000000D+00", body=""):
    return (f"{SYNTHETIC_HEADER} #p {route}\n -------\n"
            " Charge = 0 Multiplicity = 1\n NAtoms= 2\n"
            f" SCF Done: E(RHF) = {energy} A.U. after 8 cycles\n"
            f"{body}\n{ending}\n").encode()


@pytest.mark.parametrize("name,count,energy,opt,modes", [
    ("dvb_dispersion_bp86_d3zero.out", 1, -382.328035056, "not_requested", 0),
    ("dvb_gopt.out", 5, -382.308266602, "completed", 0),
    ("dvb_ir.out", 1, -382.308266602, "completed", 54),
])
def test_actual_public_gaussian_originals_are_traceable(name, count, energy, opt, modes):
    record = next(item for item in json.loads((REFERENCES / "sources.json").read_bytes())["files"]
                  if item["path"] == name)
    original = (REFERENCES / name).read_bytes()
    report = parse_log(original, source_name=name, source_url=record["source_url"])
    step = report["steps"][0]
    assert report["status"] == "normal"
    assert report["program"]["version"] == "16"
    assert report["provenance"]["sha256"] == sha256(original).hexdigest() == record["sha256"]
    assert report["provenance"]["source_url"] == record["source_url"]
    assert (REFERENCES / name).read_bytes() == original
    assert (step["charge"], step["multiplicity"], step["atom_count"]) == (0, 1, 20)
    assert len(step["energies"]) == count
    assert step["final_scf_energy"]["value"] == pytest.approx(energy, abs=1e-10)
    assert step["final_scf_energy"]["value_ev"] == pytest.approx(energy * HARTREE_EV)
    assert step["optimization"]["status"] == opt
    assert step["frequencies"]["reported_mode_count"] == modes
    assert step["frequencies"]["minimum_certified"] is False
    source_line = original.decode().splitlines()[step["final_scf_energy"]["line"] - 1]
    assert "SCF Done:" in source_line
    json.dumps(report, allow_nan=False)


def test_scf_energy_does_not_certify_optimization_or_frequency_completion():
    report = parse_log(synthetic_job(route="B3LYP/6-31+G(d,p) Opt Freq"))
    step = report["steps"][0]
    assert report["status"] == "normal"  # execution marker only
    assert step["method"] == "B3LYP"
    assert step["basis"] == "6-31+G(d,p)"
    assert step["scf"]["status"] == "converged"
    assert step["optimization"]["status"] == "incomplete"
    assert step["frequencies"]["reported_mode_count"] == 0
    assert step["warnings"]


def test_imaginary_modes_and_convergence_rows_remain_explicit():
    report = parse_log(synthetic_job(route="HF/STO-3G Opt Freq", body="""
 Maximum Force 0.000001 0.000450 YES
 RMS Force 0.000002 0.000300 YES
 Maximum Displacement 0.0020 0.001800 NO
 Optimization completed.
 Frequencies -- -25.0000 0.0000 100.5000
"""))
    step = report["steps"][0]
    assert step["optimization"]["status"] == "completed"
    assert [row["converged"] for row in step["optimization"]["convergence_criteria"]] == [True, True, False]
    assert step["frequencies"]["imaginary_mode_count"] == 1
    assert step["frequencies"]["values"][0]["unit"] == "cm^-1"
    assert step["frequencies"]["minimum_certified"] is False


@pytest.mark.parametrize("second_ending,expected", [
    ("Convergence failure -- run terminated.\nError termination via Lnk1e in l502.exe", "failure"),
    ("", "truncated"),
    ("Normal termination of Gaussian 16.", "normal"),
])
def test_link1_keeps_every_step_and_late_failure_or_truncation(second_ending, expected):
    data = synthetic_job() + b"Link1: Proceeding to internal job step number 2.\n" + synthetic_job(
        ending=second_ending, route="B3LYP/def2SVP Freq")
    report = parse_log(data)
    assert len(report["steps"]) == 2
    assert report["steps"][0]["status"] == "normal"
    assert report["steps"][1]["status"] == expected
    assert report["status"] == expected
    assert report["steps"][1]["method"] == "B3LYP"
    assert report["steps"][1]["line_start"] > report["steps"][0]["line_end"]


def test_empty_requested_link1_step_stays_truncated():
    report = parse_log(synthetic_job() + b"--Link1--\n #p HF/STO-3G Freq\n ----\n")
    assert report["status"] == "truncated"
    assert len(report["steps"]) == 2
    assert report["steps"][1]["energies"] == []


def test_continued_route_and_d_exponent_have_their_source_lines():
    data = synthetic_job(route="B3LYP/6-31G(d)\n Opt=(Tight) Freq", energy="-7.5123456789D+01")
    step = parse_log(data)["steps"][0]
    assert step["final_scf_energy"]["value"] == pytest.approx(-75.123456789)
    assert len(step["route_lines"]) == 2
    assert step["job_types"] == ["optimization", "frequencies"]


def test_unknown_and_unsupported_data_do_not_gain_supported_results():
    unknown = parse_log(b"arbitrary text: energy=-100; finished successfully")
    assert unknown["status"] == "unknown"
    assert unknown["steps"] == []
    correlated = parse_log(synthetic_job(route="CCSD(T)/cc-pVDZ"))
    assert correlated["steps"][0]["supported_scope"] is False
    assert correlated["steps"][0]["warnings"]


@pytest.mark.parametrize("unit", ["hartree", "Eh", "eV", "meV", "kJ/mol", "kcal/mol"])
def test_explicit_energy_units_round_trip(unit):
    converted = convert_energy(-75.25, "hartree", unit)
    assert convert_energy(converted, unit) == pytest.approx(-75.25)


@pytest.mark.parametrize("value,unit", [(float("nan"), "eV"), (True, "eV"),
                                        (1, None), (1, "eV/atom"), (1, "")])
def test_missing_ambiguous_or_invalid_energy_units_are_rejected(value, unit):
    with pytest.raises(ResearchError):
        convert_energy(value, unit)


def test_oversize_and_nonbyte_logs_are_bounded():
    with pytest.raises(ResearchError):
        parse_log("text")
    with pytest.raises(ResearchError):
        parse_log(b"x" * (MAX_LOG_BYTES + 1))


def test_nonfinite_or_malformed_numeric_gaussian_records_are_rejected():
    with pytest.raises(ResearchError, match="Non-finite"):
        parse_log(synthetic_job(energy="1.0D+999"))
    with pytest.raises(ResearchError, match="Malformed"):
        parse_log(synthetic_job(body=" Frequencies -- 1.0 ***** 3.0"))
