"""Explicit correspondence/registration contracts for native structure comparison."""
from __future__ import annotations

import numpy as np
from ase.geometry import find_mic

from .research_logs import convert_energy


def compare_coordinates(left, right, *, correspondence=False, mode="cartesian"):
    """Index-to-index displacements; no permutation, reflection or cell matching.

    Molecular rigid fitting uses equal atom weights and a proper Kabsch rotation.
    Periodic minimum-image displacements require the same supplied lattice and
    use ASE's general skew-cell MIC, rather than rounding fractional coordinates.
    """
    missing = {"status": "unavailable", "reason": "Two complete source structures are required."}
    if not left or not right:
        return missing
    if left.get("units", {}).get("length") != "angstrom" or right.get("units", {}).get("length") != "angstrom":
        return {**missing, "reason": "Coordinate units must explicitly agree in angstrom."}
    if not correspondence:
        return {**missing, "reason": "Confirm source atom-index correspondence before calculating displacement."}
    if left.get("elements") != right.get("elements"):
        return {**missing, "reason": "Atom count/element order differs; no automatic atom matching is performed."}
    try:
        a, b = np.asarray(left["positions"], float), np.asarray(right["positions"], float)
    except (KeyError, TypeError, ValueError):
        return missing
    if (a.shape != b.shape or a.ndim != 2 or a.shape[1:] != (3,) or len(a) == 0
            or not np.isfinite(a).all() or not np.isfinite(b).all()):
        return missing
    pbc_left = left.get("periodic_axes")
    pbc_right = right.get("periodic_axes")
    if (not isinstance(pbc_left, list) or not isinstance(pbc_right, list)
            or len(pbc_left) != 3 or pbc_left != pbc_right
            or any(type(v) is not bool for v in pbc_left)):
        return {**missing, "reason": "Periodicity differs or is unspecified; molecular/periodic registration is not inferred."}
    if mode == "rigid":
        if any(pbc_left):
            return {**missing, "reason": "Rigid alignment is available only for nonperiodic molecular structures."}
        a = a - a.mean(axis=0)
        b = b - b.mean(axis=0)
        u, _, vt = np.linalg.svd(b.T @ a)
        correction = np.eye(3)
        correction[-1, -1] = np.linalg.det(u @ vt)
        delta = b @ (u @ correction @ vt) - a
        reference = "Equal-weight proper rigid fit; translation/rotation removed; reflections and permutations excluded."
    elif mode == "minimum_image":
        ca, cb = np.asarray(left.get("cell"), float), np.asarray(right.get("cell"), float)
        if (ca.shape != (3, 3) or cb.shape != (3, 3) or not any(pbc_left)
                or not np.isfinite(ca).all() or not np.isfinite(cb).all()
                or abs(np.linalg.det(ca)) < 1e-10
                or not np.allclose(ca, cb, atol=1e-8, rtol=1e-8)):
            return {**missing, "reason": "Minimum-image comparison requires the same finite periodic cell (1e-8 Å tolerance)."}
        delta, _ = find_mic(b - a, cell=ca, pbc=pbc_left)
        reference = "Per-atom minimum image in the same supplied lattice; no global translation, permutation or cell registration."
    elif mode == "cartesian":
        delta = b - a
        reference = "Supplied Cartesian coordinates; no translation/rotation removal, wrapping or cell registration."
    else:
        return {**missing, "reason": "Unknown coordinate comparison convention."}
    displacement = np.linalg.norm(delta, axis=1)
    return {"status": "available", "unit": "angstrom", "mode": mode,
            "correspondence": "same one-based source atom indices; confirmed by user",
            "reference": reference, "rmsd": float(np.sqrt(np.mean(displacement ** 2))),
            "maximum": float(displacement.max()), "displacements": displacement.tolist(),
            "largest_atom_index": int(np.argmax(displacement)) + 1}


def energy_comparison(left_entry, right_entry, *, reviewed=False):
    """Only subtract the same printed energy convention after input review.

    A route/settings summary cannot prove complete Hamiltonian equivalence.
    User review of complete original inputs is therefore required even when
    all extracted conditions agree. Known differences always block subtraction.
    """
    result = {"status": "unavailable", "reason": "Calculation energies are absent from one or both sources."}
    outputs = [entry.get("output") if entry else None for entry in (left_entry, right_entry)]
    if not all(outputs):
        return result
    a, b = [item["step"] for item in outputs]
    ea, eb = a.get("final_energy"), b.get("final_energy")
    if not ea or not eb:
        return result
    if (outputs[0]["program"] != outputs[1]["program"] or ea["kind"] != eb["kind"]
            or ea.get("method_label") != eb.get("method_label")):
        return {**result, "reason": "Program/energy conventions differ; no cross-program total-energy subtraction."}
    if any(s.get("status") != "normal" or s.get("scf", {}).get("status") != "converged"
           or not s.get("supported_scope") for s in (a, b)):
        return {**result, "reason": "Both selected jobs require supported scope, completed execution and final electronic convergence."}
    reports = [entry["analysis"].get("report") for entry in (left_entry, right_entry)]
    if (not all(reports) or reports[0].get("elements") != reports[1].get("elements")):
        return {**result, "reason": "Atom composition/order differs; total energies are not compared."}
    ca, cb = a.get("conditions", {}), b.get("conditions", {})
    if not ca or ca != cb:
        return {**result, "reason": "Extracted calculation conditions differ or are missing."}
    if ca.get("program") == "Gaussian" and any(ca.get(k) is None for k in ("method", "basis", "charge", "multiplicity")):
        return {**result, "reason": "Gaussian method/basis/charge/multiplicity is incomplete."}
    if ca.get("program") == "VASP" and (not ca.get("pseudopotentials") or not ca.get("kpoints_reciprocal_and_weights") or
            any(k not in ca.get("settings", {}) for k in ("ENCUT", "ISMEAR", "SIGMA", "ISPIN", "NKPTS", "NELECT"))):
        return {**result, "reason": "VASP pseudopotential or required printed settings are incomplete."}
    if not reviewed:
        return {**result, "reason": "Review full inputs: method/basis or potentials, charge/spin, k-points, smearing and reference conditions. Printed summaries alone are insufficient."}
    try:
        delta = convert_energy(eb["value"], eb["unit"], "eV") - convert_energy(ea["value"], ea["unit"], "eV")
    except (KeyError, ValueError, TypeError):
        return {**result, "reason": "Missing/unsupported finite energy value or unit."}
    return {"status": "available", "delta": delta, "unit": "eV", "kind": ea["kind"],
            "reason": "Δ right−left after full-input review; this difference alone does not establish stability."}
