"""Run the optional real H2O RHF/STO-3G case or check its bundled results.

The calculation uses PySCF only in regeneration mode. --check needs CalcLens's
normal NumPy/ASE environment and independently reads Cube data with ASE.
No network access or electronic-structure dependency is needed to view/check
the committed results. This molecular job has no periodic boundary conditions.
"""

from __future__ import annotations

import argparse
from hashlib import sha256
from io import StringIO
import json
from pathlib import Path
import platform

import numpy as np
from ase.io.cube import read_cube
from ase.units import Bohr as ASE_BOHR_ANGSTROM


ROOT = Path(__file__).resolve().parents[1]
CASE_DIR = ROOT / "examples" / "electronic_case"
SOURCE = CASE_DIR / "source" / "water.xyz"
CELL_ANGSTROM = 12.0
TRANSLATION_ANGSTROM = np.array([6.0, 6.0, 6.0])
GRID_SHAPE = (30, 30, 30)
GRID_MARGIN_BOHR = 4.0
CONV_TOL = 1e-12
CONV_TOL_GRAD = 1e-8
ENERGY_TOLERANCE_HARTREE = 1e-9
MATRIX_TOLERANCE = 1e-7
BOHR_ANGSTROM = 0.529177210903
SOURCE_URLS = {
    "pyscf_rhf": "https://pyscf.org/quickstart.html#hartree-fock",
    "pyscf_mulliken": "https://pyscf.org/_modules/pyscf/scf/hf.html#mulliken_pop",
    "pyscf_lowdin": "https://pyscf.org/_modules/pyscf/lo/orth.html#lowdin",
    "pyscf_cube": "https://pyscf.org/_modules/pyscf/tools/cubegen.html",
    "ase_cube": "https://gitlab.com/ase/ase/-/blob/3.29.0/ase/io/cube.py",
}


def json_text(document: dict) -> str:
    return json.dumps(document, indent=2, allow_nan=False) + "\n"


def write_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(text.encode("utf-8"))


def source_atoms() -> tuple[list[str], np.ndarray]:
    """Read the explicit fixed input, rejecting accidental changes in scope."""
    lines = SOURCE.read_text(encoding="utf-8").splitlines()
    if len(lines) != 5 or lines[0].strip() != "3":
        raise ValueError("This case requires the bundled three-atom water input.")
    rows = [line.split() for line in lines[2:]]
    if any(len(row) != 4 for row in rows) or [row[0] for row in rows] != ["O", "H", "H"]:
        raise ValueError("The electronic case must retain the original O,H,H atom order.")
    points = np.array([[float(value) for value in row[1:]] for row in rows])
    if not np.isfinite(points).all():
        raise ValueError("Input coordinates must be finite.")
    return [row[0] for row in rows], points


def water_cif(elements: list[str], positions: np.ndarray) -> str:
    """Put a molecular input in a P1 display cell without changing its order."""
    lines = [
        "# Real PySCF molecular RHF/STO-3G output; this cell is for display only.",
        "# Isolated H2O; no periodic electronic calculation or geometry optimization.",
        "data_water_rhf_sto3g",
        "_cell_length_a 12", "_cell_length_b 12", "_cell_length_c 12",
        "_cell_angle_alpha 90", "_cell_angle_beta 90", "_cell_angle_gamma 90",
        "_space_group_IT_number 1", "_space_group_name_H-M_alt 'P 1'",
        "loop_", "_space_group_symop_operation_xyz", "'x,y,z'", "loop_",
        "_atom_site_label", "_atom_site_type_symbol", "_atom_site_fract_x",
        "_atom_site_fract_y", "_atom_site_fract_z", "_atom_site_occupancy",
    ]
    for index, (element, point) in enumerate(zip(elements, positions), 1):
        x, y, z = point / CELL_ANGSTROM
        lines.append(f"{element}{index} {element} {x:.12f} {y:.12f} {z:.12f} 1")
    return "\n".join(lines) + "\n"


def atom_charges(population: np.ndarray, ao_atoms: list[int]) -> np.ndarray:
    result = np.array([8.0, 1.0, 1.0])
    for atom, value in zip(ao_atoms, population):
        result[atom] -= value
    return result


def independent_matrix_check(state: dict) -> dict:
    """Reconstruct the HF energy/charges with NumPy, without PySCF APIs.

    Integrals still originate from PySCF. This checks numerical export and
    consistency, not an independent implementation of the integral engine.
    """
    overlap = np.array(state["overlap"])
    density = np.array(state["density_matrix"])
    core = np.array(state["core_hamiltonian"])
    eri = np.array(state["electron_repulsion_integrals_chemist"])
    coefficients = np.array(state["mo_coefficients"])
    occupations = np.array(state["mo_occupations"])
    energies = np.array(state["mo_energies_hartree"])
    coulomb = np.einsum("kl,ijkl->ij", density, eri)
    exchange = np.einsum("kl,ikjl->ij", density, eri)
    fock = core + coulomb - 0.5 * exchange
    energy = float(np.einsum("ij,ji", density, core + fock) * 0.5
                   + state["nuclear_repulsion_hartree"])
    eigenvalues, eigenvectors = np.linalg.eigh(overlap)
    square_root = (eigenvectors * np.sqrt(eigenvalues)) @ eigenvectors.T
    mulliken = atom_charges(np.diag(density @ overlap), state["ao_atom_indices_zero_based"])
    lowdin = atom_charges(np.diag(square_root @ density @ square_root),
                          state["ao_atom_indices_zero_based"])
    checks = {
        "electron_count_trace_ps": float(np.trace(density @ overlap)),
        "energy_reconstructed_hartree": energy,
        "energy_error_hartree": abs(energy - state["total_energy_hartree"]),
        "mo_orthonormality_max_error": float(np.max(np.abs(
            coefficients.T @ overlap @ coefficients - np.eye(len(energies))))),
        "density_from_occupied_mos_max_error": float(np.max(np.abs(
            density - (coefficients * occupations) @ coefficients.T))),
        "roothaan_max_residual": float(np.max(np.abs(
            fock @ coefficients - (overlap @ coefficients) * energies))),
        "mulliken_charges_e": mulliken.tolist(),
        "lowdin_charges_e": lowdin.tolist(),
        "mulliken_net_charge_e": float(mulliken.sum()),
        "lowdin_net_charge_e": float(lowdin.sum()),
    }
    if abs(checks["electron_count_trace_ps"] - 10) > MATRIX_TOLERANCE:
        raise ValueError("Independent AO electron count differs from 10.")
    if checks["energy_error_hartree"] > ENERGY_TOLERANCE_HARTREE:
        raise ValueError("Independent HF energy reconstruction failed.")
    if any(checks[key] > MATRIX_TOLERANCE for key in (
        "mo_orthonormality_max_error", "density_from_occupied_mos_max_error",
        "roothaan_max_residual",
    )):
        raise ValueError("Independent wavefunction matrix consistency check failed.")
    return checks


def read_cube_independently(path: Path) -> dict:
    """Use ASE's parser, never CalcLens's or PySCF's Cube parser."""
    with path.open(encoding="utf-8") as handle:
        return read_cube(handle, read_data=True)


def cube_stats(parsed: dict) -> dict:
    data = parsed["data"]
    spacing_bohr = np.array(parsed["spacing"]) / ASE_BOHR_ANGSTROM
    weights = np.ones(data.shape)
    for axis in range(3):
        edge = [slice(None)] * 3
        edge[axis] = [0, -1]
        weights[tuple(edge)] *= 0.5
    voxel_volume = float(abs(np.linalg.det(spacing_bohr)))
    return {
        "shape": list(data.shape), "point_count": int(data.size),
        "minimum": float(data.min()), "maximum": float(data.max()),
        "voxel_volume_bohr3": voxel_volume,
        "trapezoidal_integral": float(np.sum(data * weights) * voxel_volume),
        "trapezoidal_squared_integral": float(np.sum(data**2 * weights) * voxel_volume),
        "origin_angstrom": parsed["origin"].tolist(),
        "spacing_angstrom": parsed["spacing"].tolist(),
    }


def check_case(directory: Path) -> dict:
    """Verify artifact identity, atom mapping, field scalars, and HF invariants."""
    manifest = json.loads((directory / "manifest.json").read_bytes())
    for filename, digest in manifest["sha256"].items():
        path = directory / filename
        if not path.is_file() or sha256(path.read_bytes()).hexdigest() != digest:
            raise ValueError(f"Electronic-case SHA-256 mismatch: {filename}")
    if sha256(Path(__file__).read_bytes()).hexdigest() != manifest["preparation_script_sha256"]:
        raise ValueError("Electronic-case preparation script SHA-256 mismatch.")
    calculation = json.loads((directory / "calculation.json").read_bytes())
    state = json.loads((directory / "wavefunction.json").read_bytes())
    matrix_check = independent_matrix_check(state)
    elements, original = source_atoms()
    points = original + TRANSLATION_ANGSTROM
    cif = (directory / "water.cif").read_bytes()
    if cif.decode("utf-8") != water_cif(elements, points):
        raise ValueError("CIF no longer preserves the translated input coordinates/order.")
    structure_sha256 = sha256(cif).hexdigest()
    for method in ("mulliken", "lowdin"):
        charge = json.loads((directory / f"charges_{method}.json").read_bytes())
        if charge["structure_sha256"] != structure_sha256 or charge["kind"] != "partial_charge":
            raise ValueError("Charge data is not bound to the exact molecular CIF.")
        if charge["schema_version"] != 1 or not charge["method"] or not charge["source"]:
            raise ValueError("Charge metadata is incomplete.")
        if [(atom["index"], atom["element"]) for atom in charge["atoms"]] != [
            (1, "O"), (2, "H"), (3, "H"),
        ]:
            raise ValueError("Charge atom order does not match the molecular CIF.")
        if not np.allclose([atom["value"] for atom in charge["atoms"]],
                           matrix_check[f"{method}_charges_e"], atol=1e-10, rtol=0):
            raise ValueError(f"{method} charge export differs from independent AO analysis.")
    fields = {}
    for filename in ("density.cube", "homo.cube"):
        parsed = read_cube_independently(directory / filename)
        if parsed["atoms"].get_chemical_symbols() != elements:
            raise ValueError("Cube atomic numbers/order differ from the input.")
        if not np.allclose(parsed["atoms"].positions, points, atol=1e-6, rtol=0):
            raise ValueError("Cube positions differ from the translated input.")
        if tuple(parsed["data"].shape) != GRID_SHAPE or not np.isfinite(parsed["data"]).all():
            raise ValueError("Cube shape or scalar values differ from the case contract.")
        fields[filename] = cube_stats(parsed)
    if fields["density.cube"]["minimum"] < 0:
        raise ValueError("Total electron density contains a negative scalar.")
    if not fields["homo.cube"]["minimum"] < 0 < fields["homo.cube"]["maximum"]:
        raise ValueError("The real HOMO field must contain both wavefunction signs.")
    if not calculation["converged"] or calculation["periodic_calculation"]:
        raise ValueError("This case must remain a converged molecular calculation.")
    return {"matrix_check": matrix_check, "ase_cube_check": fields}


def reference_plot(directory: Path) -> None:
    """A second visualization: ASE-read x/z sections through the oxygen atom."""
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    figure, axes = plt.subplots(1, 2, figsize=(10, 4.2), constrained_layout=True)
    for axis, filename, title, level in zip(
        axes, ("density.cube", "homo.cube"),
        ("RHF total electron density", "HOMO (MO 5), signed amplitude"), (0.05, 0.05),
    ):
        parsed = read_cube_independently(directory / filename)
        origin = parsed["origin"]
        spacing = parsed["spacing"]
        data = parsed["data"]
        y = origin[1] + np.arange(data.shape[1]) * spacing[1, 1]
        iy = int(np.argmin(np.abs(y - 6.0)))
        x = origin[0] + np.arange(data.shape[0]) * spacing[0, 0] - 6.0
        z = origin[2] + np.arange(data.shape[2]) * spacing[2, 2] - 6.0
        section = data[:, iy, :].T
        levels = np.linspace(-0.35, 0.35, 29) if filename == "homo.cube" else np.geomspace(
            max(float(section.min()), 1e-6), float(section.max()), 28,
        )
        image = axis.contourf(x, z, section, levels=levels,
                              cmap="RdBu_r" if filename == "homo.cube" else "viridis",
                              extend="both")
        axis.contour(x, z, section, levels=[-level, level] if filename == "homo.cube" else [level],
                     colors=["#2769ac", "#c34838"] if filename == "homo.cube" else ["#ffffff"],
                     linewidths=1.0)
        axis.scatter([0], [0], c="#de453d", s=44, edgecolors="white", zorder=3)
        axis.text(0.1, 0.05, "O", color="black")
        axis.set(title=title, xlabel="x relative to O (angstrom)",
                 ylabel="z relative to O (angstrom)", aspect="equal")
        colorbar = figure.colorbar(
            image, ax=axis, shrink=0.78,
            label="bohr^-3/2" if filename == "homo.cube" else "e/bohr^3",
            format="%.2f" if filename == "homo.cube" else "%.0e",
        )
        colorbar.ax.tick_params(labelsize=8)
    figure.suptitle("Independent ASE + Matplotlib readback; nearest sampled y plane")
    figure.savefig(directory / "reference_sections.png", dpi=160,
                   metadata={"Software": "ASE Cube reader + Matplotlib"})
    plt.close(figure)


def run_case(directory: Path) -> dict:
    """Execute an actual SCF calculation and export its computed quantities."""
    try:
        import ase
        import h5py
        import pyscf
        from pyscf import dft, gto, lib, lo, scf
        from pyscf.tools import cubegen
        import scipy
    except ImportError as error:
        raise RuntimeError("Regeneration needs the optional electronic-case requirements.txt.") from error

    directory.mkdir(parents=True, exist_ok=True)
    (directory / "source").mkdir(exist_ok=True)
    elements, original = source_atoms()
    write_text(directory / "source" / "water.xyz", SOURCE.read_text(encoding="utf-8"))
    points = original + TRANSLATION_ANGSTROM
    cif = water_cif(elements, points)
    write_text(directory / "water.cif", cif)
    structure_sha256 = sha256(cif.encode("utf-8")).hexdigest()
    lib.num_threads(1)
    log = StringIO()
    molecule = gto.M(atom=list(zip(elements, points.tolist())), unit="Angstrom",
                     basis="sto-3g", charge=0, spin=0, symmetry=False, verbose=0)
    # Capture only the SCF trace: Mole.build's machine/host/path dump is omitted.
    mean_field = scf.RHF(molecule)
    mean_field.stdout = log
    mean_field.verbose = 4
    mean_field.conv_tol = CONV_TOL
    mean_field.conv_tol_grad = CONV_TOL_GRAD
    mean_field.max_cycle = 100
    mean_field.chkfile = None
    energy = float(mean_field.kernel())
    if not mean_field.converged:
        raise RuntimeError("The real electronic case did not converge; no result may be claimed.")
    density_matrix = mean_field.make_rdm1()
    overlap = mean_field.get_ovlp()
    ao_atoms = [label[0] for label in molecule.ao_labels(fmt=False)]
    _, mulliken = mean_field.mulliken_pop(verbose=0)
    # Full symmetric Lowdin: S^(1/2) P S^(1/2); no meta-Lowdin/pre-orthogonalization.
    inverse_square_root = lo.orth.lowdin(overlap)
    square_root = overlap @ inverse_square_root
    lowdin = atom_charges(np.diag(square_root @ density_matrix @ square_root), ao_atoms)
    homo = int(np.flatnonzero(mean_field.mo_occ > 0)[-1])
    coefficients = mean_field.mo_coeff.copy()
    # Canonical MO phases are arbitrary. Choose positive largest-magnitude AO coefficient.
    if coefficients[np.argmax(np.abs(coefficients[:, homo])), homo] < 0:
        coefficients[:, homo] *= -1
    state = {
        "description": "Real converged molecular RHF/STO-3G matrices; no ECP or frozen core",
        "ao_labels": molecule.ao_labels(), "ao_atom_indices_zero_based": ao_atoms,
        "overlap": overlap.tolist(), "density_matrix": density_matrix.tolist(),
        "core_hamiltonian": mean_field.get_hcore().tolist(),
        "electron_repulsion_integrals_chemist": molecule.intor("int2e", aosym="s1").tolist(),
        "mo_coefficients": coefficients.tolist(), "mo_occupations": mean_field.mo_occ.tolist(),
        "mo_energies_hartree": mean_field.mo_energy.tolist(),
        "nuclear_repulsion_hartree": float(molecule.energy_nuc()),
        "total_energy_hartree": energy,
    }
    matrix_check = independent_matrix_check(state)
    write_text(directory / "wavefunction.json", json_text(state))
    write_text(directory / "scf.log", "PySCF " + pyscf.__version__
               + "; isolated H2O; RHF/STO-3G; charge 0; spin 0; fixed XYZ input\n"
               + "Coordinates translated by (+6,+6,+6) angstrom for display only.\n"
               + log.getvalue())
    for method, values in (("mulliken", mulliken), ("lowdin", lowdin)):
        label = "Mulliken" if method == "mulliken" else "Lowdin symmetric orthogonalization"
        document = {
            "schema_version": 1, "structure_sha256": structure_sha256,
            "kind": "partial_charge", "method": f"{label}; RHF/STO-3G",
            "source": f"PySCF {pyscf.__version__}; actual molecular H2O calculation; calculation.json",
            "atoms": [{"index": index, "element": element, "value": float(value)}
                      for index, (element, value) in enumerate(zip(elements, values), 1)],
        }
        write_text(directory / f"charges_{method}.json", json_text(document))
        write_text(directory / f"charges_{method}.csv", "index,element,partial_charge_e,method\n"
                   + "".join(f"{i},{element},{float(value):.15g},{label}\n"
                             for i, (element, value) in enumerate(zip(elements, values), 1)))
    exported = {}
    for filename, kind in (("density.cube", "density"), ("homo.cube", "orbital")):
        if kind == "density":
            values = cubegen.density(molecule, str(directory / filename), density_matrix,
                                    nx=GRID_SHAPE[0], ny=GRID_SHAPE[1], nz=GRID_SHAPE[2],
                                    resolution=None, margin=GRID_MARGIN_BOHR)
        else:
            values = cubegen.orbital(molecule, str(directory / filename), coefficients[:, homo],
                                    nx=GRID_SHAPE[0], ny=GRID_SHAPE[1], nz=GRID_SHAPE[2],
                                    resolution=None, margin=GRID_MARGIN_BOHR)
        # Preserve all numerical PySCF output; replace only the nondeterministic date comment.
        lines = (directory / filename).read_text(encoding="utf-8").splitlines()
        lines[1] = f"PySCF {pyscf.__version__}; isolated H2O RHF/STO-3G; source/water.xyz"
        write_text(directory / filename, "\n".join(lines) + "\n")
        parsed = read_cube_independently(directory / filename)
        if not np.allclose(parsed["data"], values, rtol=5.1e-6, atol=1e-14):
            raise ValueError("ASE Cube readback differs from the actually computed field.")
        exported[filename] = {**cube_stats(parsed),
                              "max_export_absolute_error": float(np.max(np.abs(
                                  parsed["data"] - values)))}
    grids = dft.gen_grid.Grids(molecule)
    grids.level = 5
    grids.build()
    ao = molecule.eval_gto("GTOval_sph", grids.coords)
    quadrature_electrons = float(np.dot(
        np.einsum("pi,ij,pj->p", ao, density_matrix, ao), grids.weights,
    ))
    if abs(quadrature_electrons - 10) > 1e-5:
        raise ValueError("Atom-centered density quadrature differs from 10 electrons.")
    calculation = {
        "case": "Actual isolated H2O RHF/STO-3G calculation; original illustrative geometry",
        "program": "PySCF", "program_version": pyscf.__version__,
        "python_version": platform.python_version(),
        "environment": {"numpy": np.__version__, "scipy": scipy.__version__,
                        "h5py": h5py.__version__, "ase": ase.__version__},
        "method": "RHF", "basis": "STO-3G", "charge": 0, "spin_2s": 0,
        "electron_count": molecule.nelectron, "basis_function_count": molecule.nao_nr(),
        "converged": bool(mean_field.converged), "scf_cycles": int(mean_field.cycles),
        "energy_hartree": energy, "energy_convergence_tolerance_hartree": CONV_TOL,
        "gradient_convergence_tolerance": CONV_TOL_GRAD,
        "maximum_scf_cycles": 100, "threads": 1,
        "geometry_optimization_performed": False, "periodic_calculation": False,
        "input_units": "angstrom", "source_geometry": "source/water.xyz",
        "atom_order": elements, "display_translation_angstrom": TRANSLATION_ANGSTROM.tolist(),
        "display_cell_angstrom": [CELL_ANGSTROM] * 3,
        "structure_sha256": structure_sha256,
        "cube": {"shape": list(GRID_SHAPE), "margin_bohr": GRID_MARGIN_BOHR,
                 "spatial_units": "bohr; all voxel counts positive; z fastest",
                 "density_units": "e/bohr^3", "orbital_units": "bohr^-3/2",
                 "comments_modified": "Only the PySCF date comment is replaced for reproducibility.",
                 "scalar_precision": "PySCF cubegen default: %13.5E (six significant digits)",
                 "orbital_index_one_based": homo + 1,
                 "orbital_energy_hartree": float(mean_field.mo_energy[homo]),
                 "orbital_occupation": float(mean_field.mo_occ[homo]),
                 "orbital_phase_convention": "Largest-magnitude AO coefficient made positive",
                 "display_density_isovalue": 0.05, "display_orbital_isovalue": 0.05},
        "references": SOURCE_URLS,
        "limitations": [
            "Fixed illustrative molecular geometry; not experimentally sourced or optimized.",
            "RHF and minimal STO-3G are an educational calculation, not chemical accuracy evidence.",
            "Partial charges are partition-dependent; neither method is an oxidation state.",
            "The 12 angstrom P1 cell is only a display container; it did not enter the molecular SCF.",
            "The coarse finite Cube is for display, not an accurate electron-count integration grid.",
            "Independent checks share PySCF integrals/AO evaluator; no second electronic code was run.",
        ],
    }
    write_text(directory / "calculation.json", json_text(calculation))
    independent = {
        "method": "NumPy HF reconstruction + ASE Cube parser + separate atom-centered quadrature",
        "scope": "Export, order, units, matrix consistency; not independent integral-engine validation",
        "matrix_check": matrix_check, "ase_cube_check": exported,
        "atom_centered_quadrature": {"program": "PySCF dft.gen_grid level 5; RHF density",
                                     "point_count": len(grids.weights),
                                     "electron_count": quadrature_electrons,
                                     "absolute_error": abs(quadrature_electrons - 10)},
    }
    write_text(directory / "independent_check.json", json_text(independent))
    reference_plot(directory)
    names = ["source/water.xyz", "water.cif", "charges_mulliken.json", "charges_lowdin.json",
             "charges_mulliken.csv", "charges_lowdin.csv", "density.cube", "homo.cube",
             "wavefunction.json", "scf.log", "calculation.json", "independent_check.json",
             "reference_sections.png"]
    manifest = {"schema_version": 1, "preparation_script": "scripts/prepare_electronic_case.py",
                "preparation_script_sha256": sha256(Path(__file__).read_bytes()).hexdigest(),
                "sha256": {name: sha256((directory / name).read_bytes()).hexdigest()
                           for name in names}}
    write_text(directory / "manifest.json", json_text(manifest))
    return check_case(directory)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", type=Path, default=CASE_DIR)
    parser.add_argument("--check", action="store_true",
                        help="Check committed artifacts without PySCF or network access")
    args = parser.parse_args()
    try:
        result = check_case(args.output_dir) if args.check else run_case(args.output_dir)
    except (ValueError, RuntimeError) as error:
        parser.exit(1, f"Electronic case failed: {error}\n")
    print("Real molecular case verified: energy = "
          f"{result['matrix_check']['energy_reconstructed_hartree']:.12f} hartree; "
          "ASE readback checked both 30x30x30 Cube fields.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
