"""Loopback-only HTTP adapter for the CalcLens desktop workspace."""

from __future__ import annotations

import argparse
import base64
import binascii
from dataclasses import replace
import hashlib
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import mimetypes
from pathlib import Path, PurePosixPath
import re
import secrets
import threading
from typing import Any, Callable
from urllib.parse import parse_qs, unquote, urlsplit
from uuid import uuid4
import webbrowser

import ase

from . import __version__
from .batch import BatchInput, batch_csv
from .core import UnsupportedStructure, _read_cif, measure_atom_pair
from .project import (
    ANALYSIS_REVISION,
    MAX_ENCODED_FILE_BYTES,
    MAX_ARCHIVE_BYTES,
    MAX_FILE_BYTES,
    MAX_IMAGE_SHIFT,
    MAX_PAIR_SELECTIONS,
    MAX_PROJECT_BYTES,
    MAX_PROJECT_FILES,
    MAX_SITE_INDEX,
    MAX_WORKSPACE_BYTES,
    PAIR_MODES,
    PairSelection,
    Project,
    ProjectEntry,
    ProjectError,
    add_entries,
    dumps_project,
    dumps_project_archive,
    loads_project,
    mark_reviewed,
    refresh_review,
    remove_entry,
    replace_entry,
    review_is_current,
    validate_workspace_state,
)
from .reporting import (
    localized_error_message,
    localized_report,
    report_csv,
)
from .review import cached_batch


API_VERSION = 1
NORMAL_BODY_LIMIT = 1024 * 1024
SOCKET_TIMEOUT_SECONDS = 10.0
WEB_ASSETS = Path(__file__).resolve().with_name("web_assets")
EXAMPLES = (
    ("graphene.cif", "그래핀 · 단일 원자층", "Graphene · single plane"),
    ("hbn.cif", "h-BN · 단일 원자층", "h-BN · single plane"),
    ("mos2.cif", "MoS₂ · 세 원자 평면", "MoS₂ · three atomic planes"),
    ("mos2_a_normal.cif", "MoS₂ · a축 수직 방향", "MoS₂ · a-axis normal"),
    ("mos2_b_normal.cif", "MoS₂ · b축 수직 방향", "MoS₂ · b-axis normal"),
    ("graphene_duplicate.cif", "이상 예제 · 원자 중복", "Defect · duplicate site"),
    ("graphene_short_contact.cif", "이상 예제 · 짧은 거리", "Defect · short contact"),
    ("graphene_boundary_duplicate.cif", "이상 예제 · 경계 중복", "Defect · boundary duplicate"),
    ("tiny_self_image.cif", "이상 예제 · 자기 주기상", "Defect · close self image"),
    ("mos2_wrapped.cif", "MoS₂ · 경계를 넘는 층", "MoS₂ · wrapped layer"),
    ("bilayer_graphene.cif", "검토 예제 · 두 원자층", "Review · two atomic planes"),
    ("no_unique_gap.cif", "검토 예제 · 유일한 큰 간격 없음", "Review · no unique large gap"),
    ("tilted_c.cif", "미지원 · 기울어진 c축", "Unsupported · tilted c-axis"),
    ("multiple_blocks.cif", "미지원 · 여러 데이터 블록", "Unsupported · multiple data blocks"),
    ("symmetry_unsupported.cif", "미지원 · 명시되지 않은 P1 자리", "Unsupported · unexpanded symmetry"),
    ("partial_occupancy.cif", "미지원 · 부분 점유", "Unsupported · partial occupancy"),
)
EXAMPLE_NAMES = {item[0] for item in EXAMPLES}


class APIError(Exception):
    """A bounded client error that is safe to serialize."""

    def __init__(self, status: int, code: str, message: str, revision: int | None = None):
        super().__init__(message)
        self.status = status
        self.code = code
        self.message = message
        self.revision = revision


def _object(value: object, field: str, required: set[str], optional: set[str] = set()) -> dict:
    if not isinstance(value, dict):
        raise APIError(400, "invalid_request", f"{field} must be a JSON object.")
    missing = required - value.keys()
    extra = value.keys() - required - optional
    if missing:
        raise APIError(400, "invalid_request", f"{field} is missing: {', '.join(sorted(missing))}.")
    if extra:
        raise APIError(400, "invalid_request", f"{field} contains unexpected fields.")
    return value


def _unique_object(pairs: list[tuple[str, object]]) -> dict:
    value = {}
    for key, item in pairs:
        if key in value:
            raise APIError(400, "invalid_json", "JSON contains duplicate object fields.")
        value[key] = item
    return value


def _reject_constant(value: str) -> None:
    raise APIError(400, "invalid_json", "JSON cannot contain NaN or Infinity.")


def _json(data: bytes) -> object:
    try:
        return json.loads(
            data.decode("utf-8"), object_pairs_hook=_unique_object,
            parse_constant=_reject_constant,
        )
    except APIError:
        raise
    except (UnicodeDecodeError, json.JSONDecodeError, RecursionError) as exc:
        raise APIError(400, "invalid_json", "Request body must be valid UTF-8 JSON.") from exc


def _language(value: object) -> str:
    if not isinstance(value, str) or value not in ("ko", "en"):
        raise APIError(400, "invalid_language", "Language must be 'ko' or 'en'.")
    return value


def _integer(value: object, field: str, *, minimum: int | None = None) -> int:
    if type(value) is not int or (minimum is not None and value < minimum):
        raise APIError(400, "invalid_request", f"{field} must be an integer.")
    return value


def _site_index(value: object, field: str) -> int:
    result = _integer(value, field, minimum=0)
    if result > MAX_SITE_INDEX:
        raise APIError(400, "invalid_measurement", f"{field} must be from 0 to {MAX_SITE_INDEX}.")
    return result


def _image_shift(value: object, field: str) -> tuple[int, int, int]:
    if (not isinstance(value, list) or len(value) != 3
            or any(type(item) is not int or abs(item) > MAX_IMAGE_SHIFT for item in value)):
        raise APIError(
            400, "invalid_measurement",
            f"{field} must contain three integer shifts from {-MAX_IMAGE_SHIFT} to {MAX_IMAGE_SHIFT}.",
        )
    return tuple(value)


def _decode_file(value: object, label: str) -> tuple[str, bytes]:
    item = _object(value, label, {"filename", "data_base64"})
    filename, encoded = item["filename"], item["data_base64"]
    if not isinstance(filename, str) or not isinstance(encoded, str):
        raise APIError(400, "invalid_file", f"{label} filename and data_base64 must be text.")
    if not encoded or len(encoded) > MAX_ENCODED_FILE_BYTES:
        raise APIError(413, "file_too_large", f"{label} exceeds the encoded CIF size limit.")
    try:
        data = base64.b64decode(encoded, validate=True)
    except (binascii.Error, ValueError) as exc:
        raise APIError(400, "invalid_base64", f"{label} data_base64 is invalid.") from exc
    if not 1 <= len(data) <= MAX_FILE_BYTES:
        raise APIError(413, "file_too_large", f"{label} must contain 1 byte to 2 MiB.")
    return filename, data


def _stamp(stamp) -> dict | None:
    if stamp is None:
        return None
    return {
        "sha256": stamp.sha256,
        "normal_axis": stamp.normal_axis,
        "short_distance": stamp.short_distance,
        "analysis_revision": stamp.analysis_revision,
        "ase_version": stamp.ase_version,
        "calclens_version": stamp.calclens_version,
    }


def _selection(item: PairSelection) -> dict:
    return {
        "i": item.i,
        "j": item.j,
        "first_shift": list(item.first_shift),
        "second_shift": list(item.second_shift),
        "mode": item.mode,
    }


class Workspace:
    """One locked project and one bounded analysis cache per desktop server."""

    def __init__(self, root: Path, language: str = "ko", *, load_default: bool = True):
        self.root = Path(root).resolve()
        self.language = _language(language)
        self.token = secrets.token_urlsafe(32)
        self.revision = 0
        self.lock = threading.RLock()
        self.cache: dict = {}
        self.project = self._example_project("graphene.cif") if load_default else Project([])
        self._validated_workspace: tuple[dict, int] = (self.project.workspace_state, 2)

    def load_initial_example(self) -> dict:
        """Fill an empty desktop workspace and analyze it away from the UI thread.

        Do not replace a project opened while initialization was queued. The
        default server and direct/test construction keep their previous behavior.
        """
        with self.lock:
            if not self.project.entries and self.revision == 0:
                self.project = self._example_project("graphene.cif")
                self._validated_workspace = (self.project.workspace_state, 2)
            return self.snapshot(include_workspace=True)

    def _example_data(self, name: str) -> bytes:
        if name not in EXAMPLE_NAMES:
            raise APIError(404, "unknown_example", "Unknown bundled example.")
        try:
            return (self.root / "examples" / name).read_bytes()
        except OSError as exc:
            raise APIError(500, "missing_example", "Bundled example is unavailable.") from exc

    def _example_project(self, name: str) -> Project:
        normal_axis = {"mos2_a_normal.cif": "a", "mos2_b_normal.cif": "b"}.get(name, "c")
        entry = ProjectEntry(uuid4().hex, name, self._example_data(name), normal_axis)
        return Project([entry], selected_id=entry.id)

    def _entry(self, entry_id: object) -> ProjectEntry:
        if not isinstance(entry_id, str):
            raise APIError(400, "invalid_request", "Entry ID must be text.")
        entry = next((item for item in self.project.entries if item.id == entry_id), None)
        if entry is None:
            raise APIError(404, "entry_not_found", "Entry ID does not identify a workspace file.")
        return entry

    def _results(self, project: Project | None = None) -> list[dict]:
        detached = project is not None
        project = self.project if project is None else project
        if not project.entries:
            return []
        return cached_batch([
            BatchInput(item.filename, item.data, item.normal_axis, item.short_distance)
            for item in project.entries
        ], {} if detached else self.cache)

    def _result(self, entry_id: str) -> tuple[ProjectEntry, dict]:
        entry = self._entry(entry_id)
        index = self.project.entries.index(entry)
        return entry, self._results()[index]

    def snapshot(self, project: Project | None = None, *, include_workspace: bool = False) -> dict:
        with self.lock:
            results = self._results(project)
            project = self.project if project is None else project
            entries = []
            for entry, result in zip(project.entries, results):
                report = result["report"]
                analysis: dict[str, Any] = {"report": report, "error": result["error"]}
                if report is not None:
                    korean = localized_report(report, "ko")
                    analysis["issues_ko"] = korean["issues"]
                    analysis["assumptions_ko"] = korean["assumptions"]
                    analysis["limitations_ko"] = korean["limitations"]
                elif result["error"] is not None:
                    analysis["error_ko"] = localized_error_message(result["error"], "ko")
                    if include_workspace:
                        structure = self._auxiliary_structure(entry)
                        if structure is not None:
                            analysis["auxiliary_structure"] = structure
                entries.append({
                    "id": entry.id,
                    "filename": entry.filename,
                    "sha256": hashlib.sha256(entry.data).hexdigest(),
                    "normal_axis": entry.normal_axis,
                    "short_distance": entry.short_distance,
                    "note": entry.note,
                    "reviewed": entry.reviewed,
                    "review_current": review_is_current(entry),
                    "review_stamp": _stamp(entry.review_stamp),
                    "measurements": [_selection(item) for item in entry.measurements],
                    "preparation": self._preparation_summary(entry),
                    "analysis": analysis,
                })
            snapshot = {
                "api_version": API_VERSION,
                "token": self.token,
                "revision": self.revision,
                "language": self.language,
                "examples": [
                    {"name": name, "label_ko": ko, "label_en": en}
                    for name, ko, en in EXAMPLES
                ],
                "limits": {
                    "max_files": MAX_PROJECT_FILES,
                    "max_file_bytes": MAX_FILE_BYTES,
                    "max_pair_selections": MAX_PAIR_SELECTIONS,
                    "max_project_bytes": MAX_PROJECT_BYTES,
                    "max_workspace_bytes": MAX_WORKSPACE_BYTES,
                },
                "runtime": {
                    "calclens_version": __version__,
                    "ase_version": ase.__version__,
                    "analysis_revision": ANALYSIS_REVISION,
                },
                "project": {
                    "selected_id": project.selected_id,
                    "review_focus": project.review_focus,
                    "filter_mode": project.filter_mode,
                    "progress_filter": project.progress_filter,
                    "calclens_version": project.calclens_version,
                    "ase_version": project.ase_version,
                    "analysis_revision": project.analysis_revision,
                },
                "entries": entries,
            }
            if include_workspace:
                snapshot["project"]["workspace_state"] = project.workspace_state
            return snapshot

    @staticmethod
    def _auxiliary_structure(entry: ProjectEntry) -> dict | None:
        """Read actual explicit-P1 sites for data matching, without a report.

        A user's chosen slab normal may be unsupported while the original P1
        structure remains valid. This does not change that setting, manufacture
        metrics, or expand symmetry. Every original core input guard still runs.
        """
        for axis in dict.fromkeys((entry.normal_axis, "a", "b", "c")):
            try:
                atoms, _ = _read_cif(entry.data, axis)
            except UnsupportedStructure:
                continue
            return {
                "atom_count": len(atoms), "elements": atoms.get_chemical_symbols(),
                "positions": atoms.positions.tolist(),
            }
        return None

    @staticmethod
    def _preparation_summary(entry: ProjectEntry) -> dict | None:
        if entry.preparation is None:
            return None
        record = entry.preparation
        return {
            **{key: value for key, value in record.items() if key != "source"},
            "source_filename": record["source"]["filename"],
        }

    def _validated(self, project: Project) -> Project:
        project = self._prune_workspace_bindings(project)
        state = project.workspace_state
        previous, previous_size = self._validated_workspace
        # HTTP actions never mutate the already-validated extension in place.
        # Keep the large raw-data extension out of minor-action serialization.
        state_size = previous_size if state is previous else validate_workspace_state(state)
        lean = dumps_project(replace(project, workspace_state={}))
        if len(lean) + state_size - 2 > MAX_PROJECT_BYTES:
            raise ProjectError(f"Project JSON exceeds the {MAX_PROJECT_BYTES}-byte limit.")
        self._validated_workspace = (state, state_size)
        return project

    def _prune_workspace_bindings(self, project: Project) -> Project:
        """Drop known client references when their exact source disappears."""
        if [(item.id, item.data) for item in project.entries] == [
                (item.id, item.data) for item in self.project.entries]:
            return project
        state = project.workspace_state
        if not isinstance(state, dict) or state.get("schema_version") != 1:
            return project
        if any(not isinstance(state.get(key), dict) for key in ("auxiliary", "viewers", "drafts")):
            return replace(project, workspace_state={})
        sources = {hashlib.sha256(entry.data).hexdigest() for entry in project.entries}
        bindings = {entry.id: hashlib.sha256(entry.data).hexdigest() for entry in project.entries}
        viewer_keys = {f"{slot}:{entry_id}:{digest}" for entry_id, digest in bindings.items()
                       for slot in ("overview", "left", "right")}
        updated = {
            **state,
            "auxiliary": {key: value for key, value in state["auxiliary"].items() if key in sources},
            "viewers": {key: value for key, value in state["viewers"].items() if key in viewer_keys},
            "drafts": {key: value for key, value in state["drafts"].items()
                       if key in bindings and isinstance(value, dict)
                       and value.get("sha256") == bindings[key]},
        }
        if isinstance(state.get("comparison"), dict):
            comparison = state["comparison"]
            updated["comparison"] = {
                **comparison,
                "before": comparison.get("before") if isinstance(comparison.get("before"), str)
                and comparison["before"] in bindings else "",
                "after": comparison.get("after") if isinstance(comparison.get("after"), str)
                and comparison["after"] in bindings else "",
            }
        return project if updated == state else replace(project, workspace_state=updated)

    def _replace_entry(self, entry: ProjectEntry) -> None:
        entries = [entry if item.id == entry.id else item for item in self.project.entries]
        self.project = self._validated(replace(self.project, entries=entries))

    def apply(self, expected_revision: object, action_value: object) -> dict:
        expected = _integer(expected_revision, "expected_revision", minimum=0)
        action = _object(action_value, "action", {"type"}, {
            "name", "files", "mode", "id", "filename", "data_base64",
            "normal_axis", "short_distance", "note", "value", "selected_id",
            "review_focus", "filter_mode", "progress_filter", "language",
            "selection", "index",
            "source_sha256",
        })
        action_type = action["type"]
        if not isinstance(action_type, str):
            raise APIError(400, "invalid_action", "Action type must be text.")
        with self.lock:
            if expected != self.revision:
                raise APIError(
                    409, "revision_conflict", "Workspace revision is stale.", self.revision
                )
            try:
                self._apply_locked(action_type, action)
            except APIError:
                raise
            except ProjectError as exc:
                raise APIError(422, "invalid_project", str(exc)) from exc
            self.revision += 1
            return self.snapshot()

    def _apply_locked(self, action_type: str, action: dict) -> None:
        def exact(required: set[str], optional: set[str] = set()) -> None:
            _object(action, "action", {"type", *required}, optional)

        if action_type == "load_example":
            exact({"name"})
            if not isinstance(action["name"], str):
                raise APIError(400, "invalid_request", "Example name must be text.")
            self.project = self._example_project(action["name"])
        elif action_type == "import_cifs":
            exact({"files", "mode"})
            if action["mode"] not in ("replace", "append") or not isinstance(action["files"], list):
                raise APIError(400, "invalid_request", "Import mode or files are invalid.")
            if not action["files"]:
                raise APIError(400, "invalid_request", "Import at least one CIF file.")
            total = len(action["files"])
            if action["mode"] == "append":
                total += len(self.project.entries)
            if total > MAX_PROJECT_FILES:
                raise APIError(
                    422, "file_limit", f"A workspace can contain at most {MAX_PROJECT_FILES} files."
                )
            new_entries = []
            for index, value in enumerate(action["files"], 1):
                filename, data = _decode_file(value, f"File {index}")
                new_entries.append(ProjectEntry(uuid4().hex, filename, data))
            if action["mode"] == "append":
                self.project = self._validated(add_entries(self.project, new_entries))
            else:
                first = new_entries[0].id
                self.project = self._validated(Project(
                    new_entries, selected_id=first,
                    review_focus=self.project.review_focus,
                    filter_mode=self.project.filter_mode,
                    progress_filter=self.project.progress_filter,
                ))
        elif action_type == "replace_source":
            exact({"id", "filename", "data_base64"})
            filename, data = _decode_file(
                {"filename": action["filename"], "data_base64": action["data_base64"]},
                "Replacement file",
            )
            self.project = self._validated(replace_entry(self.project, action["id"], filename, data))
        elif action_type == "prepare_p1":
            from .preparation import PreparationError, prepare_p1

            exact({"id", "source_sha256"})
            entry = self._entry(action["id"])
            if (not isinstance(action["source_sha256"], str)
                    or action["source_sha256"] != hashlib.sha256(entry.data).hexdigest()):
                raise APIError(409, "source_conflict", "Preparation source has changed; preview it again.")
            if entry.preparation is not None:
                raise APIError(422, "already_prepared", "This entry already retains a P1 preparation record.")
            try:
                prepared = prepare_p1(entry.data, entry.normal_axis)
            except PreparationError as exc:
                raise APIError(422, "unsupported_preparation", str(exc)) from exc
            record = {
                **prepared.metadata(), "schema_version": 1, "normal_axis": entry.normal_axis,
                "source": {
                    "filename": entry.filename,
                    "cif_base64": base64.b64encode(entry.data).decode("ascii"),
                    "sha256": prepared.source_sha256,
                },
            }
            self._replace_entry(replace(
                entry, data=prepared.cif, reviewed=False, measurements=(), preparation=record,
            ))
        elif action_type == "remove_entry":
            exact({"id"})
            self.project = self._validated(remove_entry(self.project, action["id"]))
        elif action_type == "patch_entry":
            allowed = {"normal_axis", "short_distance", "note"}
            exact({"id"}, allowed)
            fields = allowed & action.keys()
            if not fields:
                raise APIError(400, "invalid_request", "Patch at least one entry field.")
            entry = self._entry(action["id"])
            changes = {field: action[field] for field in fields}
            if any(field in fields and action[field] != getattr(entry, field)
                   for field in ("normal_axis", "short_distance")):
                changes["reviewed"] = False
            self._replace_entry(refresh_review(replace(entry, **changes)))
        elif action_type == "set_reviewed":
            exact({"id", "value"})
            if type(action["value"]) is not bool:
                raise APIError(400, "invalid_request", "Reviewed value must be boolean.")
            self._replace_entry(mark_reviewed(self._entry(action["id"]), action["value"]))
        elif action_type == "patch_workspace":
            allowed = {"selected_id", "review_focus", "filter_mode", "progress_filter", "language"}
            exact(set(), allowed)
            fields = allowed & action.keys()
            if not fields:
                raise APIError(400, "invalid_request", "Patch at least one workspace field.")
            language = _language(action["language"]) if "language" in fields else self.language
            project_changes = {field: action[field] for field in fields - {"language"}}
            if project_changes:
                self.project = self._validated(replace(self.project, **project_changes))
            self.language = language
        elif action_type == "save_measurement":
            exact({"id", "selection"})
            selection = self._pair(action["selection"])
            entry, result = self._result(action["id"])
            if result["report"] is None:
                raise APIError(422, "unsupported_entry", "Cannot measure an unsupported entry.")
            measure_atom_pair(
                result["report"], selection.i, selection.j,
                selection.first_shift, selection.second_shift,
            )
            if len(entry.measurements) >= MAX_PAIR_SELECTIONS:
                raise APIError(422, "measurement_limit", "Pair selection limit reached.")
            if selection not in entry.measurements:
                self._replace_entry(replace(
                    entry, measurements=(*entry.measurements, selection)
                ))
        elif action_type == "remove_measurement":
            exact({"id", "index"})
            entry = self._entry(action["id"])
            index = _integer(action["index"], "Measurement index", minimum=0)
            if index >= len(entry.measurements):
                raise APIError(404, "measurement_not_found", "Measurement index is unavailable.")
            measurements = entry.measurements[:index] + entry.measurements[index + 1:]
            self._replace_entry(replace(entry, measurements=measurements))
        else:
            raise APIError(400, "unknown_action", "Unknown workspace action.")

    def _pair(self, value: object) -> PairSelection:
        item = _object(
            value, "selection", {"i", "j", "first_shift", "second_shift", "mode"}
        )
        i = _site_index(item["i"], "First atom index")
        j = _site_index(item["j"], "Second atom index")
        if i == j:
            raise APIError(400, "invalid_measurement", "Select two distinct atom indices.")
        if not isinstance(item["mode"], str) or item["mode"] not in PAIR_MODES:
            raise APIError(400, "invalid_measurement", "Measurement mode is invalid.")
        return PairSelection(
            i, j, _image_shift(item["first_shift"], "First image shift"),
            _image_shift(item["second_shift"], "Second image shift"), item["mode"],
        )

    def import_project(self, expected_revision: int, data: bytes, *, preview: bool = False) -> dict:
        expected_revision = _integer(expected_revision, "expected_revision", minimum=0)
        with self.lock:
            if expected_revision != self.revision:
                raise APIError(409, "revision_conflict", "Workspace revision is stale.", self.revision)
            try:
                project = loads_project(data)
            except ProjectError as exc:
                raise APIError(422, "invalid_project", str(exc)) from exc
            if project.selected_id is None:
                project = replace(project, selected_id=project.entries[0].id)
            if preview:
                return self.snapshot(project, include_workspace=True)
            self.project = project
            self.revision += 1
            return self.snapshot(include_workspace=True)

    def export_project(self) -> bytes:
        with self.lock:
            current = Project(
                list(self.project.entries), selected_id=self.project.selected_id,
                review_focus=self.project.review_focus,
                filter_mode=self.project.filter_mode,
                progress_filter=self.project.progress_filter,
                workspace_state=self.project.workspace_state,
            )
            return dumps_project(current)

    def export_workspace(self, value: object) -> bytes:
        body = _object(value, "Export", {"expected_revision", "workspace_state"})
        expected = _integer(body["expected_revision"], "expected_revision", minimum=0)
        with self.lock:
            if expected != self.revision:
                raise APIError(409, "revision_conflict", "Workspace revision is stale.", self.revision)
            project = replace(
                self.project, calclens_version=__version__, ase_version=ase.__version__,
                analysis_revision=ANALYSIS_REVISION, workspace_state=body["workspace_state"],
            )
            try:
                return dumps_project_archive(project)
            except ProjectError as exc:
                raise APIError(422, "invalid_project", str(exc)) from exc

    def preview_p1(self, value: object) -> dict:
        from .preparation import PreparationError, prepare_p1

        body = _object(value, "Preparation", {"expected_revision", "entry_id"})
        expected = _integer(body["expected_revision"], "expected_revision", minimum=0)
        with self.lock:
            if expected != self.revision:
                raise APIError(409, "revision_conflict", "Workspace revision is stale.", self.revision)
            entry = self._entry(body["entry_id"])
            if entry.preparation is not None:
                raise APIError(422, "already_prepared", "This entry already retains a P1 preparation record.")
            try:
                prepared = prepare_p1(entry.data, entry.normal_axis)
            except PreparationError as exc:
                raise APIError(422, "unsupported_preparation", str(exc)) from exc
            return {
                **prepared.metadata(), "entry_id": entry.id, "revision": self.revision,
                "prepared_cif": prepared.cif.decode("utf-8"),
            }

    def measure(self, value: object) -> dict:
        body = _object(
            value, "Measurement",
            {"expected_revision", "entry_id", "i", "j", "first_shift", "second_shift"},
        )
        expected = _integer(body["expected_revision"], "expected_revision", minimum=0)
        i = _site_index(body["i"], "First atom index")
        j = _site_index(body["j"], "Second atom index")
        if i == j:
            raise APIError(400, "invalid_measurement", "Select two distinct atom indices.")
        first_shift = _image_shift(body["first_shift"], "First image shift")
        second_shift = _image_shift(body["second_shift"], "Second image shift")
        with self.lock:
            if expected != self.revision:
                raise APIError(
                    409, "revision_conflict", "Workspace revision is stale.", self.revision
                )
            _, result = self._result(body["entry_id"])
            if result["report"] is None:
                raise APIError(422, "unsupported_entry", "Cannot measure an unsupported entry.")
            try:
                return measure_atom_pair(
                    result["report"], i, j, first_shift, second_shift,
                )
            except ValueError as exc:
                raise APIError(422, "invalid_measurement", str(exc)) from exc


class CalcLensServer(ThreadingHTTPServer):
    daemon_threads = True
    allow_reuse_address = True

    workspace: Workspace
    expected_host: str


class RequestHandler(BaseHTTPRequestHandler):
    server: CalcLensServer

    def setup(self) -> None:
        super().setup()
        self.connection.settimeout(SOCKET_TIMEOUT_SECONDS)

    def log_message(self, format: str, *args) -> None:
        return

    def _headers(self, content_type: str, length: int, *, disposition: str | None = None) -> None:
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(length))
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Cache-Control", "no-store")
        self.send_header(
            "Content-Security-Policy",
            "default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; "
            "img-src 'self' data:; connect-src 'self'; worker-src 'self' blob:; "
            "object-src 'none'; base-uri 'none'; frame-ancestors 'none'",
        )
        if disposition is not None:
            self.send_header("Content-Disposition", disposition)

    def _bytes(
        self, status: int, data: bytes, content_type: str,
        *, disposition: str | None = None,
    ) -> None:
        self.send_response(status)
        self._headers(content_type, len(data), disposition=disposition)
        self.end_headers()
        if self.command != "HEAD":
            self.wfile.write(data)

    def _json_response(self, status: int, value: object) -> None:
        self._bytes(
            status,
            json.dumps(value, ensure_ascii=False, allow_nan=False, separators=(",", ":")).encode(),
            "application/json; charset=utf-8",
        )

    def _error(self, error: APIError) -> None:
        payload: dict[str, Any] = {"error": {"code": error.code, "message": error.message}}
        if error.revision is not None:
            payload["revision"] = error.revision
        self._json_response(error.status, payload)

    def _single_header(self, name: str, *, required: bool = True) -> str | None:
        values = self.headers.get_all(name, failobj=[])
        if len(values) > 1 or (required and len(values) != 1):
            raise APIError(400, "invalid_header", f"Specify exactly one {name} header.")
        return values[0] if values else None

    def _host(self) -> None:
        if self._single_header("Host") != self.server.expected_host:
            raise APIError(403, "invalid_host", "Host header is not the CalcLens loopback origin.")

    def _authorize(self) -> None:
        self._host()
        origin = f"http://{self.server.expected_host}"
        if self._single_header("Origin", required=False) != origin:
            raise APIError(403, "invalid_origin", "Origin is not the CalcLens loopback origin.")
        supplied = self._single_header("X-CalcLens-Token", required=False) or ""
        if not secrets.compare_digest(supplied, self.server.workspace.token):
            raise APIError(403, "invalid_token", "CalcLens mutation token is missing or invalid.")

    def _body(self, limit: int) -> bytes:
        if self._single_header("Transfer-Encoding", required=False) is not None:
            raise APIError(400, "chunked_not_allowed", "Chunked request bodies are not supported.")
        raw = self._single_header("Content-Length", required=False)
        if raw is None or not raw.isdigit():
            raise APIError(411, "length_required", "A valid Content-Length is required.")
        length = int(raw)
        if length > limit:
            raise APIError(413, "request_too_large", "Request body exceeds the allowed size.")
        try:
            data = self.rfile.read(length)
        except TimeoutError as exc:
            raise APIError(408, "request_timeout", "Request body was not received in time.") from exc
        if len(data) != length:
            raise APIError(400, "incomplete_body", "Request body ended early.")
        return data

    def _require_json_content_type(self) -> None:
        content_type = self._single_header("Content-Type", required=False)
        media_type = content_type.split(";", 1)[0].strip().lower() if content_type else ""
        if media_type != "application/json":
            raise APIError(415, "unsupported_media_type", "Content-Type must be application/json.")

    def _query_language(self, query: str) -> str:
        values = parse_qs(query, keep_blank_values=True, strict_parsing=True)
        if set(values) - {"lang"} or len(values.get("lang", [])) != 1:
            raise APIError(400, "invalid_query", "Specify exactly one lang=ko or lang=en.")
        return _language(values["lang"][0])

    def do_GET(self) -> None:
        try:
            self._host()
            parsed = urlsplit(self.path)
            if parsed.path == "/_calclens/health" and not parsed.query:
                self._bytes(200, b"ok", "text/plain; charset=utf-8")
                return
            if parsed.path in ("/api/v1/bootstrap", "/api/v1/workspace") and not parsed.query:
                self._json_response(
                    200, self.server.workspace.snapshot(include_workspace=parsed.path.endswith("/bootstrap"))
                )
                return
            if parsed.path == "/api/v1/project/export" and not parsed.query:
                self._bytes(
                    200, self.server.workspace.export_project(), "application/json; charset=utf-8",
                    disposition='attachment; filename="calclens_work.calclens.json"',
                )
                return
            if parsed.path == "/api/v1/comparison.csv":
                language = self._query_language(parsed.query)
                with self.server.workspace.lock:
                    data = batch_csv(self.server.workspace._results(), language).encode(
                        "utf-8-sig" if language == "ko" else "utf-8"
                    )
                self._bytes(
                    200, data, "text/csv; charset=utf-8",
                    disposition=f'attachment; filename="calclens_comparison_{language}.csv"',
                )
                return
            match = re.fullmatch(r"/api/v1/entries/([^/]+)/report\.(json|csv)", parsed.path)
            if match:
                entry_id, kind = unquote(match.group(1)), match.group(2)
                language = self._query_language(parsed.query)
                with self.server.workspace.lock:
                    _, result = self.server.workspace._result(entry_id)
                    report = result["report"]
                if report is None:
                    raise APIError(422, "unsupported_entry", "Entry has no numeric report.")
                if kind == "json":
                    data = json.dumps(
                        localized_report(report, language), ensure_ascii=False,
                        allow_nan=False, indent=2,
                    ).encode()
                    mime, suffix = "application/json; charset=utf-8", "json"
                else:
                    data = report_csv(report, language).encode(
                        "utf-8-sig" if language == "ko" else "utf-8"
                    )
                    mime, suffix = "text/csv; charset=utf-8", "csv"
                self._bytes(
                    200, data, mime,
                    disposition=f'attachment; filename="calclens_report_{language}.{suffix}"',
                )
                return
            self._static(parsed.path, parsed.query)
        except APIError as exc:
            self._error(exc)
        except (ValueError, ProjectError) as exc:
            self._error(APIError(400, "invalid_request", str(exc)))
        except Exception:
            self._error(APIError(500, "internal_error", "CalcLens could not complete the request."))

    def _static(self, path: str, query: str) -> None:
        if query:
            raise APIError(404, "not_found", "Resource not found.")
        decoded = unquote(path)
        relative = "index.html" if decoded == "/" else decoded.removeprefix("/")
        pure = PurePosixPath(relative)
        if (not relative or pure.is_absolute() or ".." in pure.parts or "\\" in relative
                or "\x00" in relative):
            raise APIError(404, "not_found", "Resource not found.")
        assets = WEB_ASSETS.resolve()
        target = (assets / Path(*pure.parts)).resolve()
        if not target.is_relative_to(assets) or not target.is_file():
            raise APIError(404, "not_found", "Resource not found.")
        mime = mimetypes.guess_type(target.name)[0] or "application/octet-stream"
        self._bytes(200, target.read_bytes(), mime)

    def do_POST(self) -> None:
        try:
            self._authorize()
            parsed = urlsplit(self.path)
            if parsed.query:
                raise APIError(400, "invalid_query", "POST endpoints do not accept query fields.")
            if parsed.path == "/api/v1/actions":
                self._require_json_content_type()
                data = self._body(MAX_PROJECT_BYTES)
                body = _object(_json(data), "Request", {"expected_revision", "action"})
                action = body["action"]
                action_type = action.get("type") if isinstance(action, dict) else None
                if len(data) > NORMAL_BODY_LIMIT and action_type not in ("import_cifs", "replace_source"):
                    raise APIError(413, "request_too_large", "This action exceeds the normal body limit.")
                self._json_response(
                    200, self.server.workspace.apply(body["expected_revision"], action)
                )
                return
            if parsed.path == "/api/v1/project/export":
                self._require_json_content_type()
                data = self._body(MAX_PROJECT_BYTES)
                self._bytes(
                    200, self.server.workspace.export_workspace(_json(data)), "application/zip",
                    disposition='attachment; filename="calclens_work.calclens.zip"',
                )
                return
            if parsed.path in ("/api/v1/project/import", "/api/v1/project/preview"):
                content_type = self._single_header("Content-Type", required=False)
                media_type = content_type.split(";", 1)[0].strip().lower() if content_type else ""
                if media_type not in ("application/json", "application/zip", "application/octet-stream"):
                    raise APIError(415, "unsupported_media_type", "Project content must be JSON or a CalcLens ZIP archive.")
                data = self._body(max(MAX_PROJECT_BYTES, MAX_ARCHIVE_BYTES))
                raw_revision = self._single_header("X-CalcLens-Revision", required=False)
                if raw_revision is None or not raw_revision.isdigit():
                    raise APIError(400, "invalid_revision", "X-CalcLens-Revision must be an integer.")
                self._json_response(
                    200, self.server.workspace.import_project(
                        int(raw_revision), data, preview=parsed.path.endswith("/preview"),
                    )
                )
                return
            if parsed.path == "/api/v1/prepare/p1":
                self._require_json_content_type()
                self._json_response(
                    200, self.server.workspace.preview_p1(_json(self._body(NORMAL_BODY_LIMIT)))
                )
                return
            if parsed.path == "/api/v1/measure":
                self._require_json_content_type()
                self._json_response(200, self.server.workspace.measure(_json(self._body(NORMAL_BODY_LIMIT))))
                return
            raise APIError(404, "not_found", "Endpoint not found.")
        except APIError as exc:
            self._error(exc)
        except (ValueError, ProjectError) as exc:
            self._error(APIError(422, "invalid_request", str(exc)))
        except Exception:
            self._error(APIError(500, "internal_error", "CalcLens could not complete the request."))

    def do_OPTIONS(self) -> None:
        self._error(APIError(405, "method_not_allowed", "CORS preflight is not supported."))


def create_server(root: Path, port: int, language: str = "ko") -> CalcLensServer:
    """Create one ready-to-serve loopback server and its singleton workspace."""
    workspace = Workspace(Path(root), language)
    server = CalcLensServer(("127.0.0.1", int(port)), RequestHandler)
    server.workspace = workspace
    server.expected_host = f"127.0.0.1:{server.server_port}"
    server.token = workspace.token
    return server


def run_server(
    root: Path,
    port: int,
    language: str = "ko",
    on_ready: Callable[[str, CalcLensServer], None] | None = None,
) -> None:
    """Bind, announce readiness, serve until interrupted, and always close."""
    server = create_server(root, port, language)
    url = f"http://{server.expected_host}/"
    try:
        if on_ready is not None:
            on_ready(url, server)
        server.serve_forever()
    finally:
        server.server_close()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run the local CalcLens workspace server.")
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--port", type=int, default=8501)
    parser.add_argument("--language", choices=("ko", "en"), default="ko")
    parser.add_argument("--no-browser", action="store_true")
    args = parser.parse_args(argv)

    def ready(url: str, _server: CalcLensServer) -> None:
        print(url, flush=True)
        if not args.no_browser:
            webbrowser.open(url)

    try:
        run_server(args.root, args.port, args.language, ready)
    except KeyboardInterrupt:
        return 130
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
