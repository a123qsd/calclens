"""Original-output import → native geometry comparison → saved-project roundtrip."""
import base64
from copy import deepcopy
from hashlib import sha256
import os
from pathlib import Path

import numpy as np
import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
from PySide6.QtWidgets import QApplication
from PySide6.QtGui import QImage
import json

from slab_preflight.desktop import MainWindow
from slab_preflight.project import loads_project

ROOT = Path(__file__).resolve().parents[1]
VASP = ROOT / "examples/research_cases/vasp_reference/OUTCAR_Ni_reference"
GAUSSIAN = ROOT / "examples/research_cases/gaussian_reference"


@pytest.fixture(scope="module")
def app():
    return QApplication.instance() or QApplication([])


@pytest.fixture
def window(app, monkeypatch):
    monkeypatch.setattr("slab_preflight.desktop_devices.DeviceControls.ensure_local_probe", lambda _self: None)
    win = MainWindow("en", root=ROOT, recovery=False)
    errors = []
    win.show_error = lambda error: errors.append(str(error))

    def immediate(fn, after=None, **_kwargs):
        try:
            result = fn()
            return after(result) if after else None
        except Exception as exc:
            win.show_error(exc)

    win.submit = immediate
    win.show()
    app.processEvents()
    yield win, errors
    if win._comparison_dialog:
        win._comparison_dialog.close()
    win.dirty = False
    win.close()
    app.processEvents()


def test_outcar_and_gaussian_are_reachable_from_log_page_and_compare_native_geometry(window, app):
    win, errors = window
    panel = win.research_panel
    panel.import_log(VASP)
    assert panel.log_compare.isEnabled()
    assert "free_energy_TOTEN" in panel.log_info.toPlainText()
    assert "energy_sigma_to_zero" in panel.log_info.toPlainText()
    panel.log_compare.click()
    app.processEvents()
    dialog = win._comparison_dialog
    assert dialog and dialog.panes[1]["view"].report["formula"] == "Ni18"
    assert dialog.panes[1]["view"].report["cell"] is not None
    outcar_id = dialog.panes[1]["file"].currentData()
    dialog.select_output(outcar_id, side=0)
    assert dialog.coordinate_comparison["status"] == "unavailable"
    dialog.correspondence.setChecked(True)
    dialog.coordinate_mode.setCurrentIndex(dialog.coordinate_mode.findData("minimum_image"))
    assert dialog.coordinate_comparison["rmsd"] == pytest.approx(0)
    assert dialog.energy_comparison["status"] == "unavailable"
    dialog.conditions_reviewed.setChecked(True)
    assert dialog.energy_comparison["delta"] == 0
    panel.import_log(GAUSSIAN / "dvb_gopt.out")
    assert panel.log_history.count() == 2
    panel.log_compare.click()
    app.processEvents()
    molecular_id = dialog.panes[1]["file"].currentData()
    report = dialog.panes[1]["view"].report
    assert report["formula"] == "C10H10" and report["cell"] is None
    assert not dialog.panes[1]["view"].has_cell
    assert not dialog.correspondence.isChecked() and not dialog.conditions_reviewed.isChecked()
    dialog.select_output(molecular_id, side=0)
    dialog.correspondence.setChecked(True)
    dialog.coordinate_mode.setCurrentIndex(dialog.coordinate_mode.findData("rigid"))
    assert dialog.coordinate_comparison["rmsd"] < 1e-12
    image = dialog.panes[1]["view"].grab()
    assert not image.isNull()
    assert not errors


def test_original_outputs_job_selection_and_comparison_conditions_survive_project_roundtrip(window, tmp_path, app):
    win, errors = window
    panel = win.research_panel
    for source in (VASP, GAUSSIAN / "dvb_gopt.out", GAUSSIAN / "dvb_ir.out"):
        panel.import_log(source)
    dialog = win.compare_structures()
    molecular_entries = [e for e in panel.output_entries() if e["output"]["program"]["name"] == "Gaussian"]
    assert len(molecular_entries) == 2
    for side, entry in enumerate(molecular_entries):
        dialog.select_output(entry["id"], side=side)
    dialog.coordinate_mode.setCurrentIndex(dialog.coordinate_mode.findData("rigid"))
    dialog.correspondence.setChecked(True)
    assert dialog.coordinate_comparison["rmsd"] < 1e-6
    original_positions = deepcopy(dialog.panes[1]["view"].report["positions"])
    saved = tmp_path / "result-comparison.calclens.zip"
    win.save_project(path=saved)
    state = loads_project(saved.read_bytes()).workspace_state
    records = state["native_research"]["logs"]
    assert len(records) == 3
    for record in records:
        assert sha256(base64.b64decode(record["data"])).hexdigest() == record["sha256"]
    assert state["native_comparison"]["coordinate_mode"] == "rigid"
    assert state["native_comparison"]["correspondence"] is True
    dialog.close()
    app.processEvents()
    win.open_project(saved, confirm=False)
    restored = win.compare_structures()
    assert restored.coordinate_mode.currentData() == "rigid"
    assert restored.correspondence.isChecked()
    assert restored.coordinate_comparison["rmsd"] < 1e-6
    np.testing.assert_allclose(restored.panes[1]["view"].report["positions"], original_positions)
    assert len(win.research_panel.output_entries()) == 3
    assert not errors


def test_failed_output_import_and_tampered_saved_original_preserve_existing_workspace(window, tmp_path):
    win, errors = window
    panel = win.research_panel
    panel.import_log(VASP)
    original_native = deepcopy(panel.native)
    bad = tmp_path / "unknown.log"
    bad.write_text("unrecognized fake success and arbitrary energy=-100")
    panel.import_log(bad)
    assert panel.native == original_native and errors
    errors.clear()
    project, revision = win.workspace.project, win.workspace.revision
    state = win.portable_state()
    state["native_research"]["logs"][0]["data"] = base64.b64encode(b"modified original").decode()
    tampered = tmp_path / "tampered.calclens.zip"
    tampered.write_bytes(win.workspace.export_workspace({"expected_revision": revision, "workspace_state": state}))
    win.open_project(tampered, confirm=False)
    assert win.workspace.project == project and win.workspace.revision == revision
    assert "checksum" in errors[-1]


def test_legacy_single_saved_gaussian_log_still_gains_native_comparison_geometry(window, tmp_path):
    win, errors = window
    panel = win.research_panel
    panel.import_log(GAUSSIAN / "dvb_gopt.out")
    state = win.portable_state()
    del state["native_research"]["logs"]
    legacy = tmp_path / "legacy-single-log.calclens.zip"
    legacy.write_bytes(win.workspace.export_workspace({"expected_revision": win.workspace.revision,
                                                       "workspace_state": state}))
    win.open_project(legacy, confirm=False)
    assert len(win.research_panel.output_entries()) == 1
    win.research_panel.log_compare.click()
    assert win._comparison_dialog.panes[1]["view"].report["cell"] is None
    assert not errors


def test_output_publication_export_carries_exact_source_and_selected_job(window, tmp_path, monkeypatch):
    win, errors = window
    panel = win.research_panel
    panel.import_log(GAUSSIAN / "dvb_gopt.out")
    panel.log_compare.click()
    pane = win._comparison_dialog.panes[1]
    captured = []
    original_export = win.export_publication
    monkeypatch.setattr(win, "export_publication", lambda **kwargs: captured.append(kwargs))
    pane["figure"].click()
    assert captured == [{"view": pane["view"]}]
    target = tmp_path / "gaussian-job-figure.png"
    assert original_export(view=pane["view"], path=target, width_mm=85, dpi=300)
    record = json.loads(QImage(str(target)).text("CalcLens provenance"))
    source = record["source"]
    assert source["source_filename"] == "dvb_gopt.out"
    assert source["source_sha256"] == sha256((GAUSSIAN / "dvb_gopt.out").read_bytes()).hexdigest()
    assert source["job_index"] == 1
    assert source["geometry_line_end"] > source["geometry_line_start"] > 0
    assert source["coordinate_units"] == "angstrom" and source["program"]["name"] == "Gaussian"
    assert not errors


def test_large_output_is_preserved_without_entering_quadratic_native_rendering(window, tmp_path):
    win, errors = window
    path = tmp_path / "synthetic-401-atoms.log"
    atom_rows = "\n".join(f" {i+1} 1 0 {i}.0 0.0 0.0" for i in range(401))
    path.write_text("Gaussian 16\n # HF/STO-3G\n ------\n NAtoms=401\n Standard orientation:\n"
                    " -----\n Center Atomic Atomic Coordinates (Angstroms)\n Number Number Type X Y Z\n"
                    f" -----\n{atom_rows}\n -----\n Normal termination of Gaussian 16.\n")
    panel = win.research_panel
    panel.import_log(path)
    assert len(panel._log["steps"][0]["final_geometry"]["positions"]) == 401
    assert "400" in panel.log_info.toPlainText()
    panel.log_compare.click()
    pane = win._comparison_dialog.panes[1]
    assert pane["view"].report is None and len(pane["view"].positions) == 0
    assert "400" in pane["info"].text() and not pane["figure"].isEnabled()
    assert base64.b64decode(panel.native["log"]["data"]) == path.read_bytes()
    assert not errors


def test_open_comparison_resets_source_confirmations_when_project_replacement_falls_back(window, app):
    win, errors = window
    panel = win.research_panel
    panel.example_vasp_log()
    dialog = win.compare_structures()
    output_id = panel.output_entries()[0]["id"]
    for side in range(2):
        dialog.select_output(output_id, side=side)
    dialog.correspondence.setChecked(True)
    dialog.conditions_reviewed.setChecked(True)
    assert dialog.coordinate_comparison["rmsd"] == 0
    assert dialog.energy_comparison["status"] == "available"
    original_pair = dialog.portable_state()["pair_identity"]
    # An unrelated imported source does not invalidate the unchanged pair.
    panel.import_log(GAUSSIAN / "dvb_gopt.out")
    assert dialog.portable_state()["pair_identity"] == original_pair
    assert dialog.correspondence.isChecked() and dialog.conditions_reviewed.isChecked()
    win.open_project(ROOT / "examples/electronic_case/real-water.calclens.zip", confirm=False)
    app.processEvents()
    assert win._comparison_dialog is dialog
    assert dialog.portable_state()["pair_identity"] != original_pair
    assert not dialog.correspondence.isChecked() and not dialog.conditions_reviewed.isChecked()
    assert dialog.coordinate_comparison["status"] == "unavailable"
    assert dialog.energy_comparison["status"] == "unavailable"
    assert all(pane["file"].findData(output_id) < 0 for pane in dialog.panes)
    assert not errors


def test_same_entry_id_and_hash_cannot_keep_confirmation_after_geometry_content_changes(window):
    win, errors = window
    dialog = win.compare_structures()
    dialog.correspondence.setChecked(True)
    dialog.conditions_reviewed.setChecked(True)
    original_pair = dialog.portable_state()["pair_identity"]
    replacement = deepcopy(win.snapshot)
    replacement["entries"][0]["analysis"]["report"]["positions"][0][0] += 0.125
    dialog.refresh_entries(replacement)
    assert dialog.portable_state()["pair_identity"] != original_pair
    assert not dialog.correspondence.isChecked() and not dialog.conditions_reviewed.isChecked()
    assert dialog.coordinate_comparison["status"] == "unavailable"
    assert not errors


def test_selected_concatenated_job_carries_its_own_version_into_view_provenance(window, tmp_path):
    win, errors = window
    original = VASP.read_bytes()
    path = tmp_path / "synthetic-mixed-versions.OUTCAR"
    path.write_bytes(original + b"\n" + original.replace(b"vasp.5.3.3", b"vasp.6.4.3"))
    panel = win.research_panel
    panel.import_log(path)
    assert "6.4.3" in panel.log_info.toPlainText()
    panel.log_geometry.setCurrentIndex(1)
    panel.log_compare.click()
    view = win._comparison_dialog.panes[1]["view"]
    assert view.metadata["program"]["version"] == "6.4.3"
    assert view.metadata["job_index"] == 2
    assert view.metadata["source_sha256"] == sha256(path.read_bytes()).hexdigest()
    assert not errors
