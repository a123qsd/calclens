"""Reproduce a small, real periodic h-BN vacuum series with optional PySCF.

Run with the separate electronic environment; importing/viewing the committed
case needs only the normal CalcLens NumPy/ASE dependencies. This exploratory
Gamma-only, minimal-basis LDA calculation is not a production DFT benchmark.
"""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
from hashlib import sha256
import json
import os
from pathlib import Path
import sys
import time

# Fix thread counts before NumPy/PySCF load, including on machines with many cores.
for _thread_variable in ("OMP_NUM_THREADS", "OPENBLAS_NUM_THREADS", "MKL_NUM_THREADS",
                         "VECLIB_MAXIMUM_THREADS", "NUMEXPR_NUM_THREADS"):
    os.environ[_thread_variable] = "1"

import numpy as np  # noqa: E402
from ase.io import read  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from slab_preflight.research import build_vacuum_cif, compare_convergence_series  # noqa: E402

DEFAULT_DIRECTORY = ROOT / "examples" / "research_cases" / "hbn_vacuum"
VACUA = (8.0, 12.0, 16.0)
MESH = (15, 15, 151)


def write_json(path: Path, document: dict) -> None:
    path.write_text(json.dumps(document, indent=2, allow_nan=False) + "\n", encoding="utf-8")


def artifact(path: Path, root: Path, **extra) -> dict:
    return {"path": path.relative_to(root).as_posix(),
            "sha256": sha256(path.read_bytes()).hexdigest(), **extra}


def fixed_conditions(version: str) -> dict:
    return {
        "program": "PySCF", "program_version": version, "method": "RKS",
        "xc": "LDA,VWN", "basis": "gth-szv", "pseudopotential": "gth-pade",
        "charge": 0, "multiplicity": 1, "kpoint_grid": [1, 1, 1],
        "kpoint_convention": "Gamma only", "periodic_dimensions": 3,
        "coulomb_boundary": "3D periodic supercell; no truncated Coulomb potential",
        "density_fitting": "FFTDF", "fft_mesh": list(MESH),
        "xc_grid": "uniform cell grid, same mesh as FFTDF", "precision": 1e-8,
        "scf_energy_tolerance_hartree": 1e-9, "scf_gradient_tolerance": 1e-6,
        "maximum_scf_cycles": 60, "threads": 1, "geometry_optimized": False,
        "smearing": None, "energy_quantity": "electronic_total",
    }


def run_case(directory: Path) -> dict:
    from pyscf import __version__ as pyscf_version, lib
    from pyscf.pbc import dft, gto

    lib.num_threads(1)
    directory.mkdir(parents=True, exist_ok=True)
    source = (ROOT / "examples" / "hbn.cif").read_bytes()
    (directory / "source.cif").write_bytes(source)
    conditions = fixed_conditions(pyscf_version)
    cases = []
    for vacuum in VACUA:
        case_id = f"vacuum_{int(vacuum):02d}A"
        cif = directory / f"{case_id}.cif"
        log = directory / f"{case_id}.log"
        result_path = directory / f"{case_id}.json"
        cif.write_bytes(build_vacuum_cif(source, vacuum))
        atoms = read(cif, format="cif")
        started = datetime.now(timezone.utc).isoformat()
        elapsed_start = time.perf_counter()
        print(f"Computing {case_id}: {len(atoms)} atoms, Gamma point, mesh {MESH}", flush=True)
        cell = gto.Cell()
        cell.atom = list(zip(atoms.get_chemical_symbols(), atoms.positions.tolist()))
        cell.a = np.asarray(atoms.cell)
        cell.unit = "Angstrom"
        cell.basis = "gth-szv"
        cell.pseudo = "gth-pade"
        cell.dimension = 3
        cell.mesh = np.array(MESH)
        cell.precision = conditions["precision"]
        cell.charge = 0
        cell.spin = 0
        cell.max_memory = 700
        cell.verbose = 4
        cell.output = str(log)
        # Avoid PySCF's optional dump of local file paths / host details. The
        # exact reproducible input below is written explicitly into the log.
        cell.build(dump_input=False, parse_arg=False)
        cell.stdout.write("CalcLens controlled periodic input; lengths in angstrom.\n")
        cell.stdout.write(json.dumps({"fixed_conditions": conditions,
                                      "elements": atoms.get_chemical_symbols(),
                                      "positions_angstrom": atoms.positions.tolist(),
                                      "cell_angstrom": np.asarray(atoms.cell).tolist()},
                                     sort_keys=True) + "\n")
        mean_field = dft.RKS(cell)
        mean_field.xc = "lda,vwn"
        mean_field.grids = dft.gen_grid.UniformGrids(cell)
        mean_field.grids.mesh = np.array(MESH)
        mean_field.with_df.mesh = np.array(MESH)
        mean_field.conv_tol = conditions["scf_energy_tolerance_hartree"]
        mean_field.conv_tol_grad = conditions["scf_gradient_tolerance"]
        mean_field.max_cycle = conditions["maximum_scf_cycles"]
        energy = float(mean_field.kernel())
        density = np.asarray(mean_field.make_rdm1())
        overlap = np.asarray(mean_field.get_ovlp())
        core = np.asarray(mean_field.get_hcore())
        potential = mean_field.get_veff(cell, density)
        nuclear = float(cell.energy_nuc())
        rho = mean_field.get_rho(density)
        components = {
            "one_electron_hartree": float(np.einsum("ij,ji->", density, core).real),
            "coulomb_hartree": float(potential.ecoul),
            "xc_hartree": float(potential.exc), "nuclear_hartree": nuclear,
        }
        total_reconstructed = sum(components.values())
        fock = core + potential
        coefficients = np.asarray(mean_field.mo_coeff)
        mo_energy = np.asarray(mean_field.mo_energy)
        residual = fock @ coefficients - (overlap @ coefficients) * mo_energy
        grid_electrons = float(np.sum(rho) * cell.vol / rho.size)
        cell.stdout.flush()
        cell.stdout.close()
        elapsed = time.perf_counter() - elapsed_start
        calculation = {
            "schema_version": 1, "kind": "calclens_calculation_result",
            "case_id": case_id, "status": "normal" if mean_field.converged else "failure",
            "scf_converged": bool(mean_field.converged), "fixed_conditions": conditions,
            "input_cif_sha256": sha256(cif.read_bytes()).hexdigest(),
            "output_sha256": sha256(log.read_bytes()).hexdigest(),
            "energy": {"value": energy, "unit": "hartree", "quantity": "electronic_total"},
            "vacuum_angstrom": vacuum, "started_utc": started, "elapsed_seconds": elapsed,
            "electron_count": cell.nelectron, "basis_function_count": cell.nao_nr(),
            "actual_fft_mesh": mean_field.with_df.mesh.tolist(),
            "actual_xc_mesh": mean_field.grids.mesh.tolist(),
            "cartesian_angstrom": atoms.positions.tolist(),
            "cell_angstrom": np.asarray(atoms.cell).tolist(),
            "energy_components": components,
            "consistency": {
                "energy_reconstructed_hartree": total_reconstructed,
                "energy_component_error_hartree": abs(energy - total_reconstructed),
                "electron_count_trace_ds": float(np.einsum("ij,ji->", density, overlap).real),
                "electron_count_uniform_grid": grid_electrons,
                "ks_matrix_max_residual": float(np.max(np.abs(residual))),
            },
            "matrices": {
                "density": np.real_if_close(density).tolist(),
                "overlap": np.real_if_close(overlap).tolist(),
                "core_hamiltonian": np.real_if_close(core).tolist(),
            },
            "references": ["https://pyscf.org/user/pbcgto.html",
                           "https://pyscf.org/user/pbc/df.html",
                           "https://pyscf.org/user/pbc/dft-settings.html"],
        }
        write_json(result_path, calculation)
        cases.append({"id": case_id, "vacuum_angstrom": vacuum,
                      "cif": artifact(cif, directory),
                      "output": artifact(log, directory, kind="pyscf_log"),
                      "result": artifact(result_path, directory)})
        print(f"{case_id}: E={energy:.12f} Eh, SCF={mean_field.converged}, {elapsed:.2f}s", flush=True)
    manifest = {
        "schema_version": 1, "kind": "vacuum_convergence_series",
        "name": "Constructed h-BN monolayer, exploratory Gamma LDA/SZV vacuum series",
        "source_cif": artifact(directory / "source.cif", directory,
                               origin="CalcLens examples/hbn.cif, original idealized geometry; a=2.5 Å",
                               license="LicenseRef-CalcLens-Free-Use (repository LICENSE)",
                               source_url="https://github.com/a123qsd/calclens"),
        "fixed_conditions": conditions,
        "variable": {"name": "vacuum_angstrom", "normal_axis": "c",
                     "definition": "largest normal nuclei gap; planar layer thickness is zero"},
        "tolerance": {"value": 1.0, "unit": "meV/atom", "minimum_successful_cases": 3,
                      "reference": "largest successful sampled vacuum"},
        "cases": cases,
        "reproduction": {"script": "scripts/prepare_convergence_case.py",
                         "command": "python scripts/prepare_convergence_case.py --run",
                         "python": sys.version.split()[0], "numpy": np.__version__},
        "limitations": [
            "Real 3D periodic electronic outputs for an idealized 2D layer, not experimental/relaxed data.",
            "Minimal gth-szv basis and Gamma-only sampling are deliberately inexpensive and unvalidated.",
            "LDA,VWN is not a van der Waals treatment; energies do not establish physical accuracy.",
            "Fixed FFT/xc point counts mean real-space z spacing changes with vacuum. No grid convergence study.",
            "Only 8, 12, 16 Å are sampled; tolerance is a chosen 1 meV/atom demonstration criterion.",
            "No force, band-gap, density-tail, geometry, basis, or k-point convergence claim.",
            "NumPy matrix/component checks share PySCF integrals; no independent electronic engine validation.",
        ],
    }
    write_json(directory / "series.json", manifest)
    report = compare_convergence_series(directory / "series.json")
    write_json(directory / "comparison.json", report)
    return report


def check_case(directory: Path) -> dict:
    report = compare_convergence_series(directory / "series.json")
    for case in report["cases"]:
        result = json.loads((directory / case["result"]["path"]).read_bytes())
        matrices = result["matrices"]
        density = np.asarray(matrices["density"])
        overlap = np.asarray(matrices["overlap"])
        core = np.asarray(matrices["core_hamiltonian"])
        count = float(np.trace(density @ overlap))
        energy = float(np.trace(density @ core))
        components = result["energy_components"]
        energy += sum(components[key] for key in ("coulomb_hartree", "xc_hartree", "nuclear_hartree"))
        if abs(count - 8) > 1e-8:
            raise ValueError("Independent AO matrix trace does not contain eight valence electrons.")
        if abs(energy - case["energy_hartree"]) > 1e-8:
            raise ValueError("Independent energy-component reconstruction failed.")
        if result["actual_fft_mesh"] != list(MESH) or result["actual_xc_mesh"] != list(MESH):
            raise ValueError("Actual meshes differ from the declared fixed grid.")
        if result["basis_function_count"] != 8:
            raise ValueError("This case requires exactly eight minimal-basis functions.")
    return report


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run", action="store_true", help="Run three actual optional PySCF jobs.")
    parser.add_argument("--check", action="store_true", help="Verify committed outputs without PySCF.")
    parser.add_argument("--output", type=Path, default=DEFAULT_DIRECTORY)
    arguments = parser.parse_args()
    report = run_case(arguments.output) if arguments.run else check_case(arguments.output)
    print(json.dumps({"status": report["status"], "summary": report["summary"],
                      "comparisons": report["comparisons"]}, indent=2))


if __name__ == "__main__":
    main()
