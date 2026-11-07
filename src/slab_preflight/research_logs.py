"""A deliberately bounded, source-linked Gaussian text-output reader.

This is not a Gaussian execution engine or a replacement for a general parser
such as cclib. It reports SCF HF/KS energies, optimization markers and harmonic
frequencies. It never treats an SCF energy or a normal termination as proof of
a minimum, successful optimization, or a complete series of Link1 jobs.
"""

from __future__ import annotations

from hashlib import sha256
import re
from typing import Any

HARTREE_EV = 27.211386245988  # adopted CODATA 2018 conversion, eV / Eh
HARTREE_KJ_MOL = 2625.4996394799
MAX_LOG_BYTES = 32 * 1024 * 1024
MAX_JOB_STEPS = 128
PARSER_SOURCES = {
    "gaussian_route": "https://gaussian.com/route/",
    "gaussian_scf": "https://gaussian.com/scf/",
    "gaussian_optimization": "https://gaussian.com/opt/",
    "gaussian_frequencies": "https://gaussian.com/freq/",
    "cclib_data_notes": "https://cclib.github.io/data_notes.html",
    "hartree_conversion": "https://physics.nist.gov/cuu/Constants/",
}
_NUMBER = r"[-+]?(?:\d+\.?\d*|\.\d+)(?:[DdEe][-+]?\d+)?"
_SCF = re.compile(
    rf"SCF Done:\s+E\(([^)]+)\)\s*=\s*({_NUMBER})\s+A\.U\."
    r"(?:\s+after\s+(\d+)\s+cycles)?", re.I,
)
_UNSUPPORTED = re.compile(
    r"\b(?:oniom|td|tda|cis|cisd|mp[2-5]|ccsd|ccsd\(t\)|eom|casscf|"
    r"cas\(|cbs|g[1-4]|bomd|admp|irc|scan|counterpoise)\b", re.I,
)


class ResearchError(ValueError):
    """Research data is malformed, unsafe, or outside the declared contract."""


def convert_energy(value: float, unit: str, to_unit: str = "hartree") -> float:
    """Convert an explicitly labelled total energy; no per-atom inference."""
    import math

    factors = {
        "hartree": 1.0, "eh": 1.0, "a.u.": 1.0,
        "ev": HARTREE_EV, "mev": HARTREE_EV * 1000,
        "kj/mol": HARTREE_KJ_MOL, "kcal/mol": HARTREE_KJ_MOL / 4.184,
    }
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
        raise ResearchError("Energy must be a finite number.")
    try:
        return float(value) / factors[unit.strip().lower()] * factors[to_unit.strip().lower()]
    except (KeyError, AttributeError):
        raise ResearchError("Unsupported or missing energy unit.") from None


def _number(value: str) -> float:
    import math

    result = float(value.replace("D", "E").replace("d", "e"))
    if not math.isfinite(result):
        raise ResearchError("Non-finite number in Gaussian output.")
    return result


def _version(text: str) -> dict[str, Any]:
    match = re.search(r"Gaussian\s+(\d+)\s*:\s*([^\n]+)", text, re.I)
    if match:
        return {"name": "Gaussian", "version": match.group(1),
                "revision": match.group(2).strip()}
    match = re.search(r"Gaussian\s+(\d+)(?:,|\s+Revision\s+([\w.]+))?", text, re.I)
    return {"name": "Gaussian", "version": match.group(1) if match else None,
            "revision": match.group(2) if match else None}


def _segments(lines: list[str]) -> list[list[tuple[int, str]]]:
    """Split echoed routes / explicit Link1 boundaries, retaining line identity."""
    result: list[list[tuple[int, str]]] = []
    current: list[tuple[int, str]] = []
    has_route = has_activity = terminated = False
    for line_number, line in enumerate(lines, 1):
        route_start = bool(re.match(r"^\s*#[pPnNtT]?(?:\s|$)", line))
        explicit_step = bool(re.search(
            r"Link1:\s*Proceeding to internal job step|^\s*--Link1--\s*$", line, re.I))
        new_banner = terminated and bool(re.search(r"Entering Gaussian System", line, re.I))
        if current and (explicit_step or new_banner or (route_start and has_route and has_activity)):
            result.append(current)
            current = []
            has_route = has_activity = terminated = False
        current.append((line_number, line))
        has_route = has_route or route_start
        has_activity = has_activity or bool(re.search(
            r"SCF Done:|Charge\s*=|NAtoms\s*=|termination|Optimization|Frequencies --", line,
            re.I))
        terminated = terminated or bool(re.search(r"(?:Normal|Error) termination", line, re.I))
    if current:
        result.append(current)
    if len(result) > MAX_JOB_STEPS:
        raise ResearchError(f"At most {MAX_JOB_STEPS} Gaussian job steps are supported.")
    return result


def _parse_step(rows: list[tuple[int, str]], index: int) -> dict[str, Any]:
    route_parts: list[str] = []
    route_lines: list[int] = []
    collecting_route = False
    energies: list[dict[str, Any]] = []
    frequencies: list[dict[str, Any]] = []
    termination: list[dict[str, Any]] = []
    scf_failures: list[int] = []
    optimization_completed: list[int] = []
    optimization_stopped: list[int] = []
    convergence: list[dict[str, Any]] = []
    charge = multiplicity = natom = None
    state_line = atom_count_line = standard_basis_line = None
    standard_basis = None
    for line_number, line in rows:
        if re.match(r"^\s*#[pPnNtT]?(?:\s|$)", line):
            collecting_route = True
        elif collecting_route and (not line.strip() or re.match(r"^\s*-{4,}", line)):
            collecting_route = False
        if collecting_route:
            route_parts.append(line.strip())
            route_lines.append(line_number)
        match = re.search(r"Charge\s*=\s*(-?\d+)\s+Multiplicity\s*=\s*(\d+)", line)
        if match:
            charge, multiplicity = int(match.group(1)), int(match.group(2))
            state_line = line_number
        match = re.search(r"NAtoms\s*=\s*(\d+)", line)
        if match:
            natom = int(match.group(1))
            atom_count_line = line_number
        match = re.search(r"Standard basis:\s*(.+)", line)
        if match:
            standard_basis = match.group(1).strip()
            standard_basis_line = line_number
        match = _SCF.search(line)
        if match:
            energy = _number(match.group(2))
            energies.append({
                "kind": "SCF", "method_label": match.group(1),
                "value": energy, "unit": "hartree", "value_ev": energy * HARTREE_EV,
                "cycles": int(match.group(3)) if match.group(3) else None,
                "line": line_number,
            })
        if re.search(r"Convergence failure|SCF has not converged|SCF is not converged", line, re.I):
            scf_failures.append(line_number)
        if re.search(r"Optimization completed|Stationary point found", line, re.I):
            optimization_completed.append(line_number)
        if re.search(r"Optimization stopped|Number of steps exceeded", line, re.I):
            optimization_stopped.append(line_number)
        match = re.search(
            rf"^\s*(Maximum Force|RMS\s+Force|Maximum Displacement|RMS\s+Displacement)"
            rf"\s+({_NUMBER})\s+({_NUMBER})\s+(YES|NO)\b", line, re.I,
        )
        if match:
            convergence.append({"criterion": " ".join(match.group(1).split()),
                                "value": _number(match.group(2)),
                                "threshold": _number(match.group(3)),
                                "converged": match.group(4).upper() == "YES",
                                "line": line_number})
        match = re.search(r"Frequencies\s+--\s+(.+)", line)
        if match:
            tokens = match.group(1).split()
            if not tokens or any(not re.fullmatch(_NUMBER, token) for token in tokens):
                raise ResearchError(f"Malformed Gaussian frequencies at line {line_number}.")
            frequencies.extend({"value": _number(token), "unit": "cm^-1", "line": line_number}
                               for token in tokens)
        if re.search(r"Normal termination of Gaussian", line, re.I):
            termination.append({"status": "normal", "line": line_number, "text": line.strip()})
        if re.search(r"Error termination|Erroneous write|galloc:.*failed", line, re.I):
            termination.append({"status": "failure", "line": line_number, "text": line.strip()})
    route = " ".join(route_parts) or None
    method_basis = re.search(r"(?:^|\s)([A-Za-z][\w()+,-]*)/([^\s]+)", route or "")
    method = method_basis.group(1) if method_basis else None
    basis = method_basis.group(2) if method_basis else None
    requested_opt = bool(re.search(r"\bopt(?:\b|=|\()", route or "", re.I))
    requested_freq = bool(re.search(r"\bfreq(?:\b|=|\()", route or "", re.I))
    unsupported = _UNSUPPORTED.search(route or "")
    # A failed iterative stage takes precedence over an earlier normal marker.
    if any(item["status"] == "failure" for item in termination) or scf_failures:
        status = "failure"
    elif any(item["status"] == "normal" for item in termination):
        status = "normal"
    else:
        status = "truncated"
    scf_status = "unknown"
    if energies:
        scf_status = "converged"
    if scf_failures and (not energies or scf_failures[-1] > energies[-1]["line"]):
        scf_status = "failed"
    if optimization_stopped:
        opt_status = "stopped"
    elif optimization_completed:
        opt_status = "completed"
    else:
        opt_status = "incomplete" if requested_opt else "not_requested"
    warnings = []
    if status == "truncated":
        warnings.append("No normal/error termination marker; file may be incomplete or still running.")
    if requested_opt and opt_status != "completed":
        warnings.append("A completed optimization was not established.")
    if requested_freq and not frequencies:
        warnings.append("Requested harmonic frequencies were not found.")
    if frequencies:
        warnings.append("Frequencies are reported values; mode completeness and a minimum are not certified.")
    supported = route is not None and unsupported is None
    if not supported:
        warnings.append("Route is missing or contains a job outside the bounded SCF/Opt/Freq scope.")
    return {
        "index": index, "line_start": rows[0][0], "line_end": rows[-1][0],
        "status": status, "supported_scope": supported, "route": route,
        "route_lines": route_lines, "method": method, "basis": basis,
        "printed_standard_basis": standard_basis,
        "printed_standard_basis_line": standard_basis_line,
        "charge": charge, "multiplicity": multiplicity, "atom_count": natom,
        "state_line": state_line, "atom_count_line": atom_count_line,
        "job_types": (["optimization"] if requested_opt else [])
        + (["frequencies"] if requested_freq else [])
        or ["single_point"],
        "energies": energies, "final_scf_energy": energies[-1] if energies else None,
        "scf": {"status": scf_status, "failure_lines": scf_failures,
                "converged_energy_count": len(energies)},
        "optimization": {"requested": requested_opt, "status": opt_status,
                         "completion_lines": optimization_completed,
                         "stopped_lines": optimization_stopped,
                         "convergence_criteria": convergence},
        "frequencies": {"requested": requested_freq, "values": frequencies,
                        "reported_mode_count": len(frequencies),
                        "imaginary_mode_count": sum(item["value"] < 0 for item in frequencies),
                        "minimum_certified": False},
        "termination": termination, "warnings": warnings,
    }


def parse_log(data: bytes, *, source_name: str = "gaussian.log",
              source_url: str | None = None) -> dict[str, Any]:
    """Read bytes without changing them and return a JSON-safe interpretation.

    Callers should save the original bytes alongside this report. The exact
    byte hash and source-line references allow checking every extracted value.
    Only Gaussian text logs are recognized; arbitrary files stay ``unknown``.
    A normal earlier Link1 job never hides a failed/truncated later job.
    """
    if not isinstance(data, bytes) or len(data) > MAX_LOG_BYTES:
        raise ResearchError(f"A log must be bytes, at most {MAX_LOG_BYTES} bytes.")
    text = data.decode("utf-8", errors="replace")
    recognized = bool(re.search(r"Gaussian\s+(?:\d+|System)|Entering Gaussian System", text, re.I))
    report: dict[str, Any] = {
        "schema_version": 1, "kind": "gaussian_log", "parser": "calclens-bounded-1",
        "provenance": {"name": source_name, "sha256": sha256(data).hexdigest(),
                       "size_bytes": len(data), "source_url": source_url,
                       "original_preserved": "Caller retains exact input bytes; parser is read-only."},
        "program": _version(text) if recognized else {"name": None, "version": None,
                                                       "revision": None},
        "status": "unknown", "steps": [], "warnings": [], "sources": PARSER_SOURCES,
        "units": {"scf_energy": "hartree", "converted_energy": "eV",
                  "hartree_to_ev": HARTREE_EV, "conversion_standard": "adopted CODATA 2018",
                  "frequency": "cm^-1"},
    }
    if not recognized:
        report["warnings"] = ["Unrecognized output; no calculation success is inferred."]
        return report
    steps = [_parse_step(segment, index) for index, segment in
             enumerate(_segments(text.splitlines()), 1)]
    report["steps"] = steps
    statuses = [step["status"] for step in steps]
    report["status"] = ("failure" if "failure" in statuses else
                        "truncated" if "truncated" in statuses else
                        "normal" if statuses else "unknown")
    report["warnings"] = [warning for step in steps for warning in step["warnings"]]
    if len(steps) > 1:
        report["warnings"].insert(0, "Multiple job steps are kept separate; select a step before comparing.")
    return report
