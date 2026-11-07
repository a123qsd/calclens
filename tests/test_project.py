"""Portable projects preserve source identity and fail closed on damaged state."""
from dataclasses import FrozenInstanceError, replace
import base64
import hashlib
import json

import ase
import pytest

from slab_preflight import __version__
from slab_preflight import project as project_module
from slab_preflight.project import (
    FILTER_MODES,
    MAX_FILE_BYTES,
    MAX_IMAGE_SHIFT,
    MAX_NOTE_LENGTH,
    MAX_PAIR_SELECTIONS,
    MAX_PROJECT_FILES,
    PROGRESS_FILTERS,
    REVIEW_FOCUSES,
    PairSelection,
    Project,
    ProjectEntry,
    ProjectError,
    add_entries,
    dumps_project,
    loads_project,
    mark_reviewed,
    refresh_review,
    remove_entry,
    replace_entry,
    review_is_current,
)


def sample_project():
    reviewed = mark_reviewed(ProjectEntry(
        "first", "같은 이름.cif", b"data_original\r\n\xff\x00", "a", 0.1,
        "첫 번째 구조\n원본 보존",
        measurements=(PairSelection(0, 1, mode="displayed"),),
    ))
    return Project(
        entries=[
            reviewed,
            ProjectEntry("second", "같은 이름.cif", b"different\ncontent", "b", 3.0,
                         "Review <script> as plain text", False),
        ],
        selected_id="second", review_focus="short", filter_mode="needs_review",
        progress_filter="reviewed",
    )


def document():
    return json.loads(dumps_project(sample_project()))


def encode(value):
    return json.dumps(value).encode("utf-8")


def test_roundtrip_preserves_binary_originals_duplicate_names_identity_and_review_state():
    original = sample_project()
    saved = dumps_project(original)
    reopened = loads_project(saved)
    assert reopened == original
    assert reopened.entries[0].data != reopened.entries[1].data
    saved_document = json.loads(saved)
    assert saved_document["format"] == "calclens.project"
    assert saved_document["schema_version"] == 3
    for entry, embedded in zip(original.entries, saved_document["entries"]):
        assert base64.b64decode(embedded["cif_base64"]) == entry.data
        assert embedded["sha256"] == hashlib.sha256(entry.data).hexdigest()
        assert "report" not in embedded
    with pytest.raises(FrozenInstanceError):
        reopened.entries[0].note = "mutated"
    with pytest.raises(FrozenInstanceError):
        reopened.selected_id = "first"


def test_default_versions_and_unselected_review_state_are_portable():
    original = Project([ProjectEntry("one", "sample.cif", b"data_sample\n")])
    assert original.calclens_version == __version__
    assert original.ase_version == ase.__version__
    assert loads_project(dumps_project(original)) == original


@pytest.mark.parametrize("note", ["[" * 100, "}" * 100, '"\\' * 100])
def test_json_punctuation_in_notes_is_preserved_as_text(note):
    original = Project([ProjectEntry("one", "sample.cif", b"data_sample\n", note=note)])
    assert loads_project(dumps_project(original)) == original


@pytest.mark.parametrize("focus", REVIEW_FOCUSES)
@pytest.mark.parametrize("filter_mode", FILTER_MODES)
@pytest.mark.parametrize("progress_filter", PROGRESS_FILTERS)
def test_each_supported_review_position_and_filter_survives(
    focus, filter_mode, progress_filter,
):
    original = replace(sample_project(), review_focus=focus, filter_mode=filter_mode,
                       progress_filter=progress_filter)
    assert loads_project(dumps_project(original)) == original


def test_maximum_file_count_and_per_file_size_are_supported():
    original = Project([
        ProjectEntry(str(index), "same.cif", b"data_sample\n") for index in range(MAX_PROJECT_FILES)
    ])
    assert loads_project(dumps_project(original)) == original
    maximum_file = replace(original, entries=[ProjectEntry("max", "max.cif", b"x" * MAX_FILE_BYTES)])
    assert loads_project(dumps_project(maximum_file)) == maximum_file


@pytest.mark.parametrize("content", [None, "", "not base64!", "☃", "eA==="])
def test_missing_or_corrupt_embedded_content_is_rejected(content):
    value = document()
    value["entries"][0]["cif_base64"] = content
    with pytest.raises(ProjectError, match="embedded CIF content"):
        loads_project(encode(value))


def test_missing_payload_and_external_references_are_not_loaded():
    value = document()
    del value["entries"][0]["cif_base64"]
    value["entries"][0]["path"] = "/tmp/original.cif"
    with pytest.raises(ProjectError, match="missing required fields: cif_base64"):
        loads_project(encode(value))
    value = document()
    value["entries"][0]["url"] = "https://example.com/original.cif"
    with pytest.raises(ProjectError, match="unexpected fields"):
        loads_project(encode(value))


def test_content_and_hash_tampering_are_rejected():
    for field, replacement in (("cif_base64", base64.b64encode(b"tampered").decode()),
                               ("sha256", "0" * 64)):
        value = document()
        value["entries"][0][field] = replacement
        with pytest.raises(ProjectError, match="does not match its SHA-256"):
            loads_project(encode(value))


@pytest.mark.parametrize("digest", [None, 1, "", "not a digest", "A" * 64])
def test_invalid_hash_is_rejected(digest):
    value = document()
    value["entries"][0]["sha256"] = digest
    with pytest.raises(ProjectError, match="valid SHA-256"):
        loads_project(encode(value))


def test_decoded_and_encoded_file_size_limits_are_enforced():
    oversized = b"x" * (MAX_FILE_BYTES + 1)
    value = document()
    value["entries"][0]["cif_base64"] = base64.b64encode(oversized).decode()
    value["entries"][0]["sha256"] = hashlib.sha256(oversized).hexdigest()
    with pytest.raises(ProjectError, match="original CIF bytes"):
        loads_project(encode(value))
    value["entries"][0]["cif_base64"] += "AAAA"
    with pytest.raises(ProjectError, match="exceeds"):
        loads_project(encode(value))


def test_json_size_is_checked_before_parsing(monkeypatch):
    monkeypatch.setattr(project_module, "MAX_PROJECT_BYTES", 100)
    monkeypatch.setattr(project_module.json, "loads", lambda *args, **kwargs: pytest.fail("parsed"))
    with pytest.raises(ProjectError, match="100-byte limit"):
        loads_project(b" " * 101)
    with pytest.raises(ProjectError, match="100-byte limit"):
        dumps_project(sample_project())


@pytest.mark.parametrize("version", [4, 0, True, 1.0, "1", None])
def test_unknown_or_wrongly_typed_schema_is_rejected(version):
    value = document()
    value["schema_version"] = version
    with pytest.raises(ProjectError, match="Unsupported project schema"):
        loads_project(encode(value))


def test_wrong_format_and_missing_or_extra_document_fields_are_rejected():
    value = document()
    value["format"] = "another.tool"
    with pytest.raises(ProjectError, match="not a CalcLens"):
        loads_project(encode(value))
    for field in ("tools", "state", "entries"):
        value = document()
        del value[field]
        with pytest.raises(ProjectError, match="missing required fields"):
            loads_project(encode(value))
    value = document()
    value["report"] = {"trusted": True}
    with pytest.raises(ProjectError, match="unexpected fields"):
        loads_project(encode(value))


@pytest.mark.parametrize("data", [b"", b"not json", b"\xff", b"null", b"[]", b"1", b'"text"',
                                  b'{"format":1,"format":2}', b'{"value":NaN}',
                                  b'{"value":Infinity}'])
def test_malformed_documents_fail_with_project_error(data):
    with pytest.raises(ProjectError):
        loads_project(data)


def test_excessive_nesting_and_integer_length_fail_gracefully():
    with pytest.raises(ProjectError, match="nesting is too deep"):
        loads_project(b"[" * 5000 + b"0" + b"]" * 5000)
    with pytest.raises(ProjectError):
        loads_project(b"9" * 10_000)


@pytest.mark.parametrize("entries", [[], None, {}, "entries", [None], [1], [[]], [{}]])
def test_invalid_entry_container_and_shapes_are_rejected(entries):
    value = document()
    value["entries"] = entries
    with pytest.raises(ProjectError):
        loads_project(encode(value))


def test_too_many_files_duplicate_ids_and_missing_selection_are_rejected():
    value = document()
    value["entries"] = value["entries"][:1] * (MAX_PROJECT_FILES + 1)
    with pytest.raises(ProjectError, match="between 1 and 20"):
        loads_project(encode(value))
    value = document()
    value["entries"][1]["id"] = value["entries"][0]["id"]
    with pytest.raises(ProjectError, match="IDs must be unique"):
        loads_project(encode(value))
    value = document()
    value["state"]["selected_id"] = "missing"
    with pytest.raises(ProjectError, match="does not identify"):
        loads_project(encode(value))


@pytest.mark.parametrize("field,invalid", [
    ("id", ""), ("id", "x" * 129), ("id", []), ("id", "\x00"),
    ("filename", ""), ("filename", "x" * 256), ("filename", "../file.cif"),
    ("filename", "C:\\file.cif"), ("filename", ".."), ("filename", "name\n.cif"),
    ("filename", "\ud800"), ("note", "x" * (MAX_NOTE_LENGTH + 1)), ("note", None),
    ("note", "\x00"), ("note", "\ud800"), ("normal_axis", "d"), ("normal_axis", []),
    ("short_distance", True), ("short_distance", "1.0"), ("short_distance", None),
    ("short_distance", 0.099), ("short_distance", 3.001), ("short_distance", []),
    ("reviewed", 1), ("reviewed", "false"), ("reviewed", None),
])
def test_invalid_entry_fields_are_rejected_on_load_and_save(field, invalid):
    value = document()
    value["entries"][0][field] = invalid
    with pytest.raises(ProjectError):
        loads_project(encode(value))
    original = sample_project()
    invalid_entry = replace(original.entries[0], **{field: invalid})
    with pytest.raises(ProjectError):
        dumps_project(replace(original, entries=[invalid_entry, original.entries[1]]))


@pytest.mark.parametrize("cutoff", [float("nan"), float("inf"), float("-inf"), 10 ** 1000])
def test_nonfinite_or_extreme_numeric_settings_are_rejected(cutoff):
    original = sample_project()
    invalid_entry = replace(original.entries[0], short_distance=cutoff)
    with pytest.raises(ProjectError, match="finite number"):
        dumps_project(replace(original, entries=[invalid_entry, original.entries[1]]))
    value = document()
    value["entries"][0]["short_distance"] = cutoff
    with pytest.raises(ProjectError):
        loads_project(encode(value))


@pytest.mark.parametrize("field,invalid", [
    ("review_focus", "unknown"), ("review_focus", []), ("filter_mode", "unknown"),
    ("progress_filter", "unknown"),
    ("selected_id", []), ("calclens_version", 2), ("ase_version", ""),
    ("ase_version", "x" * 81),
])
def test_invalid_project_state_and_tool_versions_are_rejected_on_load_and_save(field, invalid):
    original = replace(sample_project(), **{field: invalid})
    with pytest.raises(ProjectError):
        dumps_project(original)
    value = document()
    section = "tools" if field in ("calclens_version", "ase_version") else "state"
    value[section][field] = invalid
    with pytest.raises(ProjectError):
        loads_project(encode(value))


@pytest.mark.parametrize("data", ["{}", bytearray(b"{}"), None])
def test_input_must_be_json_bytes(data):
    with pytest.raises(ProjectError, match="UTF-8 JSON bytes"):
        loads_project(data)


@pytest.mark.parametrize("data", [b"", b"x" * (MAX_FILE_BYTES + 1), bytearray(b"data"), "data"])
def test_save_requires_bounded_original_bytes(data):
    with pytest.raises(ProjectError, match="original CIF bytes"):
        dumps_project(Project([ProjectEntry("one", "sample.cif", data)]))


def test_review_stamp_tracks_engine_inputs_but_not_ui_only_app_version():
    reviewed = mark_reviewed(ProjectEntry("one", "sample.cif", b"data"))
    assert review_is_current(reviewed)
    ui_version_changed = replace(
        reviewed,
        review_stamp=replace(reviewed.review_stamp, calclens_version="999.0-ui-only"),
    )
    assert review_is_current(ui_version_changed)

    for changed in (
        replace(reviewed, data=b"different"),
        replace(reviewed, normal_axis="a"),
        replace(reviewed, short_distance=2.0),
        replace(reviewed, review_stamp=replace(
            reviewed.review_stamp, analysis_revision="older-engine",
        )),
        replace(reviewed, review_stamp=replace(reviewed.review_stamp, ase_version="0.0")),
    ):
        refreshed = refresh_review(changed)
        assert refreshed.reviewed is False
        assert refreshed.review_stamp == changed.review_stamp


def test_pre_alias_fix_reviews_require_rechecking_but_keep_their_history():
    value = document()
    value["tools"]["analysis_revision"] = "geometry-v1"
    old_stamp = value["entries"][0]["review_stamp"]
    old_stamp["analysis_revision"] = "geometry-v1"
    reopened = loads_project(encode(value))
    entry = reopened.entries[0]
    assert entry.reviewed is False
    assert entry.review_stamp.analysis_revision == "geometry-v1"
    assert entry.review_stamp.sha256 == old_stamp["sha256"]
    assert entry.data == sample_project().entries[0].data
    assert entry.note == sample_project().entries[0].note
    assert review_is_current(mark_reviewed(entry))


def test_reviewed_without_current_stamp_is_rejected_on_save_and_cleared_on_load():
    unstamped = Project([ProjectEntry("one", "sample.cif", b"data", reviewed=True)])
    with pytest.raises(ProjectError, match="review stamp"):
        dumps_project(unstamped)

    value = document()
    value["entries"][0]["review_stamp"] = None
    reopened = loads_project(encode(value))
    assert reopened.entries[0].reviewed is False
    assert reopened.entries[0].review_stamp is None


def test_schema_one_review_migrates_to_unreviewed_legacy_evidence_without_washout():
    value = document()
    value["schema_version"] = 1
    del value["workspace_state"]
    del value["tools"]["analysis_revision"]
    del value["state"]["progress_filter"]
    for entry in value["entries"]:
        del entry["review_stamp"]
        del entry["measurements"]
        del entry["preparation"]
    assert value["entries"][0]["reviewed"] is True

    migrated = loads_project(encode(value))

    first = migrated.entries[0]
    assert first.reviewed is False
    assert first.review_stamp is not None
    assert first.review_stamp.analysis_revision is None
    assert first.review_stamp.sha256 == hashlib.sha256(first.data).hexdigest()
    assert migrated.progress_filter == "all"
    assert migrated.analysis_revision is None

    reopened = loads_project(dumps_project(migrated))
    assert reopened.entries[0].reviewed is False
    assert reopened.entries[0].review_stamp == first.review_stamp


def test_pair_selections_roundtrip_without_computed_distances_and_are_bounded():
    original = sample_project()
    encoded = dumps_project(original)
    value = json.loads(encoded)
    pair = value["entries"][0]["measurements"][0]
    assert set(pair) == {"i", "j", "first_shift", "second_shift", "mode"}
    assert "distance" not in json.dumps(pair)
    assert loads_project(encoded) == original

    value["entries"][0]["measurements"][0]["second_shift"] = [MAX_IMAGE_SHIFT + 1, 0, 0]
    with pytest.raises(ProjectError, match="image shifts"):
        loads_project(encode(value))

    value = document()
    value["entries"][0]["measurements"] = [
        {"i": 0, "j": 1, "first_shift": [0, 0, 0], "second_shift": [0, 0, 0],
         "mode": "minimum_image"}
    ] * (MAX_PAIR_SELECTIONS + 1)
    with pytest.raises(ProjectError, match="at most"):
        loads_project(encode(value))


def test_project_file_edits_are_atomic_and_preserve_unaffected_review_state():
    original = sample_project()
    addition = ProjectEntry("third", "new.cif", b"new data")
    added = add_entries(original, [addition])
    assert original.entries == sample_project().entries
    assert added.entries[-1] == addition

    reviewed = original.entries[0]
    renamed = replace_entry(original, reviewed.id, "renamed.cif", reviewed.data)
    assert renamed.entries[0].reviewed is True
    assert renamed.entries[0].review_stamp == reviewed.review_stamp
    assert renamed.entries[0].measurements == reviewed.measurements

    replaced_project = replace_entry(original, reviewed.id, "replacement.cif", b"replacement")
    replaced_entry = replaced_project.entries[0]
    assert replaced_entry.id == reviewed.id
    assert replaced_entry.note == reviewed.note
    assert replaced_entry.normal_axis == reviewed.normal_axis
    assert replaced_entry.reviewed is False
    assert replaced_entry.review_stamp == reviewed.review_stamp
    assert replaced_entry.measurements == ()

    removed = remove_entry(original, "second")
    assert [entry.id for entry in removed.entries] == ["first"]
    assert removed.selected_id == "first"
    with pytest.raises(ProjectError, match="at least one"):
        remove_entry(removed, "first")
    with pytest.raises(ProjectError, match="does not identify"):
        replace_entry(original, "missing", "x.cif", b"x")
    with pytest.raises(ProjectError, match="does not identify"):
        remove_entry(original, "missing")


def test_add_entries_rejects_duplicate_or_excess_files_without_mutating_source():
    original = sample_project()
    before = list(original.entries)
    with pytest.raises(ProjectError, match="IDs must be unique"):
        add_entries(original, [replace(original.entries[0], filename="duplicate.cif")])
    assert original.entries == before

    full = Project([
        ProjectEntry(str(index), f"{index}.cif", b"data")
        for index in range(MAX_PROJECT_FILES)
    ])
    with pytest.raises(ProjectError, match="between 1 and 20"):
        add_entries(full, [ProjectEntry("extra", "extra.cif", b"data")])


def test_pair_selection_requires_distinct_sites_on_save_and_load():
    original = sample_project()
    invalid = replace(original.entries[0], measurements=(PairSelection(0, 0),))
    with pytest.raises(ProjectError, match="distinct"):
        dumps_project(replace(original, entries=[invalid], selected_id=invalid.id))
    value = json.loads(dumps_project(original))
    value["entries"][0]["measurements"][0]["j"] = 0
    with pytest.raises(ProjectError, match="distinct"):
        loads_project(encode(value))
