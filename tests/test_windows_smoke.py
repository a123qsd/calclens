"""Pure checks for the Windows frozen-executable smoke harness."""

import importlib.util
import json
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location(
    "calclens_windows_smoke", ROOT / "scripts" / "smoke_windows_exe.py"
)
smoke = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(smoke)
WORKSPACE_SPEC = importlib.util.spec_from_file_location(
    "calclens_workspace_smoke", ROOT / "scripts" / "smoke_workspace.py"
)
workspace_smoke = importlib.util.module_from_spec(WORKSPACE_SPEC)
WORKSPACE_SPEC.loader.exec_module(workspace_smoke)


def test_descendant_process_ids_follows_bootloader_child_chain_only():
    parents = {
        100: 50,
        101: 100,  # onefile Python child
        102: 101,  # any descendant owned by that runtime
        200: 50,   # unrelated process with the same parent
        201: 200,
    }
    assert smoke.descendant_process_ids(100, parents) == {100, 101, 102}


def test_descendant_process_ids_ignores_unrooted_cycles_and_pid_like_values():
    parents = {
        "11": "10",
        12: 11,
        30: 31,
        31: 30,
        40: 999,
    }
    assert smoke.descendant_process_ids(10, parents) == {10, 11, 12}


def test_workspace_smoke_requires_schema_three_review_and_saved_pair():
    document = {
        "format": "calclens.project",
        "schema_version": 3,
        "tools": {"calclens_version": "0.4.0"},
        "entries": [
            {"filename": "graphene.cif"},
            {
                "filename": "mos2_a_normal.cif", "normal_axis": "a",
                "short_distance": 2.5, "note": workspace_smoke.NOTE,
                "reviewed": True, "review_stamp": {"sha256": "a" * 64},
                "measurements": [{
                    "i": 0, "j": 1, "mode": "minimum_image",
                    "first_shift": [0, 0, 0], "second_shift": [0, 0, 0],
                }],
            },
            {"filename": "partial_occupancy.cif"},
        ],
    }
    workspace_smoke._assert_project(document, "0.4.0")
    with pytest.raises(AssertionError, match="schema must be version 3"):
        workspace_smoke._assert_project({**document, "schema_version": 2}, "0.4.0")


def test_workspace_smoke_origin_normalizes_default_ports():
    assert workspace_smoke._origin("http://127.0.0.1/path") == ("http", "127.0.0.1", 80)
    assert workspace_smoke._origin("https://example.test:444/app") == (
        "https", "example.test", 444,
    )


def test_windows_smoke_uses_distinct_workspace_and_legacy_health_endpoints():
    assert smoke.health_endpoint() == "/_calclens/health"
    assert smoke.health_endpoint(legacy_ui=True) == "/_stcore/health"


def test_windows_smoke_requires_checks_for_the_declared_ui_variant():
    core = {name: True for name in smoke.SELF_TEST_CHECKS}
    smoke.verify_self_test_checks({"includes_legacy_ui": False, "checks": core})
    with pytest.raises(AssertionError, match="omitted required"):
        smoke.verify_self_test_checks({"includes_legacy_ui": True, "checks": core})
    smoke.verify_self_test_checks({"includes_legacy_ui": True,
                                  "checks": core | dict.fromkeys(smoke.LEGACY_SELF_TEST_CHECKS, True)})
    with pytest.raises(AssertionError, match="imported legacy"):
        smoke.verify_self_test_checks({"includes_legacy_ui": False, "checks": core,
                                       "module_origins": {"plotly": "unexpected"}})


def test_legacy_project_download_uses_the_current_serializer_contract(tmp_path):
    from slab_preflight.project import Project, ProjectEntry, SCHEMA_VERSION, dumps_project

    path = tmp_path / "legacy.calclens.json"
    path.write_bytes(dumps_project(Project([
        ProjectEntry("water", "water.cif", (ROOT / "examples/electronic_case/water.cif").read_bytes()),
    ])))
    document = smoke.read_legacy_project_document(path)
    assert document["schema_version"] == SCHEMA_VERSION
    assert document["workspace_state"] == {}


@pytest.mark.parametrize("schema", [1, 2, 999, True, 3.0, "3", None])
def test_legacy_project_download_rejects_mismatched_or_noninteger_schema(tmp_path, schema):
    from slab_preflight.project import PROJECT_FORMAT

    path = tmp_path / "wrong-schema.json"
    path.write_text(json.dumps({"format": PROJECT_FORMAT, "schema_version": schema}))
    with pytest.raises(AssertionError, match="format/schema"):
        smoke.read_legacy_project_document(path)


def test_legacy_project_download_rejects_a_foreign_format(tmp_path):
    from slab_preflight.project import SCHEMA_VERSION

    path = tmp_path / "wrong-format.json"
    path.write_text(json.dumps({"format": "other.project", "schema_version": SCHEMA_VERSION}))
    with pytest.raises(AssertionError, match="format/schema"):
        smoke.read_legacy_project_document(path)
