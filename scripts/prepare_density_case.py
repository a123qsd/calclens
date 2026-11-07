"""Regenerate or independently check a real frozen H2 AB/A/B density example.

Regeneration alone requires PySCF 2.12.0. --check uses only the normal NumPy/ASE
environment. Geometry is illustrative; the three UHF calculations are real,
isolated molecular calculations with common full-dimer ghost-center bases.
"""
from __future__ import annotations

import argparse
import csv
from hashlib import sha256
import json
from pathlib import Path
import sys

import numpy as np
from ase.io.cube import read_cube_data

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
BOHR_ANGSTROM = 0.529177210903
CASE_DIR = ROOT / "examples" / "research_cases" / "h2_density"
METHOD = "PySCF 2.12.0 UHF/STO-3G; common full H2 AO basis with ghost-H centers"
REFERENCE = ("Frozen H2 nuclei at 0.74 angstrom; neutral AB singlet (2 electrons), neutral A/B "
             "doublets (1 electron each); isolated gas phase, no periodic electronic calculation; "
             "same STO-3G functions on both dimer centers via ghosts, same Cartesian grid/origin/voxel basis; "
             "SCF energy tolerance 1e-12 hartree, gradient tolerance 1e-8; no density renormalization")
POSITIONS_ANGSTROM = np.array([[5.63, 6., 6.], [6.37, 6., 6.]])


def _json(path: Path, value: dict) -> None:
    path.write_text(json.dumps(value, indent=2, allow_nan=False) + "\n", encoding="utf-8")


def _structure() -> str:
    lines = ["# Illustrative frozen isolated H2; 12 A P1 cell is for display, not a periodic SCF model.",
             "data_h2_frozen_uhf_sto3g", "_cell_length_a 12", "_cell_length_b 12", "_cell_length_c 12",
             "_cell_angle_alpha 90", "_cell_angle_beta 90", "_cell_angle_gamma 90",
             "_space_group_IT_number 1", "_space_group_name_H-M_alt 'P 1'", "loop_",
             "_space_group_symop_operation_xyz", "'x,y,z'", "loop_", "_atom_site_label",
             "_atom_site_type_symbol", "_atom_site_fract_x", "_atom_site_fract_y", "_atom_site_fract_z",
             "_atom_site_occupancy"]
    for index, position in enumerate(POSITIONS_ANGSTROM, 1):
        lines.append(f"H{index} H " + " ".join(f"{value:.16g}" for value in position / 12) + " 1")
    return "\n".join(lines) + "\n"


def _write_cube(path: Path, values: np.ndarray, origin: np.ndarray, vectors: np.ndarray,
                real_indices: list[int], role: str) -> None:
    # Cube atom records contain only real nuclei. Ghost basis centers remain in
    # the explicit inputs and SCF log; they are not invented zero-Z atoms.
    lines = [f"Real PySCF UHF/STO-3G H2 {role}; total electron density e/bohr^3",
             "Frozen nuclei; full dimer basis including ghosts; isolated, not periodic",
             " ".join([str(len(real_indices)), *(f"{value:.17g}" for value in origin)])]
    lines.extend(" ".join([str(count), *(f"{value:.17g}" for value in vector)])
                 for count, vector in zip(values.shape, vectors, strict=True))
    lines.extend("1 1 " + " ".join(f"{value:.17g}" for value in POSITIONS_ANGSTROM[index] / BOHR_ANGSTROM)
                 for index in real_indices)
    flat = values.ravel()
    lines.extend(" ".join(f"{value:.12e}" for value in flat[index:index + 6])
                 for index in range(0, len(flat), 6))
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def _independent_readback(directory: Path) -> dict:
    """ASE reads raw Cube scalars; physical profile is reconstructed independently."""
    fields = [read_cube_data(str(directory / name))[0] for name in ("ab.cube", "a.cube", "b.cube")]
    headers = (directory / "ab.cube").read_text().splitlines()
    origin = np.array([float(value) for value in headers[2].split()[1:4]])
    vectors = np.array([[float(value) for value in headers[index].split()[1:4]] for index in (3, 4, 5)])
    difference = fields[0] - fields[1] - fields[2]
    average = np.mean(difference, axis=(0, 1)) / BOHR_ANGSTROM**3
    positions = (origin[2] + np.arange(difference.shape[2]) * vectors[2, 2]) * BOHR_ANGSTROM
    volume_bohr3 = abs(np.linalg.det(vectors))
    return {"parser": "ASE read_cube_data, independent of CalcLens Cube parser",
            "shape": list(difference.shape), "raw_difference_e_per_bohr3": difference,
            "positions_angstrom": positions, "average_e_per_angstrom3": average,
            "integrals_e": {role: float(field.sum(dtype=np.float64) * volume_bohr3)
                            for role, field in zip(("AB", "A", "B"), fields, strict=True)},
            "difference_integral_e": float(difference.sum(dtype=np.float64) * volume_bohr3)}


def _readme(case: dict) -> str:
    states = {state["role"]: state for state in case["scf"]}
    return f"""# Frozen H₂ density difference / 동결 H₂ 전자 밀도 차분

This is an illustrative H₂ geometry with **three actual local PySCF 2.12.0
UHF/STO-3G calculations**. H₂ has a fixed 0.74 Å separation. AB is a neutral
singlet; A and B are neutral H doublets at their unchanged dimer positions.
Both fragment calculations retain the full dimer basis through a ghost-H center.
The basis, grid, origin and voxel vectors are common to all three calculations.

| State | Electrons / spin | SCF energy (hartree) | SCF converged |
| --- | --- | --- | --- |
| AB | 2 / singlet | {states['AB']['energy_hartree']:.12f} | {states['AB']['converged']} |
| A | 1 / doublet | {states['A']['energy_hartree']:.12f} | {states['A']['converged']} |
| B | 1 / doublet | {states['B']['energy_hartree']:.12f} | {states['B']['converged']} |

Open `h2.cif`, then use `ab.cube`, `a.cube` and `b.cube` as **total density**
in `e/bohr^3`. Fragment indices in AB are A `[1]` and B `[2]` (one-based).
Select the z grid axis for the supplied reference profile. Copy the exact common
method and reference conditions from `case.json` when recomputing AB−A−B.

`ab.log`, `a.log` and `b.log` contain the actual SCF iterations. `inputs.json`
records all real/ghost centers and settings. `case.json` records source hashes,
spin diagnostics, overlap electron counts, stationary Fock/density checks and an
independent reconstruction of the UHF energy. `reference-profile.csv` comes from
an independent ASE Cube readback and direct CPU arithmetic.

The {case['grid']['shape'][0]}³ finite grid integrates to AB
{case['independent_readback']['integrals_e']['AB']:.10f} e, A
{case['independent_readback']['integrals_e']['A']:.10f} e and B
{case['independent_readback']['integrals_e']['B']:.10f} e. The integrated difference is
{case['independent_readback']['difference_integral_e']:.6g} e. These are finite-grid
rectangle sums, without renormalization or a convergence claim. The quantum
density matrices separately have exactly 2, 1 and 1 electrons within the recorded
overlap-trace tolerance.

Positive difference density denotes electron accumulation relative to the two
frozen atom references. It is not an assigned atomic charge or a quantitatively
converged charge-transfer measurement. STO-3G is deliberately small. These SCF
energies do not establish correlated accuracy or basis/grid convergence.
The 12 Å P1 CIF is a display container: the electronic jobs are isolated,
nonperiodic and unrelaxed.

실제 로컬 UHF 계산 세 번으로 만든 예제입니다. 원자 간격 0.74 Å를 고정하고,
AB는 중성 단일항, A·B는 각각 중성 H 이중항으로 계산했습니다. 조각에서도
고스트 중심으로 전체 H₂ 기저를 유지했습니다. 세 Cube는 같은 격자를 사용합니다.
차분의 양수는 두 원자 기준에 비해 전자가 늘어난 영역이며 원자별 전하를 뜻하지
않습니다. 작은 기저·유한 격자의 설명용 예제이므로 정량적 전하 이동이나 수렴을
주장하지 않습니다. CIF의 P1 셀은 표시용이고 전자 계산에는 주기 경계가 없습니다.

Regenerate using an isolated environment with PySCF 2.12.0, NumPy and ASE:

```sh
python scripts/prepare_density_case.py --output-dir examples/research_cases/h2_density
```

Check the bundled data with the normal CalcLens environment, without PySCF:

```sh
python scripts/prepare_density_case.py --check --output-dir examples/research_cases/h2_density
```

References: [PySCF ghost/basis input](https://pyscf.org/user/gto.html),
[PySCF unrestricted Hartree–Fock](https://pyscf.org/user/scf.html),
[Cube format](https://www.ks.uiuc.edu/Research/vmd/plugins/molfile/cubeplugin.html).
"""


def regenerate(directory: Path, points: int = 49) -> dict:
    import pyscf
    from pyscf import gto, lib, scf
    if pyscf.__version__ != "2.12.0":
        raise ValueError("This reference regeneration requires PySCF 2.12.0 explicitly.")
    if not 17 <= points <= 75:
        raise ValueError("Choose 17–75 points per axis; reference data uses 49.")
    lib.num_threads(1)
    directory.mkdir(parents=True, exist_ok=True)
    (directory / "h2.cif").write_text(_structure(), encoding="utf-8")
    origin = np.full(3, 2.0 / BOHR_ANGSTROM)
    vectors = np.eye(3) * (8.0 / (points - 1) / BOHR_ANGSTROM)
    shape = (points, points, points)
    indices = np.stack(np.meshgrid(*(np.arange(points) for _ in range(3)), indexing="ij"), axis=-1).reshape((-1, 3))
    coordinates = origin + indices @ vectors
    states = []
    overlap_reference = kinetic_reference = None
    definitions = [("AB", [0, 1], 0), ("A", [0], 1), ("B", [1], 1)]
    input_states = []
    for role, real_indices, spin in definitions:
        atoms = [("H" if index in real_indices else "ghost-H", tuple(position / BOHR_ANGSTROM))
                 for index, position in enumerate(POSITIONS_ANGSTROM)]
        molecule = gto.M(atom=atoms, basis="sto-3g", unit="Bohr", charge=0, spin=spin, verbose=0)
        overlap = molecule.intor_symmetric("int1e_ovlp")
        kinetic = molecule.intor_symmetric("int1e_kin")
        if overlap_reference is None:
            overlap_reference, kinetic_reference = overlap, kinetic
        else:
            np.testing.assert_allclose(overlap, overlap_reference, rtol=0, atol=1e-14)
            np.testing.assert_allclose(kinetic, kinetic_reference, rtol=0, atol=1e-14)
        input_states.append({"role": role, "centers_bohr": [{"element": element, "position": list(position)}
                             for element, position in atoms], "spin_Nalpha_minus_Nbeta": spin,
                             "charge": 0, "real_indices_zero_based": real_indices})
        with (directory / f"{role.lower()}.log").open("w", encoding="utf-8") as log:
            log.write(f"Actual PySCF {pyscf.__version__} calculation: {role}\n{METHOD}\n{REFERENCE}\n")
            log.write(json.dumps(input_states[-1], sort_keys=True) + "\n")
            mean_field = scf.UHF(molecule)
            mean_field.stdout = log
            mean_field.verbose = 4
            mean_field.chkfile = None
            mean_field.conv_tol = 1e-12
            mean_field.conv_tol_grad = 1e-8
            mean_field.max_cycle = 100
            mean_field.init_guess = "1e"
            mean_field.kernel()
            if not mean_field.converged or not np.isfinite(mean_field.e_tot):
                raise ValueError(f"Actual {role} SCF did not converge; no reference case is accepted.")
            density_matrices = np.asarray(mean_field.make_rdm1())
            focks = np.asarray(mean_field.get_fock())
            hcore = mean_field.get_hcore()
            reconstructed = float(.5 * np.einsum("sij,sji->", density_matrices, focks + hcore)
                                  + molecule.energy_nuc())
            electron_count = float(np.einsum("sij,ji->", density_matrices, overlap))
            residual = max(float(np.linalg.norm(fock @ density @ overlap - overlap @ density @ fock))
                           for density, fock in zip(density_matrices, focks, strict=True))
            if abs(reconstructed - mean_field.e_tot) > 1e-10 or abs(electron_count - molecule.nelectron) > 1e-10 or residual > 1e-8:
                raise ValueError(f"{role} independent SCF matrix checks failed.")
            spin_squared, multiplicity = mean_field.spin_square()
            ao = molecule.eval_gto("GTOval_sph", coordinates)
            values = sum(np.sum((ao @ coefficients)**2 * occupations, axis=1)
                         for coefficients, occupations in zip(mean_field.mo_coeff, mean_field.mo_occ, strict=True))
            matrix_values = np.einsum("pi,ij,pj->p", ao, density_matrices.sum(axis=0), ao)
            np.testing.assert_allclose(values, matrix_values, rtol=1e-11, atol=1e-13)
            state = {"role": role, "method": "UHF", "basis": "STO-3G at both full-dimer centers",
                     "energy_hartree": float(mean_field.e_tot), "converged": bool(mean_field.converged),
                     "electrons": molecule.nelectron, "alpha_beta_electrons": list(molecule.nelec),
                     "spin_squared": float(spin_squared), "multiplicity_from_spin_squared": float(multiplicity),
                     "ao_count": molecule.nao_nr(), "overlap_electron_count": electron_count,
                     "independent_energy_hartree": reconstructed,
                     "stationary_commutator_norm": residual, "cycles": int(mean_field.cycles)}
            log.write("Independent CPU matrix checks: " + json.dumps(state, sort_keys=True) + "\n")
        _write_cube(directory / f"{role.lower()}.cube", values.reshape(shape), origin, vectors, real_indices, role)
        states.append(state)
    inputs = {"source_status": "illustrative synthetic geometry; actual local SCF calculations",
              "pyscf_version": pyscf.__version__, "method": METHOD, "reference_conditions": REFERENCE,
              "basis": "sto-3g", "positions_angstrom": POSITIONS_ANGSTROM.tolist(), "states": input_states,
              "grid": {"shape": list(shape), "origin_bohr": origin.tolist(), "voxel_vectors_bohr": vectors.tolist()},
              "scf": {"conv_tol_hartree": 1e-12, "conv_tol_grad": 1e-8, "max_cycle": 100,
                      "initial_guess": "1e", "threads": 1}}
    _json(directory / "inputs.json", inputs)
    independent = _independent_readback(directory)
    with (directory / "reference-profile.csv").open("w", newline="", encoding="utf-8") as handle:
        writer = csv.writer(handle)
        writer.writerow(["position_angstrom", "difference_average_e_per_angstrom3"])
        writer.writerows(zip(independent["positions_angstrom"], independent["average_e_per_angstrom3"], strict=True))
    case = {"schema_version": 1, "case_id": "h2-frozen-density", "title": "Frozen H2 AB−A−B density difference",
            "source_status": inputs["source_status"], "structure": "h2.cif", "pyscf_version": pyscf.__version__,
            "common_method": METHOD, "common_basis": "same full H2 STO-3G basis via ghost-H centers",
            "reference_conditions": REFERENCE, "frozen_geometry": True,
            "a_indices": [1], "b_indices": [2], "normal_axis": 2,
            "density_sources": [{"role": role, "path": f"{role.lower()}.cube", "kind": "density",
                                  "units": "e/bohr^3", "real_indices_one_based": [index + 1 for index in real]}
                                 for role, real, _ in definitions],
            "grid": inputs["grid"], "scf": states,
            "common_basis_verified_by": "identical AO overlap and kinetic matrices within 1e-14",
            "independent_readback": {key: value for key, value in independent.items()
                                     if key not in {"raw_difference_e_per_bohr3", "positions_angstrom", "average_e_per_angstrom3"}},
            "limitations": ["Isolated illustrative molecule; CIF P1 cell is for display only.",
                            "No geometry relaxation, periodic electronic calculation or basis/grid convergence study.",
                            "Density difference is not a uniquely assigned atomic charge transfer."]}
    (directory / "README.md").write_text(_readme(case), encoding="utf-8")
    generated = ["h2.cif", "ab.cube", "a.cube", "b.cube", "ab.log", "a.log", "b.log",
                 "inputs.json", "reference-profile.csv", "README.md"]
    case["files"] = {name: {"sha256": sha256((directory / name).read_bytes()).hexdigest(),
                            "bytes": (directory / name).stat().st_size} for name in generated}
    _json(directory / "case.json", case)
    return check_case(directory)


def check_case(directory: Path) -> dict:
    from slab_preflight.density import density_difference, parse_cube
    case = json.loads((directory / "case.json").read_text())
    for name, identity in case["files"].items():
        if Path(name).name != name:
            raise ValueError("Case sources must be local relative filenames.")
        data = (directory / name).read_bytes()
        if len(data) != identity["bytes"] or sha256(data).hexdigest() != identity["sha256"]:
            raise ValueError(f"Case source identity changed: {name}")
    independent = _independent_readback(directory)
    fields = [parse_cube((directory / entry["path"]).read_bytes(), kind=entry["kind"],
                         units=entry["units"], source_name=entry["path"]) for entry in case["density_sources"]]
    result = density_difference(*fields, a_indices=case["a_indices"], b_indices=case["b_indices"],
                                method=case["common_method"], reference_conditions=case["reference_conditions"],
                                frozen_geometry=case["frozen_geometry"], axis=case["normal_axis"], device="cpu")
    expected = independent["raw_difference_e_per_bohr3"] / BOHR_ANGSTROM**3
    np.testing.assert_allclose(result.grid.values, expected, rtol=1e-11, atol=1e-12)
    np.testing.assert_allclose(result.profile["average_e_per_angstrom3"], independent["average_e_per_angstrom3"], rtol=1e-11, atol=1e-12)
    np.testing.assert_allclose(result.profile["positions_angstrom"], independent["positions_angstrom"], rtol=0, atol=1e-12)
    reference = np.loadtxt(directory / "reference-profile.csv", delimiter=",", skiprows=1)
    np.testing.assert_allclose(reference[:, 0], independent["positions_angstrom"], rtol=0, atol=1e-12)
    np.testing.assert_allclose(reference[:, 1], independent["average_e_per_angstrom3"], rtol=1e-11, atol=1e-12)
    for state in case["scf"]:
        if not state["converged"] or abs(state["energy_hartree"] - state["independent_energy_hartree"]) > 1e-10:
            raise ValueError("Recorded SCF state or independently reconstructed energy is invalid.")
    return {"status": "passed", "case_id": case["case_id"], "sources_sha256_verified": len(case["files"]),
            "independent_parser": independent["parser"], "shape": list(result.grid.shape),
            "maximum_density_difference_error_e_per_angstrom3": float(np.max(np.abs(result.grid.values - expected))),
            "integrals_e": independent["integrals_e"], "difference_integral_e": result.profile["integral_e"],
            "method": case["common_method"], "reference_conditions": case["reference_conditions"]}


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", type=Path, default=CASE_DIR)
    parser.add_argument("--points", type=int, default=49)
    parser.add_argument("--check", action="store_true")
    arguments = parser.parse_args(argv)
    result = check_case(arguments.output_dir) if arguments.check else regenerate(arguments.output_dir, arguments.points)
    print(json.dumps(result, indent=2, allow_nan=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
