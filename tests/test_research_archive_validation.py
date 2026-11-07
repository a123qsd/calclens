"""Native document validation accepts archived inputs and rejects altered records."""

from copy import deepcopy
from dataclasses import replace

import numpy as np
import pytest

from slab_preflight.density_records import replay_difference
from slab_preflight.desktop_research import ResearchPanel
from slab_preflight.project import dumps_project_archive, loads_project
from slab_preflight.web_api import Workspace
from test_density_records import CIF, ROOT, retained


@pytest.mark.parametrize("legacy", [False, True])
def test_blocked_current_slab_axis_still_accepts_retained_valid_p1_sources(legacy):
    project, _, bundle, _, original = retained(legacy=legacy)
    blocked = replace(project, entries=[replace(project.entries[0], normal_axis="a")])
    workspace = Workspace(ROOT)
    workspace.project = blocked
    snapshot = workspace.snapshot(include_workspace=True)
    entry = snapshot["entries"][0]
    assert entry["analysis"]["report"] is None
    assert entry["analysis"]["auxiliary_structure"]["atom_count"] == 2
    ResearchPanel.validate_state(blocked.workspace_state, [entry])
    replay = replay_difference(bundle, entry)
    np.testing.assert_array_equal(replay.grid.values, original.grid.values)
    restored = loads_project(dumps_project_archive(blocked))
    assert restored.entries[0].data == CIF and restored.entries[0].note == "Original memo · 메모"
    assert restored.workspace_state == blocked.workspace_state


@pytest.mark.parametrize("part", ["source", "result", "normal", "profile", "provenance", "version",
                                 "axis", "record", "array-hash", "limitations", "quadrature"])
def test_tampered_modern_archive_is_rejected_before_replacing_live_data(part):
    project, entry, _, _, _ = retained()
    state = deepcopy(project.workspace_state)
    digest = entry["sha256"]
    bundle = state["native_research"]["differences"][digest]["difference"]
    item = state["native_research"]["signed"][digest][0]
    if part == "source":
        bundle["sources"]["A"]["raw"] += "\n"
    elif part == "result":
        item["rawText"] += "\n"
    elif part == "normal":
        bundle["calculation"]["normal_vector"] = [1, 0, 0]
    elif part == "profile":
        bundle["computation"]["profile"]["average_e_per_angstrom3"][0] += 3
    elif part == "provenance":
        bundle["computation"]["provenance"]["common_method_declared"] = "Other method"
    elif part == "version":
        bundle["schema_version"] = True
    elif part == "axis":
        bundle["axis"] = True
    elif part == "array-hash":
        bundle["computation"]["grid"]["source_sha256"] = "f" * 64
    elif part == "limitations":
        bundle["computation"]["profile"]["limitations"] = ["Convergence proven by geometry"]
    elif part == "quadrature":
        bundle["computation"]["profile"]["quadrature"] = "Undeclared new integration rule"
    else:
        del bundle["computation"]
    with pytest.raises(ValueError):
        ResearchPanel.validate_state(state, [entry])


def test_partial_occupancy_and_missing_validated_geometry_are_still_rejected():
    project, entry, bundle, _, _ = retained()
    entry["analysis"] = {"report": None, "error": "Partial occupancy unsupported"}
    with pytest.raises(ValueError, match="supported CIF"):
        ResearchPanel.validate_state(project.workspace_state, [entry])
    with pytest.raises(ValueError, match="validated original P1"):
        replay_difference(bundle, entry)


def test_archived_axis_and_changed_draft_are_identified_without_reinterpreting_record(tmp_path):
    from PySide6.QtWidgets import QApplication
    from slab_preflight.desktop import MainWindow
    from slab_preflight.project import dumps_project_archive
    import time

    app = QApplication.instance() or QApplication([])
    project, _, _, _, _ = retained()
    path = tmp_path / "archive.calclens.zip"
    path.write_bytes(dumps_project_archive(project))
    window = MainWindow("en", root=ROOT, recovery=False)
    try:
        window.open_project(path, confirm=False)
        deadline = time.monotonic() + 8
        while window.is_busy and time.monotonic() < deadline:
            app.processEvents()
            time.sleep(.005)
        panel = window.research_panel
        assert "differs from current fragment" not in panel.archive_info.text()
        panel.method.setText("changed method")
        panel._store_draft()
        assert "differs from current fragment" in panel.archive_info.text()
        assert panel._archive()[0]["method"] == "Synthetic method declaration"
    finally:
        window.dirty = False
        window.close()
