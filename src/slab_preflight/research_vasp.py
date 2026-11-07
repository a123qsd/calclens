"""Bounded VASP OUTCAR interpretation with separate energy conventions.

No input files, pseudopotential datasets or executables are opened. Completion
of execution, electronic convergence and ionic convergence are separate facts.
"""
from __future__ import annotations

import re

import numpy as np
from ase.data import atomic_numbers

from .result_geometry import MAX_RESULT_ATOMS, validate_geometry

NUMBER = r"[-+]?(?:\d+\.?\d*|\.\d+)(?:[DdEe][-+]?\d+)?"
VASP_BANNER = re.compile(r"^\s*vasp\.(\d+(?:\.\d+)*)(?:\s|$)", re.I)
SOURCES = {
    "outcar": "https://www.vasp.at/wiki/OUTCAR",
    "electronic_convergence": "https://www.vasp.at/wiki/EDIFF",
    "ionic_convergence": "https://www.vasp.at/wiki/EDIFFG",
    "energy_conventions": "https://www.vasp.at/wiki/Smearing_technique",
    "reference_parser": "https://gitlab.com/ase/ase/-/blob/master/ase/io/vasp_parsers/vasp_outcar_parsers.py",
}


def _number(text):
    result = float(text.replace("D", "E").replace("d", "e"))
    if not np.isfinite(result):
        raise ValueError("Non-finite number in VASP OUTCAR.")
    return result


def _vector(line, size):
    tokens = line.split()
    if len(tokens) < size or any(not re.fullmatch(NUMBER, word) for word in tokens[:size]):
        raise ValueError("Malformed VASP coordinate/lattice row.")
    return [_number(word) for word in tokens[:size]]


def _step(rows, index):
    text = "\n".join(line for _, line in rows)
    version = next(VASP_BANNER.match(line).group(1) for _, line in rows if VASP_BANNER.match(line))
    program = {"name": "VASP", "version": version, "revision": None}
    counts_match = re.search(r"ions per type\s*=\s*([^\n]+)", text)
    counts = []
    if counts_match:
        if not re.fullmatch(r"\s*\d+(?:\s+\d+)*\s*", counts_match.group(1)):
            raise ValueError("Malformed VASP ions-per-type record.")
        counts = [int(x) for x in counts_match.group(1).split()]
        if not counts or min(counts) <= 0 or sum(counts) > MAX_RESULT_ATOMS:
            raise ValueError("Invalid or oversized VASP ions-per-type record.")
    titles = re.findall(r"^\s*TITEL\s*=\s*(.+?)\s*$", text, re.M)
    if not titles:
        titles = re.findall(r"^\s*POTCAR:\s*(.+?)\s*$", text, re.M)
    species = []
    for title in titles[:len(counts)]:
        tokens = title.split()
        symbol = tokens[1].split("_")[0] if len(tokens) >= 2 else ""
        if symbol not in atomic_numbers:
            species = []
            break
        species.append(symbol)
    elements = [symbol for symbol, count in zip(species, counts) for _ in range(count)]
    if len(species) != len(counts):
        elements = []
    nions = re.search(r"\bNIONS\s*=\s*(\d+)", text)
    if nions and counts and int(nions.group(1)) != sum(counts):
        raise ValueError("VASP NIONS disagrees with ions per type.")
    settings = {}
    integer_keys = ("IBRION", "NSW", "NELM", "ISPIN", "ISMEAR", "NKPTS", "IALGO", "LDAUTYPE")
    for key in (*integer_keys, "ENCUT", "SIGMA", "EDIFF", "EDIFFG", "NELECT", "AEXX", "HFSCREEN", "NUPDOWN"):
        match = re.search(rf"\b{key}\s*=\s*({NUMBER})", text)
        if match:
            value = _number(match.group(1))
            if key in integer_keys:
                if not value.is_integer():
                    raise ValueError(f"VASP {key} must be an integer.")
                value = int(value)
            settings[key] = value
    for key in ("GGA", "METAGGA", "LHFCALC", "LDAU", "LASPH", "LNONCOLLINEAR", "LSORBIT"):
        match = re.search(rf"\b{key}\s*=\s*([^\s;]+)", text)
        if match:
            settings[key] = match.group(1)
    for key in ("LDAUL", "LDAUU", "LDAUJ"):
        match = re.search(rf"^\s*{key}\s*=\s*([^\n]+)", text, re.M)
        if match:
            settings[key] = " ".join(match.group(1).split())
    kpoints = None
    for offset, (_, line) in enumerate(rows):
        if "k-points in reciprocal lattice and weights" in line.lower():
            count = settings.get("NKPTS", 0)
            if 0 < count <= 100_000 and offset + count < len(rows):
                try:
                    kpoints = [_vector(record, 4) for _, record in rows[offset + 1:offset + 1 + count]]
                except ValueError:
                    kpoints = None
    warnings, energies, frames, ionic = [], [], [], []
    lattice = None
    lattice_line = None
    last_geometry = None
    geometry_attempted = False
    current_ionic = None
    iterations = 0
    scf_line = None
    failure_lines, completed, normal_lines = [], [], []
    last_energy_line = 0
    last_iteration_line = 0
    summary_pending = False
    active_energy = None
    active_ionic = None
    for offset, (number, line) in enumerate(rows):
        match = re.search(r"\bIteration\s+(\d+)\(\s*(\d+)\)", line)
        if match:
            label = int(match.group(1))
            if label != current_ionic:
                current_ionic, iterations, scf_line = label, 0, None
                last_geometry = None
            # Every electronic iteration starts a new energy block, even when
            # the printed outer ionic index remains unchanged.
            scf_line = None
            summary_pending = False
            active_energy = active_ionic = None
            iterations = max(iterations, int(match.group(2)))
            last_iteration_line = number
        if re.match(r"^\s*FREE ENERGIE OF THE ION-ELECTRON SYSTEM\b", line, re.I):
            # The final ionic summary uses ENERGIE. Electronic iterations print
            # the English 'Free energy ...' and must not become ionic frames.
            summary_pending = True
            active_energy = active_ionic = None
        if "aborting loop because EDIFF is reached" in line:
            scf_line = number
        if "direct lattice vectors" in line.lower():
            lattice = None
            lattice_line = number
            if offset + 3 < len(rows):
                try:
                    matrix = [_vector(row, 3) for _, row in rows[offset + 1:offset + 4]]
                    if abs(np.linalg.det(matrix)) < 1e-10:
                        raise ValueError("Singular VASP source lattice.")
                    lattice = matrix
                except ValueError as exc:
                    warnings.append(f"{exc} Source line {number}.")
        if re.match(r"^\s*POSITION\s+TOTAL-FORCE", line):
            geometry_attempted = True
            last_geometry = None
            count = sum(counts)
            try:
                if not count or not elements or lattice is None or offset + count + 2 >= len(rows):
                    raise ValueError("Missing complete atom identities, positions or lattice")
                start = offset + 1
                if re.match(r"^\s*-{5,}\s*$", rows[start][1]):
                    start += 1
                values = [_vector(row, 6) for _, row in rows[start:start + count]]
                if not re.match(r"^\s*-{5,}\s*$", rows[start + count][1]):
                    raise ValueError("Incomplete VASP force/position table")
                last_geometry = {
                    "elements": elements, "positions": [row[:3] for row in values],
                    "cell": lattice, "periodic_axes": [True, True, True], "units": "angstrom",
                    "source_units": "angstrom", "atom_indices": list(range(1, count + 1)),
                    "source": "OUTCAR POSITION / TOTAL-FORCE",
                    "line_start": number, "line_end": rows[start + count][0],
                    "cell_line": lattice_line,
                    "forces": [row[3:] for row in values], "force_units": "eV/angstrom",
                }
                validate_geometry(last_geometry)
                frames.append(last_geometry)
            except ValueError as exc:
                warnings.append(f"{exc} at line {number}; final geometry unavailable.")
        match = re.search(rf"free\s+energy\s+TOTEN\s*=\s*({NUMBER})\s+eV\b", line)
        if re.search(r"free\s+energy\s+TOTEN\s*=", line) and not match:
            raise ValueError(f"Malformed VASP TOTEN energy at line {number}.")
        if match:
            energy = {"kind": "free_energy_TOTEN", "value": _number(match.group(1)),
                      "unit": "eV", "value_ev": _number(match.group(1)), "line": number,
                      "stage": "ionic_summary" if summary_pending else "electronic_iteration",
                      "ionic_index": current_ionic, "electronic_iteration": iterations or None}
            energies.append(energy)
            active_energy, active_ionic = energy, None
            if summary_pending:
                last_energy_line = number
                status = "converged" if scf_line else (
                    "failed" if settings.get("NELM") and iterations >= settings["NELM"] else "unknown")
                active_ionic = {"index": current_ionic, "energy": energy,
                                "energies": {"free_energy_TOTEN": energy},
                                "geometry": last_geometry, "electronic_status": status,
                                "electronic_iterations": iterations, "convergence_line": scf_line}
                if ionic and current_ionic is not None and ionic[-1]["index"] == current_ionic:
                    ionic[-1] = active_ionic
                else:
                    ionic.append(active_ionic)
                summary_pending = False
        match = re.search(rf"energy\s+without entropy\s*=\s*({NUMBER})\s+energy\(sigma->0\)\s*=\s*({NUMBER})", line, re.I)
        if re.search(r"energy\s+without entropy\s*=", line, re.I) and not match:
            raise ValueError(f"Malformed VASP entropy/sigma energy at line {number}.")
        if match and active_energy:
            for kind, group in (("energy_without_entropy", 1), ("energy_sigma_to_zero", 2)):
                component = {"kind": kind, "value": _number(match.group(group)),
                             "unit": "eV", "line": number}
                active_energy[kind] = component
                if active_ionic is not None:
                    active_ionic["energies"][kind] = component
        if "reached required accuracy" in line.lower():
            completed.append(number)
        if "General timing and accounting informations for this job" in line:
            normal_lines.append(number)
        if re.search(r"VERY BAD NEWS|internal error|ERROR:|ZBRENT: fatal|BRMIX: very serious", line, re.I):
            failure_lines.append(number)
    unfinished_scf = last_iteration_line > last_energy_line or summary_pending
    final_ionic = ionic[-1] if ionic and not unfinished_scf else None
    scf_status = "converged" if scf_line else (
        "failed" if settings.get("NELM") and iterations >= settings["NELM"] else "unknown")
    status = ("failure" if failure_lines or scf_status == "failed" else
              "normal" if normal_lines and final_ionic is not None
              and normal_lines[-1] > max(last_energy_line, last_iteration_line) else "truncated")
    opt_requested = settings.get("IBRION") in (1, 2, 3) and settings.get("NSW", 0) > 0
    final_opt_completed = bool(completed and completed[-1] >= max(last_iteration_line, last_energy_line))
    opt_status = "completed" if opt_requested and final_opt_completed else "incomplete" if opt_requested else "not_requested"
    if status == "truncated":
        warnings.append("No completed OUTCAR accounting footer/final ionic record; output may be truncated or running.")
    if scf_status != "converged":
        warnings.append("Final electronic convergence is not established by an EDIFF termination marker.")
    if opt_requested and not final_opt_completed:
        warnings.append("Ionic relaxation convergence was not established.")
    if settings.get("IBRION") == 0:
        warnings.append("Molecular-dynamics trajectory; the final snapshot is not a minimized structure.")
    if not geometry_attempted:
        warnings.append("No complete POSITION/TOTAL-FORCE geometry was printed; no structure is inferred.")
    if not elements:
        warnings.append("Atom species/count mapping is missing; no geometry is assigned.")
    warnings.append("TOTEN is electronic free energy; without-entropy and sigma→0 energies remain distinct. No thermodynamic stability is inferred.")
    return {
        "index": index, "program": program,
        "line_start": rows[0][0], "line_end": rows[-1][0], "status": status,
        "supported_scope": True, "route": None, "charge": None, "multiplicity": None,
        "atom_count": sum(counts) if counts else None,
        "job_types": ["optimization" if opt_requested else "molecular_dynamics" if settings.get("IBRION") == 0 else "single_point"],
        "energies": energies, "final_scf_energy": None,
        "final_energy": final_ionic["energy"] if final_ionic else None,
        "final_energies": final_ionic["energies"] if final_ionic else {},
        "scf": {"status": scf_status, "failure_lines": failure_lines,
                "converged_energy_count": sum(i["electronic_status"] == "converged" for i in ionic)},
        "optimization": {"requested": opt_requested, "status": opt_status,
                         "completion_lines": completed, "stopped_lines": [], "convergence_criteria": []},
        "frequencies": {"requested": False, "values": [], "reported_mode_count": 0,
                        "imaginary_mode_count": 0, "minimum_certified": False},
        "geometries": frames, "final_geometry": None if unfinished_scf else last_geometry,
        "ionic_steps": ionic, "settings": settings,
        "conditions": {"program": "VASP", "settings": settings,
                       "pseudopotentials": titles[:len(counts)], "elements": elements,
                       "kpoints_reciprocal_and_weights": kpoints},
        "termination": ([{"status": "normal", "line": n} for n in normal_lines]
                        + [{"status": "failure", "line": n} for n in failure_lines]),
        "warnings": warnings,
    }


def parse_outcar(text, provenance, max_steps=128):
    rows = list(enumerate(text.splitlines(), 1))
    starts = [i for i, (_, line) in enumerate(rows) if VASP_BANNER.match(line)]
    if not starts or len(starts) > max_steps:
        raise ValueError("Missing VASP banner or too many concatenated OUTCAR jobs.")
    starts[0] = 0
    ends = [*starts[1:], len(rows)]
    steps = [_step(rows[start:end], i) for i, (start, end) in enumerate(zip(starts, ends), 1)]
    version = next(VASP_BANNER.match(line).group(1) for _, line in rows if VASP_BANNER.match(line))
    statuses = [step["status"] for step in steps]
    return {
        "schema_version": 1, "kind": "vasp_outcar", "parser": "calclens-outcar-1",
        "provenance": provenance, "program": {"name": "VASP", "version": version, "revision": None},
        "status": "failure" if "failure" in statuses else "truncated" if "truncated" in statuses else "normal",
        "steps": steps, "warnings": [warning for step in steps for warning in step["warnings"]],
        "sources": SOURCES, "units": {"energy": "eV", "length": "angstrom", "force": "eV/angstrom"},
    }
