"""Portable original-output records and derived native comparison choices."""
from __future__ import annotations

import base64
from hashlib import sha256

from .core import MAX_ATOMS
from .research_logs import MAX_LOG_BYTES, parse_log
from .result_geometry import geometry_report

MAX_SAVED_OUTPUTS = 8
MAX_OUTPUT_BUNDLE_BYTES = 64 * 1024 * 1024


def output_record(data, filename):
    if not isinstance(data, bytes) or len(data) > MAX_LOG_BYTES:
        raise ValueError("Calculation output exceeds 32 MiB.")
    return {"filename": filename, "sha256": sha256(data).hexdigest(),
            "data": base64.b64encode(data).decode("ascii")}


def read_output_record(record):
    if (not isinstance(record, dict) or not isinstance(record.get("filename"), str)
            or not 0 < len(record["filename"]) <= 500 or not isinstance(record.get("data"), str)
            or len(record["data"]) > 4 * ((MAX_LOG_BYTES + 2) // 3)):
        raise ValueError("Invalid saved calculation output.")
    try:
        raw = base64.b64decode(record["data"], validate=True)
    except (ValueError, UnicodeError) as exc:
        raise ValueError("Invalid calculation output encoding.") from exc
    if len(raw) > MAX_LOG_BYTES or sha256(raw).hexdigest() != record.get("sha256"):
        raise ValueError("Saved calculation output checksum/size differs from the original.")
    return parse_log(raw, source_name=record["filename"])


def saved_output_records(native):
    """Include the v0.9 single log without duplicating it in the v0.10 library."""
    records = native.get("logs", [])
    if not isinstance(records, list) or len(records) > MAX_SAVED_OUTPUTS:
        raise ValueError("At most eight saved calculation outputs are supported.")
    records = list(records)
    latest = native.get("log")
    if latest is not None:
        if not isinstance(latest, dict):
            raise ValueError("Invalid latest calculation output record.")
        if not any(isinstance(r, dict) and r.get("sha256") == latest.get("sha256") for r in records):
            records.append(latest)
    if len(records) > MAX_SAVED_OUTPUTS:
        raise ValueError("At most eight saved calculation outputs are supported.")
    seen, total = set(), 0
    for record in records:
        if not isinstance(record, dict) or not isinstance(record.get("data"), str):
            raise ValueError("Invalid calculation output library record.")
        digest = record.get("sha256")
        if not isinstance(digest, str) or digest in seen:
            raise ValueError("Duplicate or invalid calculation output identity.")
        seen.add(digest)
        total += len(record["data"])
    if total > 4 * ((MAX_OUTPUT_BUNDLE_BYTES + 2) // 3):
        raise ValueError("Saved calculation output library exceeds 64 MiB.")
    return records


def result_entries(report):
    """Each Link1/concatenated job is independently selectable and source-bound."""
    result = []
    for step in report["steps"]:
        geometry = step.get("final_geometry")
        if not geometry:
            continue
        info = report["provenance"]
        program = step.get("program", report["program"])
        oversized = len(geometry["elements"]) > MAX_ATOMS
        render_error = (f"{len(geometry['elements'])} source atoms exceed the native {MAX_ATOMS}-atom display/comparison limit. "
                        "The complete original output and parsed coordinates are retained; no atoms are omitted.") if oversized else None
        result.append({
            "id": f"output:{info['sha256']}:{step['index']}",
            "sha256": info["sha256"],
            "filename": f"{info['name']} · {program['name']} {program.get('version') or ''} · job {step['index']} [{step['status']}]",
            "normal_axis": None, "short_distance": None,
            "analysis": {"report": None if oversized else geometry_report(geometry),
                         "error": render_error,
                         "error_ko": (f"원본 원자 {len(geometry['elements'])}개가 표시·비교 한도 {MAX_ATOMS}개를 초과합니다. "
                                      "원본 출력과 좌표는 보관하며 원자를 생략하지 않습니다.") if oversized else None},
            "output": {"program": program, "step": step,
                       "provenance": info, "kind": report["kind"]},
        })
    return result
