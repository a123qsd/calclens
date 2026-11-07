"""Native research tools use original sources and preserve projects after failed imports."""

import base64
from copy import deepcopy
from hashlib import sha256
import json
import os
from pathlib import Path

import numpy as np
import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
from PySide6.QtWidgets import QApplication
from slab_preflight.desktop import MainWindow
from slab_preflight.desktop_sources import pack_series, read_saved_series
from slab_preflight.density import parse_cube
from slab_preflight.native_fields import isosurfaces, parse_charge
from slab_preflight.project import loads_project

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture(scope="module")
def app():
    return QApplication.instance() or QApplication([])


@pytest.fixture
def window(app):
    window = MainWindow("en", root=ROOT, recovery=False)
    window.show()
    # Execute jobs immediately for deterministic model/UI round trip; native thread
    # cancellation and stale callbacks are exercised separately in the window suite.
    errors = []

    def immediate(fn, after=None, **kwargs):
        try:
            result = fn()
        except Exception as exc:
            window.show_error(str(exc))
            return None
        return after(result) if after else None

    window.submit = immediate
    window.show_error = lambda e: errors.append(str(e))
    yield window, errors
    window.dirty = False
    window.close()
    app.processEvents()


def test_real_v08_water_fields_reparse_and_restore_matching_units_and_legend(window):
    win, errors = window
    path = ROOT / "examples/electronic_case/real-water.calclens.zip"
    win.open_project(path, confirm=False)
    panel = win.research_panel
    assert panel is not None and len(panel.dataset_choices(win.selected_entry)["charges"]) == 2
    assert win.view.charges is not None and len(win.view.charges) == 3
    assert panel.unit_label.text() == "e/angstrom^3"
    panel.level.setValue(0.05)
    panel.draw_surface()
    assert win.view.surfaces and win.view.surface_metadata["isovalue"] == 0.05
    assert win.view.surface_metadata["source_sha256"]
    original = loads_project(path.read_bytes()).workspace_state
    state = win.portable_state()
    assert state["auxiliary"] == original["auxiliary"]
    assert state["comparison"] == original["comparison"]
    assert not errors


def test_native_gaussian_and_hbn_sources_survive_save_and_reopen(window, tmp_path):
    win, errors = window
    p = win.research_panel
    p.example_log()
    p.example_series()
    assert "Gaussian" in p.log_info.toPlainText() and "meV/atom" in p.series_info.toPlainText()
    assert p._series["status"] == "accepted" and p._log["status"] == "normal"
    raw = base64.b64decode(p.native["log"]["data"])
    assert sha256(raw).hexdigest() == p._log["provenance"]["sha256"]
    saved = tmp_path / "research.calclens.zip"
    win.save_project(path=saved)
    win.open_project(saved, confirm=False)
    assert win.research_panel._series["reference_id"] == "vacuum_16A"
    assert win.research_panel._log["provenance"]["sha256"] == sha256(raw).hexdigest()
    assert not errors


def test_chgcar_selected_field_keeps_raw_bytes_and_profile_after_archive_reopen(window, tmp_path):
    win, errors = window
    report = win.selected_entry["analysis"]["report"]
    lines = ["Graphene test grid", "1", *(" ".join(map(str, row)) for row in report["cell"]),
             "C", "2", "Cartesian", *(" ".join(map(str, row)) for row in report["positions"]),
             "", "2 2 2", "1 2 3 4 5 6 7 8"]
    raw = ("\r\n".join(lines) + "\r\n").encode()
    path = tmp_path / "CHGCAR"
    path.write_bytes(raw)
    win.research_panel.import_chgcar(path)
    uid = win.research_panel.volume.currentData()
    project = tmp_path / "chgcar.calclens.zip"
    win.save_project(path=project)
    win.open_project(project, confirm=False)
    panel = win.research_panel
    item = panel._source("volume", uid)
    assert panel.volume.currentData() == uid and item["rawText"].encode() == raw
    field = panel._decode("volume", item)
    assert field.source_sha256 == sha256(raw).hexdigest()
    assert field.values.sum() * abs(np.linalg.det(field.voxel_vectors_angstrom)) == pytest.approx(4.5)
    assert not errors


def test_compromised_series_file_cannot_change_workspace(window, tmp_path):
    win, errors = window
    p = win.research_panel
    p.example_series()
    orig = win.workspace.project
    revision = win.workspace.revision
    state = deepcopy(win.portable_state())
    state["native_research"]["series"]["files"]["../outside"] = base64.b64encode(b"bad").decode()
    archive = win.workspace.export_workspace(
        {"expected_revision": revision, "workspace_state": state}
    )
    bad = tmp_path / "bad.zip"
    bad.write_bytes(archive)
    win.open_project(bad, confirm=False)
    assert win.workspace.project == orig and win.workspace.revision == revision
    assert errors


def test_periodic_distance_button_returns_real_rows(window):
    win, errors = window
    p = win.research_panel
    p.device.setCurrentIndex(p.device.findData("cpu"))
    p.calculate_pairs()
    assert p._pairs["pair_count"] == 1 and p.pair_save.isEnabled()
    assert p._pairs["pairs"][0]["distance_angstrom"] == pytest.approx(
        win.selected_entry["analysis"]["report"]["metrics"]["minimum_distance_angstrom"]
    )
    assert not errors


def test_planar_mesh_uses_cartesian_voxel_basis_and_all_triangles_are_on_isovalue():
    text = "CalcLens test\nlinear scalar field\n1 0 0 0\n-2 2 0 0\n-2 0 3 0\n-2 0 0 4\n1 1 0 0 0\n0 0 0 0 1 1 1 1\n"
    grid = parse_cube(text, kind="density", units="e/angstrom^3")
    (mesh,) = isosurfaces(grid, 0.5)
    triangles = mesh["vertices"][mesh["faces"]]
    np.testing.assert_allclose(triangles[:, :, 0], 1)
    total = (
        np.linalg.norm(
            np.cross(triangles[:, 1] - triangles[:, 0], triangles[:, 2] - triangles[:, 0]), axis=1
        ).sum()
        / 2
    )
    assert total == pytest.approx(12)


def test_charge_import_preserves_unknown_and_requires_matching_hash_and_atom_order():
    shape = {"atom_count": 2, "elements": ["C", "H"]}
    digest = "a" * 64
    data = {
        "schema_version": 1,
        "structure_sha256": digest,
        "kind": "partial_charge",
        "method": "Mulliken",
        "source": "test",
        "atoms": [
            {"index": 1, "element": "C", "value": -0.4},
            {"index": 2, "element": "H", "value": None},
        ],
    }
    values, meta = parse_charge(json.dumps(data).encode(), shape, digest)
    assert values == [-0.4, None] and meta["units"] == "e"
    data["atoms"][1]["element"] = "O"
    with pytest.raises(ValueError, match="Element"):
        parse_charge(json.dumps(data).encode(), shape, digest)
    with pytest.raises(ValueError, match="SHA-256"):
        parse_charge(json.dumps(data).encode(), shape, "b" * 64)


def test_series_uses_only_embedded_originals_after_moving_project():
    bundle, report = pack_series(ROOT / "examples/research_cases/hbn_vacuum/series.json")
    assert read_saved_series(bundle)["comparisons"] == report["comparisons"]
    bundle["files"]["vacuum_08A.log"] = base64.b64encode(b" changed").decode()
    with pytest.raises(ValueError):
        read_saved_series(bundle)
