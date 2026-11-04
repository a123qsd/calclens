"""Portable review projects containing original CIF bytes and review state.

Projects never contain trusted analysis results or references to local files.
Callers reanalyze the embedded originals with their current geometry engine.
SHA-256 detects damaged content; it does not authenticate a project's author.
"""
from __future__ import annotations

import base64
import binascii
from dataclasses import dataclass
import hashlib
import json
import math
import re

import ase

from . import __version__

PROJECT_FORMAT = "calclens.project"
SCHEMA_VERSION = 1
MAX_PROJECT_FILES = 20
MAX_FILE_BYTES = 2 * 1024 * 1024
MAX_ENCODED_FILE_BYTES = 4 * ((MAX_FILE_BYTES + 2) // 3)
MAX_PROJECT_BYTES = MAX_PROJECT_FILES * MAX_ENCODED_FILE_BYTES + 1024 * 1024
MAX_NOTE_LENGTH = 10_000
MAX_JSON_DEPTH = 16
REVIEW_FOCUSES = ("overview", "minimum", "overlap", "short", "gap", "metadata")
FILTER_MODES = ("all", "needs_review", "unsupported")


class ProjectError(ValueError):
    """The project cannot be saved or safely reopened as a supported project."""


@dataclass(frozen=True)
class ProjectEntry:
    id: str
    filename: str
    data: bytes
    normal_axis: str = "c"
    short_distance: float = 1.0
    note: str = ""
    reviewed: bool = False


@dataclass(frozen=True)
class Project:
    entries: list[ProjectEntry]
    selected_id: str | None = None
    review_focus: str = "overview"
    filter_mode: str = "all"
    calclens_version: str = __version__
    ase_version: str = ase.__version__


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


def _validate_project(project: Project) -> None:
    if not isinstance(project, Project):
        raise ProjectError("Save a Project instance.")
    if not isinstance(project.entries, list) or not 1 <= len(project.entries) <= MAX_PROJECT_FILES:
        raise ProjectError(f"A project must contain between 1 and {MAX_PROJECT_FILES} CIF files.")
    seen = set()
    for index, entry in enumerate(project.entries, 1):
        label = f"Entry {index}"
        if not isinstance(entry, ProjectEntry):
            raise ProjectError(f"{label} must be a ProjectEntry instance.")
        _text(entry.id, f"{label} ID", 128)
        if entry.id in seen:
            raise ProjectError("Project entry IDs must be unique, including for duplicate filenames.")
        seen.add(entry.id)
        _text(entry.filename, f"{label} filename", 255)
        if entry.filename in (".", "..") or "/" in entry.filename or "\\" in entry.filename:
            raise ProjectError(f"{label} filename must be a filename without a directory path.")
        if not isinstance(entry.data, bytes) or not 1 <= len(entry.data) <= MAX_FILE_BYTES:
            raise ProjectError(f"{label} must embed between 1 and {MAX_FILE_BYTES} original CIF bytes.")
        _choice(entry.normal_axis, f"{label} normal axis", ("a", "b", "c"))
        if (type(entry.short_distance) not in (int, float)
                or not 0.1 <= entry.short_distance <= 3.0
                or not math.isfinite(entry.short_distance)):
            raise ProjectError(f"{label} short-distance cutoff must be a finite number from 0.1 to 3.0.")
        _text(entry.note, f"{label} note", MAX_NOTE_LENGTH, empty=True, multiline=True)
        if type(entry.reviewed) is not bool:
            raise ProjectError(f"{label} reviewed status must be true or false.")
    if project.selected_id is not None:
        _text(project.selected_id, "Selected entry ID", 128)
        if project.selected_id not in seen:
            raise ProjectError("Selected entry ID does not identify an embedded CIF file.")
    _choice(project.review_focus, "Review focus", REVIEW_FOCUSES)
    _choice(project.filter_mode, "Review filter", FILTER_MODES)
    _text(project.calclens_version, "CalcLens version", 80)
    _text(project.ase_version, "ASE version", 80)


def dumps_project(project: Project) -> bytes:
    """Validate and serialize a self-contained schema-1 project as UTF-8 JSON."""
    _validate_project(project)
    document = {
        "format": PROJECT_FORMAT,
        "schema_version": SCHEMA_VERSION,
        "tools": {
            "calclens_version": project.calclens_version,
            "ase_version": project.ase_version,
        },
        "state": {
            "selected_id": project.selected_id,
            "review_focus": project.review_focus,
            "filter_mode": project.filter_mode,
        },
        "entries": [
            {
                "id": entry.id,
                "filename": entry.filename,
                "cif_base64": base64.b64encode(entry.data).decode("ascii"),
                "sha256": hashlib.sha256(entry.data).hexdigest(),
                "normal_axis": entry.normal_axis,
                "short_distance": float(entry.short_distance),
                "note": entry.note,
                "reviewed": entry.reviewed,
            }
            for entry in project.entries
        ],
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


def _load_entry(value: object, index: int) -> ProjectEntry:
    label = f"Entry {index}"
    entry = _mapping(value, label, {
        "id", "filename", "cif_base64", "sha256", "normal_axis", "short_distance", "note", "reviewed",
    })
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
    if hashlib.sha256(original).hexdigest() != digest:
        raise ProjectError(f"{label} embedded CIF content does not match its SHA-256; it may be damaged.")
    return ProjectEntry(
        id=entry["id"], filename=entry["filename"], data=original,
        normal_axis=entry["normal_axis"], short_distance=entry["short_distance"],
        note=entry["note"], reviewed=entry["reviewed"],
    )


def loads_project(data: bytes) -> Project:
    """Reopen bounded, validated embedded originals without reading external paths."""
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
    if type(document["schema_version"]) is not int or document["schema_version"] != SCHEMA_VERSION:
        raise ProjectError("Unsupported project schema version; this CalcLens supports version 1.")
    tools = _mapping(document["tools"], "Project tools", {"calclens_version", "ase_version"})
    state = _mapping(document["state"], "Project state", {"selected_id", "review_focus", "filter_mode"})
    entries = document["entries"]
    if not isinstance(entries, list) or not 1 <= len(entries) <= MAX_PROJECT_FILES:
        raise ProjectError(f"A project must contain between 1 and {MAX_PROJECT_FILES} CIF files.")
    project = Project(
        entries=[_load_entry(value, index) for index, value in enumerate(entries, 1)],
        selected_id=state["selected_id"], review_focus=state["review_focus"],
        filter_mode=state["filter_mode"], calclens_version=tools["calclens_version"],
        ase_version=tools["ase_version"],
    )
    _validate_project(project)
    return project
