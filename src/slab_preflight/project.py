"""Portable projects containing original CIF bytes and bounded review state.

Saved analysis results are never trusted. Originals are reanalyzed by the
current engine; review stamps only record which inputs a person reviewed.
"""
from __future__ import annotations

import base64
import binascii
from dataclasses import dataclass, replace
import hashlib
import json
import math
import re
from typing import Iterable

import ase

from . import __version__

PROJECT_FORMAT = "calclens.project"
SCHEMA_VERSION = 2
ANALYSIS_REVISION = "geometry-v1"
MAX_PROJECT_FILES = 20
MAX_FILE_BYTES = 2 * 1024 * 1024
MAX_ENCODED_FILE_BYTES = 4 * ((MAX_FILE_BYTES + 2) // 3)
MAX_PROJECT_BYTES = MAX_PROJECT_FILES * MAX_ENCODED_FILE_BYTES + 1024 * 1024
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
    """Validate and serialize a self-contained schema-2 project as UTF-8 JSON."""
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
        "entries": [{
            "id": entry.id, "filename": entry.filename,
            "cif_base64": base64.b64encode(entry.data).decode("ascii"),
            "sha256": _sha256(entry.data), "normal_axis": entry.normal_axis,
            "short_distance": float(entry.short_distance), "note": entry.note,
            "reviewed": entry.reviewed, "review_stamp": _stamp_document(entry.review_stamp),
            "measurements": [_pair_document(pair) for pair in entry.measurements],
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


def _load_entry_v2(value: object, index: int) -> ProjectEntry:
    label = f"Entry {index}"
    entry = _mapping(value, label, {
        "id", "filename", "cif_base64", "sha256", "normal_axis", "short_distance", "note",
        "reviewed", "review_stamp", "measurements",
    })
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
    )
    if type(candidate.reviewed) is not bool:
        raise ProjectError(f"{label} reviewed status must be true or false.")
    return refresh_review(candidate)


def loads_project(data: bytes) -> Project:
    """Reopen bounded schema-1/2 originals without trusting analysis output."""
    if not isinstance(data, bytes):
        raise ProjectError("Project input must be UTF-8 JSON bytes.")
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
    document = _mapping(document, "Project", {"format", "schema_version", "tools", "state", "entries"})
    if document["format"] != PROJECT_FORMAT:
        raise ProjectError("This is not a CalcLens project file.")
    version = document["schema_version"]
    if type(version) is not int or version not in (1, SCHEMA_VERSION):
        raise ProjectError("Unsupported project schema version; this CalcLens supports versions 1 and 2.")
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
            [_load_entry_v2(value, index) for index, value in enumerate(values, 1)],
            state["selected_id"], state["review_focus"], state["filter_mode"],
            tools["calclens_version"], tools["ase_version"], state["progress_filter"],
            tools["analysis_revision"],
        )
    _validate_project(project)
    return project


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
