"""Portable projects containing original CIF bytes and bounded review state.

Saved analysis results are never trusted. Originals are reanalyzed by the
current engine; review stamps only record which inputs a person reviewed.
"""
from __future__ import annotations

import base64
import binascii
from dataclasses import dataclass, field as dataclass_field, replace
import hashlib
import json
import math
import re
from io import BytesIO
import stat
import struct
from typing import Iterable
import zipfile
import zlib

import ase

from . import __version__

PROJECT_FORMAT = "calclens.project"
SCHEMA_VERSION = 3
ANALYSIS_REVISION = "geometry-v1"
MAX_PROJECT_FILES = 20
MAX_FILE_BYTES = 2 * 1024 * 1024
MAX_ENCODED_FILE_BYTES = 4 * ((MAX_FILE_BYTES + 2) // 3)
MAX_PROJECT_BYTES = 128 * 1024 * 1024
MAX_ARCHIVE_BYTES = MAX_PROJECT_BYTES
MAX_WORKSPACE_BYTES = 96 * 1024 * 1024
MAX_WORKSPACE_NODES = 250_000
MAX_NOTE_LENGTH = 10_000
MAX_JSON_DEPTH = 16
MAX_PAIR_SELECTIONS = 50
MAX_SITE_INDEX = 399
MAX_IMAGE_SHIFT = 9
REVIEW_FOCUSES = ("overview", "minimum", "overlap", "short", "gap", "metadata")
FILTER_MODES = ("all", "needs_review", "unsupported")
PROGRESS_FILTERS = ("all", "unreviewed", "reviewed")
PAIR_MODES = ("minimum_image", "displayed")


class ProjectError(ValueError):
    """The project cannot be saved or safely reopened as a supported project."""


@dataclass(frozen=True)
class ReviewStamp:
    """Exact input and engine identity that a human marked as reviewed."""

    sha256: str
    normal_axis: str
    short_distance: float
    analysis_revision: str | None
    ase_version: str
    calclens_version: str


@dataclass(frozen=True)
class PairSelection:
    """A recomputable selection; calculated distances are intentionally omitted."""

    i: int
    j: int
    first_shift: tuple[int, int, int] = (0, 0, 0)
    second_shift: tuple[int, int, int] = (0, 0, 0)
    mode: str = "minimum_image"


@dataclass(frozen=True)
class ProjectEntry:
    id: str
    filename: str
    data: bytes
    normal_axis: str = "c"
    short_distance: float = 1.0
    note: str = ""
    reviewed: bool = False
    review_stamp: ReviewStamp | None = None
    measurements: tuple[PairSelection, ...] = ()
    preparation: dict | None = None


@dataclass(frozen=True)
class Project:
    entries: list[ProjectEntry]
    selected_id: str | None = None
    review_focus: str = "overview"
    filter_mode: str = "all"
    calclens_version: str = __version__
    ase_version: str = ase.__version__
    progress_filter: str = "all"
    analysis_revision: str | None = ANALYSIS_REVISION
    workspace_state: dict = dataclass_field(default_factory=dict)


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def review_is_current(entry: ProjectEntry) -> bool:
    """Return whether completion matches current bytes, settings and analysis engine."""
    if not isinstance(entry, ProjectEntry) or not isinstance(entry.data, bytes):
        return False
    stamp = entry.review_stamp
    return bool(
        entry.reviewed
        and isinstance(stamp, ReviewStamp)
        and stamp.sha256 == _sha256(entry.data)
        and stamp.normal_axis == entry.normal_axis
        and type(entry.short_distance) in (int, float)
        and 0.1 <= entry.short_distance <= 3.0
        and stamp.short_distance == float(entry.short_distance)
        and stamp.analysis_revision == ANALYSIS_REVISION
        and stamp.ase_version == ase.__version__
    )


def mark_reviewed(entry: ProjectEntry, reviewed: bool = True) -> ProjectEntry:
    """Set completion; clearing it retains the historical stamp for auditability."""
    if not isinstance(entry, ProjectEntry):
        raise ProjectError("Review state requires a ProjectEntry instance.")
    if type(reviewed) is not bool:
        raise ProjectError("Reviewed status must be true or false.")
    if not reviewed:
        return replace(entry, reviewed=False)
    base = replace(entry, reviewed=False)
    _validate_entry(base, 1)
    return replace(base, reviewed=True, review_stamp=ReviewStamp(
        _sha256(base.data), base.normal_axis, float(base.short_distance),
        ANALYSIS_REVISION, ase.__version__, __version__,
    ))


def refresh_review(entry: ProjectEntry) -> ProjectEntry:
    """Clear stale completion while retaining the previous review stamp."""
    return entry if not entry.reviewed or review_is_current(entry) else replace(entry, reviewed=False)


def _text(value: object, field: str, maximum: int, *, empty: bool = False,
          multiline: bool = False) -> str:
    if not isinstance(value, str):
        raise ProjectError(f"{field} must be text.")
    if len(value) > maximum or (not empty and not value.strip()):
        raise ProjectError(f"{field} must contain {'0' if empty else '1'} to {maximum} characters.")
    try:
        value.encode("utf-8")
    except UnicodeEncodeError as exc:
        raise ProjectError(f"{field} must contain valid Unicode text.") from exc
    allowed_controls = "\n\r\t" if multiline else ""
    if any((ord(char) < 32 or 127 <= ord(char) <= 159) and char not in allowed_controls
           for char in value):
        raise ProjectError(f"{field} contains unsupported control characters.")
    return value


def _choice(value: object, field: str, choices: tuple[str, ...]) -> None:
    if not isinstance(value, str) or value not in choices:
        raise ProjectError(f"{field} must be one of: {', '.join(choices)}.")


def _cutoff(value: object, field: str) -> None:
    if (type(value) not in (int, float) or not 0.1 <= value <= 3.0
            or not math.isfinite(value)):
        raise ProjectError(f"{field} must be a finite number from 0.1 to 3.0.")


def _validate_stamp(stamp: object, label: str) -> None:
    if not isinstance(stamp, ReviewStamp):
        raise ProjectError(f"{label} review stamp must be a ReviewStamp instance.")
    if not isinstance(stamp.sha256, str) or re.fullmatch(r"[0-9a-f]{64}", stamp.sha256) is None:
        raise ProjectError(f"{label} review stamp must include a valid SHA-256.")
    _choice(stamp.normal_axis, f"{label} reviewed normal axis", ("a", "b", "c"))
    _cutoff(stamp.short_distance, f"{label} reviewed short-distance cutoff")
    if stamp.analysis_revision is not None:
        _text(stamp.analysis_revision, f"{label} analysis revision", 80)
    _text(stamp.ase_version, f"{label} reviewed ASE version", 80)
    _text(stamp.calclens_version, f"{label} reviewed CalcLens version", 80)


def _validate_shift(value: object, field: str) -> None:
    if (not isinstance(value, tuple) or len(value) != 3
            or any(type(item) is not int or abs(item) > MAX_IMAGE_SHIFT for item in value)):
        raise ProjectError(
            f"{field} must be three integer image shifts from {-MAX_IMAGE_SHIFT} to {MAX_IMAGE_SHIFT}."
        )


def _validate_pair(selection: object, label: str) -> None:
    if not isinstance(selection, PairSelection):
        raise ProjectError(f"{label} must be a PairSelection instance.")
    for field, value in (("first atom index", selection.i), ("second atom index", selection.j)):
        if type(value) is not int or not 0 <= value <= MAX_SITE_INDEX:
            raise ProjectError(f"{label} {field} must be from 0 to {MAX_SITE_INDEX}.")
    if selection.i == selection.j:
        raise ProjectError(f"{label} must select two distinct atom indices.")
    _validate_shift(selection.first_shift, f"{label} first shift")
    _validate_shift(selection.second_shift, f"{label} second shift")
    _choice(selection.mode, f"{label} mode", PAIR_MODES)


def validate_workspace_state(value: object) -> int:
    """Bound portable client state; clients still revalidate scientific data.

    The extension is JSON only. It cannot name files for the backend to open or
    contain executable objects. Raw auxiliary text is retained without parsing
    it as a trusted calculation, measurement, or electronic structure.
    """
    if not isinstance(value, dict):
        raise ProjectError("Workspace state must be a JSON object.")
    pending = [(value, 2)]  # Include the enclosing project object in the depth.
    visited = 0
    while pending:
        item, depth = pending.pop()
        visited += 1
        if visited + len(pending) > MAX_WORKSPACE_NODES:
            raise ProjectError("Workspace state contains too many JSON values.")
        if depth > MAX_JSON_DEPTH:
            raise ProjectError("Workspace state nesting is too deep.")
        if isinstance(item, dict):
            if visited + len(pending) + len(item) * 2 > MAX_WORKSPACE_NODES:
                raise ProjectError("Workspace state contains too many JSON values.")
            for key, child in item.items():
                _text(key, "Workspace field name", 1024, empty=True)
                pending.append((child, depth + 1))
                visited += 1
        elif isinstance(item, list):
            if visited + len(pending) + len(item) > MAX_WORKSPACE_NODES:
                raise ProjectError("Workspace state contains too many JSON values.")
            pending.extend((child, depth + 1) for child in item)
        elif isinstance(item, str):
            try:
                if len(item.encode("utf-8")) > MAX_WORKSPACE_BYTES:
                    raise ProjectError("Workspace text exceeds the portable state size limit.")
            except UnicodeEncodeError as exc:
                raise ProjectError("Workspace state must contain valid Unicode text.") from exc
        elif item is None or type(item) is bool:
            pass
        elif type(item) is int:
            if abs(item) > 2**53 - 1:
                raise ProjectError("Workspace integers must be exactly representable JSON numbers.")
        elif type(item) is float:
            if not math.isfinite(item):
                raise ProjectError("Workspace numbers must be finite.")
        else:
            raise ProjectError("Workspace state must contain JSON data only.")
    encoded = json.dumps(value, ensure_ascii=False, allow_nan=False, separators=(",", ":")).encode()
    if len(encoded) > MAX_WORKSPACE_BYTES:
        raise ProjectError(f"Workspace state exceeds the {MAX_WORKSPACE_BYTES}-byte limit.")
    return len(encoded)


def _validate_preparation(value: object, data: bytes, label: str) -> None:
    record = _mapping(value, f"{label} preparation", {
        "schema_version", "method", "source", "source_sha256", "prepared_sha256",
        "source_site_count", "prepared_site_count", "source_spacegroup", "source_cell",
        "prepared_cell", "occupancy_policy", "symmetry_operation_count",
        "symmetry_tolerance_fractional", "symmetry_tolerance_angstrom", "ase_version",
        "normal_axis", "warnings", "changes",
    })
    if type(record["schema_version"]) is not int or record["schema_version"] != 1:
        raise ProjectError(f"{label} preparation schema is unsupported.")
    if record["method"] != "symmetry_expansion_to_p1":
        raise ProjectError(f"{label} preparation method is unsupported.")
    source = _mapping(record["source"], f"{label} original preparation source", {
        "filename", "cif_base64", "sha256",
    })
    _text(source["filename"], f"{label} preparation source filename", 255)
    if source["filename"] in (".", "..") or any(char in source["filename"] for char in "/\\"):
        raise ProjectError(f"{label} preparation source must be a filename without a directory path.")
    _, digest = _load_payload(source, f"{label} preparation source")
    if record["source_sha256"] != digest or record["prepared_sha256"] != _sha256(data):
        raise ProjectError(f"{label} preparation hashes do not match original and prepared CIF content.")
    for key in ("source_site_count", "prepared_site_count", "symmetry_operation_count"):
        maximum = 192 if key == "symmetry_operation_count" else MAX_SITE_INDEX + 1
        if type(record[key]) is not int or not 1 <= record[key] <= maximum:
            raise ProjectError(f"{label} preparation {key} is outside the supported limit.")
    for key in ("source_cell", "prepared_cell"):
        cell = record[key]
        if not isinstance(cell, list) or len(cell) != 6:
            raise ProjectError(f"{label} preparation cells must contain six parameters.")
        if any(type(item) not in (int, float) or not math.isfinite(item) for item in cell):
            raise ProjectError(f"{label} preparation cell parameters must be finite numbers.")
        if any(not 0.001 <= item <= 10000 for item in cell[:3]) or any(
                not 0 < item < 180 for item in cell[3:]):
            raise ProjectError(f"{label} preparation cell parameters are unsupported.")
    if record["source_cell"] != record["prepared_cell"]:
        raise ProjectError(f"{label} P1 preparation must retain its original cell.")
    group = _mapping(record["source_spacegroup"], f"{label} original space group", {
        "number", "symbol",
    })
    if type(group["number"]) is not int or not 1 <= group["number"] <= 230:
        raise ProjectError(f"{label} original space-group number is invalid.")
    _text(group["symbol"], f"{label} original space-group symbol", 80)
    _choice(record["normal_axis"], f"{label} preparation normal axis", ("a", "b", "c"))
    _text(record["ase_version"], f"{label} preparation ASE version", 80)
    _choice(record["occupancy_policy"], f"{label} preparation occupancy policy", (
        "explicit source occupancy 1.0 retained",
        "omitted in source; coreCIF default 1.0 made explicit",
    ))
    for key in ("symmetry_tolerance_fractional", "symmetry_tolerance_angstrom"):
        number = record[key]
        if type(number) not in (int, float) or not math.isfinite(number) or not 0 < number <= 0.001:
            raise ProjectError(f"{label} preparation symmetry tolerance is unsupported.")
    for key in ("warnings", "changes"):
        if not isinstance(record[key], list) or len(record[key]) > 20:
            raise ProjectError(f"{label} preparation {key} must be a bounded list.")
        for text in record[key]:
            _text(text, f"{label} preparation {key}", 1000)


def _validate_entry(entry: object, index: int) -> None:
    label = f"Entry {index}"
    if not isinstance(entry, ProjectEntry):
        raise ProjectError(f"{label} must be a ProjectEntry instance.")
    _text(entry.id, f"{label} ID", 128)
    _text(entry.filename, f"{label} filename", 255)
    if entry.filename in (".", "..") or "/" in entry.filename or "\\" in entry.filename:
        raise ProjectError(f"{label} filename must be a filename without a directory path.")
    if not isinstance(entry.data, bytes) or not 1 <= len(entry.data) <= MAX_FILE_BYTES:
        raise ProjectError(f"{label} must embed between 1 and {MAX_FILE_BYTES} original CIF bytes.")
    _choice(entry.normal_axis, f"{label} normal axis", ("a", "b", "c"))
    _cutoff(entry.short_distance, f"{label} short-distance cutoff")
    _text(entry.note, f"{label} note", MAX_NOTE_LENGTH, empty=True, multiline=True)
    if type(entry.reviewed) is not bool:
        raise ProjectError(f"{label} reviewed status must be true or false.")
    if entry.review_stamp is not None:
        _validate_stamp(entry.review_stamp, label)
    if entry.reviewed and not review_is_current(entry):
        raise ProjectError(f"{label} reviewed status is stale or missing its current review stamp.")
    if not isinstance(entry.measurements, tuple) or len(entry.measurements) > MAX_PAIR_SELECTIONS:
        raise ProjectError(f"{label} must contain at most {MAX_PAIR_SELECTIONS} pair selections.")
    for pair_index, pair in enumerate(entry.measurements, 1):
        _validate_pair(pair, f"{label} pair selection {pair_index}")
    if entry.preparation is not None:
        _validate_preparation(entry.preparation, entry.data, label)


def _validate_project(project: Project) -> None:
    if not isinstance(project, Project):
        raise ProjectError("Save a Project instance.")
    if not isinstance(project.entries, list) or not 1 <= len(project.entries) <= MAX_PROJECT_FILES:
        raise ProjectError(f"A project must contain between 1 and {MAX_PROJECT_FILES} CIF files.")
    seen = set()
    for index, entry in enumerate(project.entries, 1):
        _validate_entry(entry, index)
        if entry.id in seen:
            raise ProjectError("Project entry IDs must be unique, including for duplicate filenames.")
        seen.add(entry.id)
    if project.selected_id is not None:
        _text(project.selected_id, "Selected entry ID", 128)
        if project.selected_id not in seen:
            raise ProjectError("Selected entry ID does not identify an embedded CIF file.")
    _choice(project.review_focus, "Review focus", REVIEW_FOCUSES)
    _choice(project.filter_mode, "Review filter", FILTER_MODES)
    _choice(project.progress_filter, "Progress filter", PROGRESS_FILTERS)
    _text(project.calclens_version, "CalcLens version", 80)
    _text(project.ase_version, "ASE version", 80)
    if project.analysis_revision is not None:
        _text(project.analysis_revision, "Analysis revision", 80)
    validate_workspace_state(project.workspace_state)


def _stamp_document(stamp: ReviewStamp | None) -> dict | None:
    if stamp is None:
        return None
    return {
        "sha256": stamp.sha256, "normal_axis": stamp.normal_axis,
        "short_distance": float(stamp.short_distance),
        "analysis_revision": stamp.analysis_revision,
        "ase_version": stamp.ase_version, "calclens_version": stamp.calclens_version,
    }


def _pair_document(pair: PairSelection) -> dict:
    return {
        "i": pair.i, "j": pair.j, "first_shift": list(pair.first_shift),
        "second_shift": list(pair.second_shift), "mode": pair.mode,
    }


def dumps_project(project: Project) -> bytes:
    """Validate and serialize a self-contained schema-3 project as UTF-8 JSON."""
    _validate_project(project)
    document = {
        "format": PROJECT_FORMAT,
        "schema_version": SCHEMA_VERSION,
        "tools": {
            "calclens_version": project.calclens_version,
            "ase_version": project.ase_version,
            "analysis_revision": project.analysis_revision,
        },
        "state": {
            "selected_id": project.selected_id, "review_focus": project.review_focus,
            "filter_mode": project.filter_mode, "progress_filter": project.progress_filter,
        },
        "workspace_state": project.workspace_state,
        "entries": [{
            "id": entry.id, "filename": entry.filename,
            "cif_base64": base64.b64encode(entry.data).decode("ascii"),
            "sha256": _sha256(entry.data), "normal_axis": entry.normal_axis,
            "short_distance": float(entry.short_distance), "note": entry.note,
            "reviewed": entry.reviewed, "review_stamp": _stamp_document(entry.review_stamp),
            "measurements": [_pair_document(pair) for pair in entry.measurements],
            "preparation": entry.preparation,
        } for entry in project.entries],
    }
    data = json.dumps(document, ensure_ascii=False, allow_nan=False,
                      sort_keys=True, separators=(",", ":")).encode("utf-8")
    if len(data) > MAX_PROJECT_BYTES:
        raise ProjectError(f"Project JSON exceeds the {MAX_PROJECT_BYTES}-byte limit.")
    return data


def _mapping(value: object, field: str, keys: set[str]) -> dict:
    if not isinstance(value, dict):
        raise ProjectError(f"{field} must be a JSON object.")
    missing = keys - value.keys()
    if missing:
        raise ProjectError(f"{field} is missing required fields: {', '.join(sorted(missing))}.")
    if value.keys() - keys:
        raise ProjectError(f"{field} contains unexpected fields.")
    return value


def _unique_object(pairs: list[tuple[str, object]]) -> dict:
    result = {}
    for key, value in pairs:
        if key in result:
            raise ProjectError("Project JSON contains duplicate object fields.")
        result[key] = value
    return result


def _reject_constant(value: str) -> None:
    raise ProjectError("Project JSON cannot contain NaN or Infinity.")


def _check_json_depth(data: bytes) -> None:
    """Bound container nesting without counting braces inside embedded strings."""
    in_string = False
    escaped_at = -1
    depth = 0
    for match in re.finditer(rb'["\\{}\[\]]', data):
        token = match.group()
        if in_string:
            if match.start() == escaped_at:
                continue
            if token == b"\\":
                escaped_at = match.start() + 1
            elif token == b'"':
                in_string = False
        elif token == b'"':
            in_string = True
        elif token in (b"{", b"["):
            depth += 1
            if depth > MAX_JSON_DEPTH:
                raise ProjectError("Project JSON nesting is too deep.")
        elif token in (b"}", b"]"):
            depth -= 1


def _load_payload(entry: dict, label: str) -> tuple[bytes, str]:
    encoded = entry["cif_base64"]
    if not isinstance(encoded, str) or not encoded:
        raise ProjectError(f"{label} is missing its embedded CIF content (cif_base64).")
    if len(encoded) > MAX_ENCODED_FILE_BYTES:
        raise ProjectError(f"{label} embedded CIF content exceeds the {MAX_FILE_BYTES}-byte limit.")
    digest = entry["sha256"]
    if not isinstance(digest, str) or re.fullmatch(r"[0-9a-f]{64}", digest) is None:
        raise ProjectError(f"{label} must include a valid SHA-256 for its embedded CIF content.")
    try:
        original = base64.b64decode(encoded, validate=True)
    except (binascii.Error, ValueError) as exc:
        raise ProjectError(f"{label} embedded CIF content is not valid base64.") from exc
    if not original or len(original) > MAX_FILE_BYTES:
        raise ProjectError(f"{label} must embed between 1 and {MAX_FILE_BYTES} original CIF bytes.")
    if _sha256(original) != digest:
        raise ProjectError(f"{label} embedded CIF content does not match its SHA-256; it may be damaged.")
    return original, digest


def _load_stamp(value: object, label: str) -> ReviewStamp | None:
    if value is None:
        return None
    stamp = _mapping(value, f"{label} review stamp", {
        "sha256", "normal_axis", "short_distance", "analysis_revision",
        "ase_version", "calclens_version",
    })
    result = ReviewStamp(
        stamp["sha256"], stamp["normal_axis"], stamp["short_distance"],
        stamp["analysis_revision"], stamp["ase_version"], stamp["calclens_version"],
    )
    _validate_stamp(result, label)
    return result


def _load_pair(value: object, label: str) -> PairSelection:
    pair = _mapping(value, label, {"i", "j", "first_shift", "second_shift", "mode"})
    if not isinstance(pair["first_shift"], list) or not isinstance(pair["second_shift"], list):
        raise ProjectError(f"{label} image shifts must be JSON arrays.")
    result = PairSelection(
        pair["i"], pair["j"], tuple(pair["first_shift"]),
        tuple(pair["second_shift"]), pair["mode"],
    )
    _validate_pair(result, label)
    return result


def _load_entry_v1(value: object, index: int, tools: dict) -> ProjectEntry:
    label = f"Entry {index}"
    entry = _mapping(value, label, {
        "id", "filename", "cif_base64", "sha256", "normal_axis", "short_distance", "note", "reviewed",
    })
    original, digest = _load_payload(entry, label)
    if type(entry["reviewed"]) is not bool:
        raise ProjectError(f"{label} reviewed status must be true or false.")
    stamp = None
    if entry["reviewed"]:
        stamp = ReviewStamp(
            digest, entry["normal_axis"], entry["short_distance"], None,
            tools["ase_version"], tools["calclens_version"],
        )
    return ProjectEntry(
        entry["id"], entry["filename"], original, entry["normal_axis"],
        entry["short_distance"], entry["note"], False, stamp,
    )


def _load_entry_v2(value: object, index: int, *, version: int = 2) -> ProjectEntry:
    label = f"Entry {index}"
    fields = {
        "id", "filename", "cif_base64", "sha256", "normal_axis", "short_distance", "note",
        "reviewed", "review_stamp", "measurements",
    }
    if version == 3:
        fields.add("preparation")
    entry = _mapping(value, label, fields)
    original, _ = _load_payload(entry, label)
    measurements = entry["measurements"]
    if not isinstance(measurements, list) or len(measurements) > MAX_PAIR_SELECTIONS:
        raise ProjectError(f"{label} must contain at most {MAX_PAIR_SELECTIONS} pair selections.")
    candidate = ProjectEntry(
        entry["id"], entry["filename"], original, entry["normal_axis"],
        entry["short_distance"], entry["note"], entry["reviewed"],
        _load_stamp(entry["review_stamp"], label),
        tuple(_load_pair(item, f"{label} pair selection {pair_index}")
              for pair_index, item in enumerate(measurements, 1)),
        entry["preparation"] if version == 3 else None,
    )
    if type(candidate.reviewed) is not bool:
        raise ProjectError(f"{label} reviewed status must be true or false.")
    return refresh_review(candidate)


def _replay_preparation(entry: ProjectEntry) -> None:
    """Verify saved transformation evidence from originals, never trust a claim."""
    if entry.preparation is None:
        return
    from .preparation import PreparationError, prepare_p1

    record = entry.preparation
    source, _ = _load_payload(record["source"], "Original preparation source")
    try:
        prepared = prepare_p1(source, record["normal_axis"])
    except PreparationError as exc:
        raise ProjectError("Saved preparation original cannot be safely reproduced.") from exc
    if prepared.cif != entry.data:
        raise ProjectError("Saved prepared CIF does not reproduce from its embedded original source.")
    for key, expected in prepared.metadata().items():
        # Historical tool identity remains evidence, while scientific content
        # and method-v1 output are checked by the current preparation engine.
        if key == "ase_version":
            continue
        actual = record[key]
        if type(expected) is float:
            agrees = math.isclose(actual, expected, rel_tol=1e-10, abs_tol=1e-15)
        else:
            agrees = actual == expected
        if not agrees:
            raise ProjectError(f"Saved preparation {key} disagrees with its embedded original source.")


def loads_project(data: bytes) -> Project:
    """Reopen bounded schema-1/2/3 JSON or a sole-project.json ZIP archive."""
    if not isinstance(data, bytes):
        raise ProjectError("Project input must be UTF-8 JSON bytes or a CalcLens ZIP archive.")
    if data.startswith(b"PK"):
        return loads_project_archive(data)
    if len(data) > MAX_PROJECT_BYTES:
        raise ProjectError(f"Project JSON exceeds the {MAX_PROJECT_BYTES}-byte limit.")
    _check_json_depth(data)
    try:
        document = json.loads(data.decode("utf-8"), object_pairs_hook=_unique_object,
                              parse_constant=_reject_constant)
    except RecursionError as exc:
        raise ProjectError("Project JSON nesting is too deep.") from exc
    except (UnicodeDecodeError, ValueError) as exc:
        if isinstance(exc, ProjectError):
            raise
        raise ProjectError("Project must contain valid UTF-8 JSON.") from exc
    if not isinstance(document, dict):
        raise ProjectError("Project must be a JSON object.")
    if "schema_version" in document and (
        type(document["schema_version"]) is not int or document["schema_version"] not in (1, 2, 3)
    ):
        raise ProjectError("Unsupported project schema version; this CalcLens supports versions 1, 2 and 3.")
    fields = {"format", "schema_version", "tools", "state", "entries"}
    if document.get("schema_version") == 3:
        fields.add("workspace_state")
    document = _mapping(document, "Project", fields)
    if document["format"] != PROJECT_FORMAT:
        raise ProjectError("This is not a CalcLens project file.")
    version = document["schema_version"]
    if type(version) is not int or version not in (1, 2, SCHEMA_VERSION):
        raise ProjectError("Unsupported project schema version; this CalcLens supports versions 1, 2 and 3.")
    values = document["entries"]
    if not isinstance(values, list) or not 1 <= len(values) <= MAX_PROJECT_FILES:
        raise ProjectError(f"A project must contain between 1 and {MAX_PROJECT_FILES} CIF files.")
    if version == 1:
        tools = _mapping(document["tools"], "Project tools", {"calclens_version", "ase_version"})
        state = _mapping(document["state"], "Project state", {"selected_id", "review_focus", "filter_mode"})
        project = Project(
            [_load_entry_v1(value, index, tools) for index, value in enumerate(values, 1)],
            state["selected_id"], state["review_focus"], state["filter_mode"],
            tools["calclens_version"], tools["ase_version"], "all", None,
        )
    else:
        tools = _mapping(document["tools"], "Project tools", {
            "calclens_version", "ase_version", "analysis_revision",
        })
        state = _mapping(document["state"], "Project state", {
            "selected_id", "review_focus", "filter_mode", "progress_filter",
        })
        project = Project(
            [_load_entry_v2(value, index, version=version) for index, value in enumerate(values, 1)],
            state["selected_id"], state["review_focus"], state["filter_mode"],
            tools["calclens_version"], tools["ase_version"], state["progress_filter"],
            tools["analysis_revision"],
            document["workspace_state"] if version == 3 else {},
        )
    _validate_project(project)
    for entry in project.entries:
        _replay_preparation(entry)
    return project


def dumps_project_archive(project: Project) -> bytes:
    """Return a bounded ZIP with one self-contained project.json member."""
    payload = dumps_project(project)
    buffer = BytesIO()
    with zipfile.ZipFile(buffer, "w", compression=zipfile.ZIP_DEFLATED,
                         compresslevel=6, allowZip64=False) as archive:
        member = zipfile.ZipInfo("project.json", date_time=(1980, 1, 1, 0, 0, 0))
        member.compress_type = zipfile.ZIP_DEFLATED
        member.external_attr = (stat.S_IFREG | 0o600) << 16
        archive.writestr(member, payload, compresslevel=6)
    data = buffer.getvalue()
    if len(data) > MAX_ARCHIVE_BYTES:
        raise ProjectError(f"Project ZIP exceeds the {MAX_ARCHIVE_BYTES}-byte limit.")
    return data


def _archive_directory(data: bytes) -> None:
    """Reject multi-entry/ZIP64 archives before ZipFile allocates their directory."""
    # CalcLens archives need no comments, spanning, prefix, or ZIP64 extensions.
    if len(data) < 22 or data[:4] != b"PK\x03\x04" or data[-22:-18] != b"PK\x05\x06":
        raise ProjectError("Project ZIP must be an ordinary, complete single-file archive.")
    _, disk, start_disk, on_disk, total, size, offset, comment = struct.unpack("<4s4H2LH", data[-22:])
    if (disk or start_disk or on_disk != 1 or total != 1 or comment
            or size > 128 * 1024 or offset + size != len(data) - 22):
        raise ProjectError("Project ZIP must contain exactly one project.json entry without ZIP64 or comments.")


def loads_project_archive(data: bytes) -> Project:
    """Read in memory with byte caps; no member is ever extracted to disk."""
    if not isinstance(data, bytes):
        raise ProjectError("Project ZIP input must be bytes.")
    if len(data) > MAX_ARCHIVE_BYTES:
        raise ProjectError(f"Project ZIP exceeds the {MAX_ARCHIVE_BYTES}-byte limit.")
    _archive_directory(data)
    try:
        with zipfile.ZipFile(BytesIO(data), "r", allowZip64=False) as archive:
            members = archive.infolist()
            if len(members) != 1:
                raise ProjectError("Project ZIP must contain exactly one project.json entry.")
            member = members[0]
            if (member.filename != "project.json" or member.orig_filename != "project.json"
                    or member.is_dir()
                    or stat.S_IFMT(member.external_attr >> 16) not in (0, stat.S_IFREG)
                    or member.flag_bits & (1 | 0x40)
                    or member.extract_version > 20
                    or member.compress_type not in (zipfile.ZIP_STORED, zipfile.ZIP_DEFLATED)):
                raise ProjectError("Project ZIP permits only an unencrypted regular project.json entry.")
            if not 1 <= member.file_size <= MAX_PROJECT_BYTES:
                raise ProjectError(f"Expanded project JSON exceeds the {MAX_PROJECT_BYTES}-byte limit.")
            if member.compress_size > MAX_ARCHIVE_BYTES:
                raise ProjectError("Compressed project member exceeds the archive size limit.")
            payload = bytearray()
            with archive.open(member) as source:
                while chunk := source.read(min(1024 * 1024, MAX_PROJECT_BYTES + 1 - len(payload))):
                    payload.extend(chunk)
                    if len(payload) > MAX_PROJECT_BYTES:
                        raise ProjectError("Expanded project JSON exceeds its size limit.")
            if len(payload) != member.file_size:
                raise ProjectError("Expanded project JSON length does not match its archive metadata.")
    except ProjectError:
        raise
    except (zipfile.BadZipFile, zipfile.LargeZipFile, RuntimeError, NotImplementedError,
            OSError, EOFError, zlib.error, ValueError) as exc:
        raise ProjectError("Project ZIP is corrupt or unsupported.") from exc
    # Do not recursively accept nested project archives.
    if payload.startswith(b"PK"):
        raise ProjectError("Nested project ZIP archives are unsupported.")
    return loads_project(bytes(payload))


def add_entries(project: Project, new_entries: Iterable[ProjectEntry]) -> Project:
    """Return a fully validated project with entries appended atomically."""
    result = replace(project, entries=[*project.entries, *list(new_entries)])
    _validate_project(result)
    return result


def replace_entry(project: Project, entry_id: str, filename: str, data: bytes) -> Project:
    """Replace one original while preserving identity, note, settings and review history."""
    try:
        index = next(i for i, entry in enumerate(project.entries) if entry.id == entry_id)
    except StopIteration as exc:
        raise ProjectError("Replacement entry ID does not identify a project file.") from exc
    current = project.entries[index]
    changed = data != current.data
    replacement = replace(
        current, filename=filename, data=data,
        reviewed=False if changed else current.reviewed,
        measurements=() if changed else current.measurements,
        preparation=None if changed else current.preparation,
    )
    entries = list(project.entries)
    entries[index] = replacement
    result = replace(project, entries=entries)
    _validate_project(result)
    return result


def remove_entry(project: Project, entry_id: str) -> Project:
    """Remove one entry and select the nearest surviving row when necessary."""
    if len(project.entries) == 1:
        raise ProjectError("A project must keep at least one CIF file.")
    try:
        index = next(i for i, entry in enumerate(project.entries) if entry.id == entry_id)
    except StopIteration as exc:
        raise ProjectError("Removal entry ID does not identify a project file.") from exc
    entries = [entry for entry in project.entries if entry.id != entry_id]
    selected_id = project.selected_id
    if selected_id == entry_id:
        selected_id = entries[min(index, len(entries) - 1)].id
    result = replace(project, entries=entries, selected_id=selected_id)
    _validate_project(result)
    return result
