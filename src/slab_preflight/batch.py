"""Bounded, independent CIF comparisons with per-file measurement settings."""
from __future__ import annotations

import csv
from dataclasses import dataclass
import hashlib
import io

import ase

from . import __version__
from .core import UnsupportedStructure, analyze_cif
from .provenance import with_provenance
from .reporting import _spreadsheet_text, localized_error_message

MAX_BATCH_FILES = 20


@dataclass(frozen=True)
class BatchInput:
    filename: str
    data: bytes
    normal_axis: str = "c"
    short_distance: float = 1.0


def analyze_batch(inputs: list[BatchInput]) -> list[dict]:
    """Keep input order and failed entries; one invalid CIF does not abort the rest."""
    if not 1 <= len(inputs) <= MAX_BATCH_FILES:
        raise ValueError(f"Choose between 1 and {MAX_BATCH_FILES} CIF files.")
    results = []
    for item in inputs:
        entry = {
            "filename": item.filename,
            "sha256": hashlib.sha256(item.data).hexdigest(),
            "calclens_version": __version__,
            "ase_version": ase.__version__,
            "normal_axis": item.normal_axis,
            "short_distance_threshold_angstrom": item.short_distance,
            "report": None,
            "error": None,
        }
        try:
            report = analyze_cif(item.data, short_distance=item.short_distance,
                                 normal_axis=item.normal_axis)
            entry["report"] = with_provenance(report, item.data, item.filename)
        except (UnsupportedStructure, ValueError) as exc:
            entry["error"] = str(exc)
        results.append(entry)
    return results


_HEADERS_KO = {
    "filename": "파일명", "status": "상태", "formula": "조성", "atom_count": "원자 수",
    "normal_axis": "선택 축", "short_distance_threshold_angstrom": "짧은 거리 기준 / Å",
    "minimum_distance_angstrom": "최소 거리 / Å", "nuclei_thickness_angstrom": "핵 두께 / Å",
    "nuclei_gap_angstrom": "핵 간격 / Å", "warning_count": "경고 수", "error_count": "오류 수",
    "sha256": "SHA-256", "calclens_version": "CalcLens 버전", "ase_version": "ASE 버전",
    "error": "입력 오류",
}


def batch_rows(results: list[dict], language: str = "en") -> list[dict]:
    """Use blanks for failed measurements, never misleading zeroes or passed labels."""
    if language not in ("en", "ko"):
        raise ValueError("Report language must be 'en' or 'ko'.")
    rows = []
    for entry in results:
        report = entry["report"]
        metrics = report["metrics"] if report else {}
        issues = report["issues"] if report else []
        provenance = report.get("provenance", {}) if report else {}
        row = {
            "filename": entry["filename"],
            "status": ("unsupported" if report is None else
                       "review_required" if report["review_required"] else "no_flags"),
            "formula": report["formula"] if report else None,
            "atom_count": report["atom_count"] if report else None,
            "normal_axis": entry["normal_axis"],
            "short_distance_threshold_angstrom": entry["short_distance_threshold_angstrom"],
            "minimum_distance_angstrom": metrics.get("minimum_distance_angstrom"),
            "nuclei_thickness_angstrom": metrics.get("nuclei_thickness_angstrom"),
            "nuclei_gap_angstrom": metrics.get("nuclei_gap_angstrom"),
            "warning_count": sum(i["severity"] == "warning" for i in issues) if report else None,
            "error_count": sum(i["severity"] == "error" for i in issues) if report else None,
            "sha256": entry["sha256"],
            "calclens_version": provenance.get("calclens_version", entry.get("calclens_version")),
            "ase_version": provenance.get("ase_version", entry.get("ase_version")),
            "error": localized_error_message(entry["error"], language) if entry["error"] else "",
        }
        rows.append({_HEADERS_KO[key] if language == "ko" else key: value
                     for key, value in row.items()})
    return rows


def batch_csv(results: list[dict], language: str = "en") -> str:
    rows = batch_rows(results, language)
    output = io.StringIO(newline="")
    headers = list(rows[0]) if rows else [
        _HEADERS_KO[key] if language == "ko" else key for key in _HEADERS_KO
    ]
    writer = csv.DictWriter(output, fieldnames=headers, lineterminator="\n")
    writer.writeheader()
    writer.writerows({key: _spreadsheet_text(value) for key, value in row.items()} for row in rows)
    return output.getvalue()
