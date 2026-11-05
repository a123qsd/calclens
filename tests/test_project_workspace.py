"""Portable workspace extensions and archive import fail closed."""
from dataclasses import replace
from io import BytesIO
import json
from pathlib import Path
import stat
import struct
import zipfile

import pytest

from slab_preflight import project as module
from slab_preflight.project import (
    Project, ProjectEntry, ProjectError, dumps_project, dumps_project_archive,
    loads_project, loads_project_archive, validate_workspace_state,
)

ROOT = Path(__file__).resolve().parents[1]


def project(state=None):
    return Project([ProjectEntry("cif", "graphene.cif", (ROOT / "examples/graphene.cif").read_bytes())],
                   selected_id="cif", workspace_state={} if state is None else state)


def archive(payload, name="project.json", *, compression=zipfile.ZIP_STORED, second=None,
            mode=None):
    stream = BytesIO()
    with zipfile.ZipFile(stream, "w", compression=compression) as value:
        member = zipfile.ZipInfo(name)
        member.compress_type = compression
        if mode is not None:
            member.create_system = 3
            member.external_attr = mode << 16
        value.writestr(member, payload)
        if second is not None:
            value.writestr(second, payload)
    return stream.getvalue()


def test_full_workspace_raw_data_settings_camera_and_drafts_roundtrip_exactly():
    original = project({
        "schema_version": 1,
        "auxiliary": {"a" * 64: {"cube": {"filename": "density.cube", "raw": "density\n" + "0.1 0.2\n" * 30_000},
                                  "bands": {"filename": "bands.json", "raw": '{"energy":[-1,0,1]}'}}},
        "viewers": {"before:cif:" + "a" * 64: {"camera": {"position": [1, 2, 3], "zoom": 1.25}}},
        "drafts": {"cif": {"note": "메모\n原本", "cutoff": 1.2}},
        "comparison": {"before": "cif", "after": "cif", "sync": True},
    })
    encoded = dumps_project(original)
    assert json.loads(encoded)["schema_version"] == 3
    assert loads_project(encoded) == original
    zipped = dumps_project_archive(original)
    assert zipped == dumps_project_archive(original)
    assert len(zipped) < len(encoded) / 10
    assert loads_project(zipped) == original
    with zipfile.ZipFile(BytesIO(zipped)) as opened:
        assert opened.namelist() == ["project.json"]
        assert opened.read("project.json") == encoded


def test_schema_two_loads_without_extension_or_transformation_and_resaves_schema_three():
    value = json.loads(dumps_project(project()))
    value["schema_version"] = 2
    del value["workspace_state"]
    for entry in value["entries"]:
        del entry["preparation"]
    loaded = loads_project(json.dumps(value).encode())
    assert loaded.workspace_state == {}
    assert loaded.entries[0].preparation is None
    assert json.loads(dumps_project(loaded))["schema_version"] == 3


@pytest.mark.parametrize("state", [None, [], "state", {"value": float("inf")},
                                  {"value": float("nan")}, {"value": 2**53},
                                  {"value": (1, 2)}, {"value": object()},
                                  {"value": "\ud800"}, {1: "nontext-key"}])
def test_opaque_state_is_still_bounded_finite_json(state):
    with pytest.raises(ProjectError):
        validate_workspace_state(state)


def test_workspace_state_depth_width_and_serialized_byte_caps(monkeypatch):
    state = {}
    for _ in range(20):
        state = {"child": state}
    with pytest.raises(ProjectError, match="deep"):
        dumps_project(project(state))
    monkeypatch.setattr(module, "MAX_WORKSPACE_NODES", 10)
    with pytest.raises(ProjectError, match="too many"):
        validate_workspace_state({"rows": list(range(20))})
    monkeypatch.setattr(module, "MAX_WORKSPACE_BYTES", 20)
    with pytest.raises(ProjectError, match="size limit|byte limit"):
        validate_workspace_state({"raw": "x" * 21})
    with pytest.raises(ProjectError, match="byte limit"):
        validate_workspace_state({"x": "a" * 8, "y": "b" * 8})


@pytest.mark.parametrize("name", ["../project.json", "/project.json", "folder/project.json",
                                   "project.json/", "PROJECT.JSON", "other.json", "project\\json"])
def test_archive_only_permits_exact_project_json_name(name):
    with pytest.raises(ProjectError):
        loads_project(archive(dumps_project(project()), name))


def test_duplicate_and_extra_zip_members_are_rejected_before_directory_allocation(monkeypatch):
    payload = dumps_project(project())
    with pytest.warns(UserWarning, match="Duplicate name"):
        duplicate = archive(payload, second="project.json")
    values = [duplicate, archive(payload, second="extra.txt")]
    monkeypatch.setattr(module.zipfile, "ZipFile", lambda *a, **k: pytest.fail("parsed directory"))
    for value in values:
        with pytest.raises(ProjectError, match="exactly one"):
            loads_project(value)


def test_zip_size_caps_are_checked_before_decompression_and_json_parsing(monkeypatch):
    value = archive(dumps_project(project()), compression=zipfile.ZIP_DEFLATED)
    monkeypatch.setattr(module, "MAX_PROJECT_BYTES", 100)
    monkeypatch.setattr(module.json, "loads", lambda *a, **k: pytest.fail("parsed JSON"))
    with pytest.raises(ProjectError, match="Expanded.*limit"):
        loads_project(value)
    monkeypatch.setattr(module, "MAX_ARCHIVE_BYTES", 20)
    monkeypatch.setattr(module.zipfile, "ZipFile", lambda *a, **k: pytest.fail("parsed archive"))
    with pytest.raises(ProjectError, match="ZIP exceeds"):
        loads_project(value)


def test_corrupt_crc_truncated_and_nested_archives_are_rejected():
    value = bytearray(archive(dumps_project(project())))
    # Stored entry starts after the fixed 30-byte header plus its filename.
    value[30 + len("project.json") + 4] ^= 1
    with pytest.raises(ProjectError, match="corrupt"):
        loads_project(bytes(value))
    for invalid in (bytes(value)[:-1], b"PKbad", archive(dumps_project_archive(project()))):
        with pytest.raises(ProjectError):
            loads_project(invalid)


def test_archive_rejects_links_encryption_and_unsupported_compression():
    payload = dumps_project(project())
    with pytest.raises(ProjectError, match="regular"):
        loads_project(archive(payload, mode=stat.S_IFLNK | 0o777))
    with pytest.raises(ProjectError, match="regular"):
        loads_project(archive(payload, mode=stat.S_IFDIR | 0o700))
    with pytest.raises(ProjectError, match="regular"):
        loads_project(archive(payload, compression=zipfile.ZIP_BZIP2))
    value = bytearray(archive(payload))
    central = value.index(b"PK\x01\x02")
    struct.pack_into("<H", value, 6, 1)
    struct.pack_into("<H", value, central + 8, 1)
    with pytest.raises(ProjectError, match="unencrypted"):
        loads_project(bytes(value))


def test_forged_central_directory_size_is_bounded_before_zipfile_parse(monkeypatch):
    value = bytearray(archive(dumps_project(project())))
    eocd = len(value) - 22
    struct.pack_into("<L", value, eocd + 12, 200_000)
    monkeypatch.setattr(module.zipfile, "ZipFile", lambda *a, **k: pytest.fail("parsed directory"))
    with pytest.raises(ProjectError):
        loads_project(bytes(value))


def test_original_preparation_source_and_all_hashes_survive_archive_roundtrip():
    from slab_preflight.web_api import Workspace
    from base64 import b64encode, b64decode
    workspace = Workspace(ROOT)
    source = (ROOT / "examples/public_case/source/9011577-rev291877.cif").read_bytes()
    workspace.apply(0, {"type": "import_cifs", "mode": "replace", "files": [{
        "filename": "source.cif", "data_base64": b64encode(source).decode(),
    }]})
    entry = workspace.project.entries[0]
    preview = workspace.preview_p1({"expected_revision": 1, "entry_id": entry.id})
    workspace.apply(1, {"type": "prepare_p1", "id": entry.id,
                        "source_sha256": preview["source_sha256"]})
    prepared = workspace.project
    restored = loads_project(dumps_project_archive(prepared))
    record = restored.entries[0].preparation
    assert restored == prepared
    assert b64decode(record["source"]["cif_base64"]) == source
    assert record["source_sha256"] == preview["source_sha256"]
    assert record["prepared_sha256"] == preview["prepared_sha256"]
    assert record["source_site_count"] == 2
    assert record["prepared_site_count"] == 4
    for field in ("source_sha256", "prepared_sha256"):
        bad = {**record, field: "0" * 64}
        candidate = replace(restored, entries=[replace(restored.entries[0], preparation=bad)])
        with pytest.raises(ProjectError, match="hashes"):
            dumps_project(candidate)
    from slab_preflight.project import replace_entry
    changed = replace_entry(restored, entry.id, "replacement.cif", b"different source")
    assert changed.entries[0].preparation is None
    same = replace_entry(restored, entry.id, "renamed.cif", restored.entries[0].data)
    assert same.entries[0].preparation == record
    # A matching hash chain alone cannot authenticate invented scientific history.
    tampered = json.loads(dumps_project(restored))
    tampered["entries"][0]["preparation"]["source_site_count"] = 399
    with pytest.raises(ProjectError, match="source_site_count.*disagrees"):
        loads_project(json.dumps(tampered).encode())
    tampered = json.loads(dumps_project(restored))
    tampered["entries"][0]["preparation"]["ase_version"] = "historical-version"
    assert loads_project(json.dumps(tampered).encode()).entries[0].data == restored.entries[0].data


def test_standalone_archive_loader_refuses_json_instead_of_loosening_contract():
    with pytest.raises(ProjectError):
        loads_project_archive(dumps_project(project()))
