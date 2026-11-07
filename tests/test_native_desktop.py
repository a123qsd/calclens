"""Exercise the actual native desktop's user-facing operations and Qt renderer."""
import json
import os
from pathlib import Path
import threading
import time

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
pytest.importorskip("PySide6")

from PySide6.QtCore import QPoint, QPointF, QThread, Qt
from PySide6.QtGui import QFileOpenEvent, QImage, QWheelEvent
from PySide6.QtTest import QSignalSpy, QTest
from PySide6.QtWidgets import QApplication, QDialog, QMessageBox

from slab_preflight.core import analyze_cif
from slab_preflight.desktop import MainWindow
from slab_preflight.desktop_view import StructureView
from slab_preflight.project import loads_project
from slab_preflight.recovery import RecoveryStore


ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture(scope="module")
def application():
    app = QApplication.instance() or QApplication([])
    yield app


def finish_jobs(window, application, timeout=8):
    until = time.monotonic() + timeout
    while window.is_busy and time.monotonic() < until:
        application.processEvents()
        QTest.qWait(5)
    application.processEvents()
    assert not window.is_busy, "A native background operation did not finish."


@pytest.fixture
def window(application):
    widget = MainWindow(language="en", root=ROOT, recovery=False, research_factory=False)
    widget.show()
    application.processEvents()
    yield widget
    finish_jobs(widget, application)
    widget.dirty = False
    widget.close()
    widget.deleteLater()
    application.processEvents()


def test_landing_is_a_real_native_window_with_working_example(window):
    assert window.selected_entry["filename"] == "graphene.cif"
    assert window.view.report["atom_count"] == 2
    assert window.file_list.count() == 1
    assert "1.420" in window.metric_labels[0].text()
    assert window.tabs.tabText(0) == "Structure"
    assert window.view.grab().width() > 300
    assert window.dirty is False


def test_language_switch_rebuilds_native_controls_and_preserves_draft(window, application):
    window.note_edit.setPlainText("Draft retained across languages")
    window.language_combo.setCurrentIndex(0)
    application.processEvents()
    assert window.language == "ko"
    assert window.tabs.tabText(0) == "구조"
    assert window.open_button.text() == "CIF 열기"
    assert window.note_edit.toPlainText() == "Draft retained across languages"
    assert window.view.report["atom_count"] == 2


def test_open_multiple_cifs_and_switching_preserves_unapplied_drafts(window, application):
    window.open_cifs([ROOT / "examples/hbn.cif", ROOT / "examples/mos2.cif"])
    finish_jobs(window, application)
    assert window.file_list.count() == 3
    assert window.selected_entry["filename"] == "hbn.cif"
    original_id = window.selected_entry["id"]
    window.note_edit.setPlainText("Keep this unapplied note")
    other_id = window.snapshot["entries"][-1]["id"]
    window.select_entry(other_id)
    finish_jobs(window, application)
    assert window.view.report["formula"] == "MoS2"
    window.select_entry(original_id)
    finish_jobs(window, application)
    assert window.note_edit.toPlainText() == "Keep this unapplied note"
    assert window.selected_entry["note"] == ""
    assert window.dirty


def test_apply_settings_review_and_condition_change_invalidate_review(window, application):
    window.note_edit.setPlainText("Checked periodic distances")
    window.cutoff_spin.setValue(1.5)
    QTest.mouseClick(window.apply_button, Qt.MouseButton.LeftButton)
    finish_jobs(window, application)
    assert window.selected_entry["short_distance"] == 1.5
    assert window.selected_entry["note"] == "Checked periodic distances"
    window.review_check.setChecked(True)
    finish_jobs(window, application)
    assert window.selected_entry["review_current"] is True
    window.cutoff_spin.setValue(1.0)
    window.apply_settings()
    finish_jobs(window, application)
    assert window.selected_entry["review_current"] is False


def test_edit_while_analysis_runs_does_not_erase_the_newer_unapplied_draft(window, application, monkeypatch):
    started, release = threading.Event(), threading.Event()
    real_apply = window.workspace.apply

    def delayed_apply(*args):
        started.set()
        assert release.wait(3)
        return real_apply(*args)

    monkeypatch.setattr(window.workspace, "apply", delayed_apply)
    window.note_edit.setPlainText("Applied version")
    window.apply_settings()
    assert started.wait(1)
    window.note_edit.setPlainText("Newer unapplied draft")
    release.set()
    finish_jobs(window, application)
    assert window.selected_entry["note"] == "Applied version"
    assert window.note_edit.toPlainText() == "Newer unapplied draft"
    assert window.portable_state()["native_desktop"]["drafts"][window.selected_entry["id"]]["note"] == "Newer unapplied draft"


def test_pair_measurement_uses_exact_periodic_image_and_can_be_saved(window, application):
    window.measure_pair()
    finish_jobs(window, application)
    assert "1.420282" in window.measurement_label.text()
    contact = window.view.selected_contact
    assert contact["distance_kind"] == "minimum_image"
    assert contact["distance_angstrom"] == pytest.approx(2.46 / 3 ** 0.5)
    window.save_measurement()
    finish_jobs(window, application)
    assert len(window.selected_entry["measurements"]) == 1
    assert window.saved_measurements.count() == 1


def test_changing_measurement_inputs_invalidates_displayed_and_pending_distances(window, application):
    window.measure_pair()
    finish_jobs(window, application)
    assert window.view.selected_contact["distance_kind"] == "minimum_image"
    window.measurement_mode.setCurrentIndex(1)
    assert window.view.selected_contact is None and "1.420282" not in window.measurement_label.text()
    window.measure_pair()
    window.shift_spins[1][0].setValue(2)
    finish_jobs(window, application)
    assert window.view.selected_contact is None
    window.measure_pair()
    finish_jobs(window, application)
    assert window.view.selected_contact["end_shift"][0] == 2


def test_prepare_preview_apply_keeps_original_source_evidence(window, application, tmp_path, monkeypatch):
    source = b"""data_nonp1
_cell_length_a 4
_cell_length_b 5
_cell_length_c 20
_cell_angle_alpha 90
_cell_angle_beta 90
_cell_angle_gamma 90
_space_group_IT_number 2
loop_
_atom_site_label
_atom_site_type_symbol
_atom_site_fract_x
_atom_site_fract_y
_atom_site_fract_z
_atom_site.occupancy
C1 C 0.1 0.2 0.3 1
"""
    path = tmp_path / "nonp1.cif"
    path.write_bytes(source)
    window.open_cifs([path], mode="replace")
    finish_jobs(window, application)
    assert window.selected_entry["analysis"]["report"] is None
    monkeypatch.setattr(QDialog, "exec", lambda self: QDialog.DialogCode.Accepted)
    window.preview_preparation()
    finish_jobs(window, application)
    assert window.view.report["atom_count"] == 2
    assert window.selected_entry["preparation"]["source_site_count"] == 1
    assert window.workspace.project.entries[0].preparation["source"]["filename"] == "nonp1.cif"


def test_save_open_retains_draft_camera_and_unknown_extension(window, application, tmp_path):
    from dataclasses import replace

    window.workspace.project = replace(window.workspace.project, workspace_state={"future": {"keep": 42}})
    window.note_edit.setPlainText("Unapplied, but saved")
    window.view.zoom = 1.7
    window._view_changed()
    path = tmp_path / "native.calclens.zip"
    assert window.save_project(path)
    project = loads_project(path.read_bytes())
    assert project.workspace_state["future"] == {"keep": 42}
    assert project.entries[0].note == ""
    assert not window.dirty
    window.note_edit.setPlainText("Temporary replacement")
    window.open_project(path, confirm=False)
    finish_jobs(window, application)
    assert window.note_edit.toPlainText() == "Unapplied, but saved"
    assert window.view.zoom == pytest.approx(1.7)
    assert not window.dirty


def test_failed_save_keeps_existing_file_dirty_state_and_save_identity(window, tmp_path, monkeypatch):
    import slab_preflight.desktop as desktop

    path = tmp_path / "existing.calclens.zip"
    path.write_bytes(b"previous saved content")
    window.note_edit.setPlainText("Must remain recoverable")
    monkeypatch.setattr(desktop, "atomic_write", lambda *_: (_ for _ in ()).throw(OSError("write denied")))
    assert window.save_project(path) is False
    assert path.read_bytes() == b"previous saved content"
    assert window.project_path is None
    assert window.dirty
    assert "write denied" in window.error_label.text()


def test_invalid_original_research_source_cannot_replace_live_project(window, application, tmp_path):
    from slab_preflight.project import dumps_project_archive

    original = window.workspace.project
    original_revision = window.workspace.revision
    archive = tmp_path / "untrusted.calclens.zip"
    archive.write_bytes(dumps_project_archive(original))

    class RejectingResearch:
        @staticmethod
        def validate_state(state, entries):
            raise ValueError("Electronic source cannot be reproduced")

    window.research_panel = RejectingResearch()
    window.open_project(archive, confirm=False)
    finish_jobs(window, application)
    assert window.workspace.project is original
    assert window.workspace.revision == original_revision
    assert "cannot be reproduced" in window.error_label.text()
    window.research_panel = None


def test_untrusted_native_draft_types_are_ignored_on_open(window, application, tmp_path):
    from dataclasses import replace
    from slab_preflight.project import dumps_project_archive

    entry = window.selected_entry
    state = {"native_desktop": {"schema_version": 1, "drafts": {entry["id"]: {
        "sha256": entry["sha256"], "normal_axis": [], "short_distance": "nan", "note": [],
    }}, "views": {window._view_key(entry): "not a camera"}}}
    archive = tmp_path / "malformed-ui-state.calclens.zip"
    archive.write_bytes(dumps_project_archive(replace(window.workspace.project, workspace_state=state)))
    window.open_project(archive, confirm=False)
    finish_jobs(window, application)
    assert window.axis_combo.currentText() == "c"
    assert window.cutoff_spin.value() == 1.0
    assert window.note_edit.toPlainText() == ""
    assert window.portable_state()["native_desktop"]["drafts"] == {}


def test_close_cancel_and_failed_save_do_not_close_window(window, monkeypatch):
    window.note_edit.setPlainText("Unsaved")
    monkeypatch.setattr(QMessageBox, "warning", lambda *_: QMessageBox.StandardButton.Cancel)
    assert not window.close()
    assert window.isVisible()
    monkeypatch.setattr(QMessageBox, "warning", lambda *_: QMessageBox.StandardButton.Save)
    monkeypatch.setattr(window, "save_project", lambda: False)
    assert not window.close()
    assert window.isVisible()


def test_replaced_background_result_cannot_update_gui_from_stale_job(window, application):
    started, release = threading.Event(), threading.Event()
    received = []

    def slow():
        started.set()
        assert release.wait(3)
        return "old"

    window.submit(slow, lambda value: received.append(value), key="same-source")
    assert started.wait(1)

    def newest(value):
        assert QThread.currentThread() == application.thread()
        received.append(value)

    window.submit(lambda: "new", newest, key="same-source")
    release.set()
    finish_jobs(window, application)
    assert received == ["new"]


def test_cancel_running_result_does_not_apply_it_and_keeps_file_navigation_enabled(window, application):
    started, release = threading.Event(), threading.Event()
    received = []

    def slow():
        started.set()
        assert release.wait(3)
        return "must not apply"

    window.submit(slow, received.append, key="research-compute")
    try:
        assert started.wait(1)
        assert window.file_list.isEnabled()
        status = window.cancel_job("research-compute")
        assert status == {"invalidated": 1, "running": 1, "pending": 0}
    finally:
        release.set()
        finish_jobs(window, application)
    assert received == []


def test_cancel_pending_job_skips_its_computation(window, application):
    started, release = threading.Event(), threading.Event()
    computed, applied = [], []

    def blocker():
        started.set()
        assert release.wait(3)

    window.submit(blocker, key="busy-research")
    try:
        assert started.wait(1)
        window.submit(lambda: computed.append(True), applied.append, key="queued-research")
        assert window.cancel_job("queued-research") == {"invalidated": 1, "running": 0, "pending": 1}
    finally:
        release.set()
        finish_jobs(window, application)
    assert computed == [] and applied == []


def test_superseded_pending_surface_job_does_not_build_an_obsolete_mesh(window, application):
    started, release = threading.Event(), threading.Event()
    computed, applied = [], []

    def blocker():
        started.set()
        assert release.wait(3)

    window.submit(blocker, key="other-numeric-job")
    try:
        assert started.wait(1)
        window.submit(lambda: computed.append("old"), applied.append, key="surface")
        window.submit(lambda: computed.append("new") or "new", applied.append, key="surface")
    finally:
        release.set()
        finish_jobs(window, application)
    assert computed == ["new"] and applied == ["new"]


def test_workspace_selection_completes_while_read_only_numeric_job_is_running(window, application):
    window.open_cifs([ROOT / "examples/hbn.cif"])
    finish_jobs(window, application)
    original = window.selected_entry["id"]
    other = next(entry["id"] for entry in window.snapshot["entries"] if entry["id"] != original)
    started, release = threading.Event(), threading.Event()

    def slow():
        started.set()
        assert release.wait(3)

    window.submit(slow, key="research-compute")
    try:
        assert started.wait(1)
        window.select_entry(other)
        until = time.monotonic() + 1
        while window.selected_entry["id"] != other and time.monotonic() < until:
            application.processEvents()
            QTest.qWait(5)
        assert window.selected_entry["id"] == other
        assert not release.is_set()
    finally:
        release.set()
        finish_jobs(window, application)


def test_recovery_write_is_not_blocked_by_a_running_numeric_job(window, application, tmp_path):
    store = RecoveryStore(tmp_path / "concurrent-recovery")
    window.recovery = store
    started, release = threading.Event(), threading.Event()

    def slow():
        started.set()
        assert release.wait(3)

    window.submit(slow, key="research-compute")
    try:
        assert started.wait(1)
        window.note_edit.setPlainText("Autosave while numerical work continues")
        window._save_recovery()
        deadline = time.monotonic() + 1
        target = store._path(store.session_id)
        while not target.exists() and time.monotonic() < deadline:
            application.processEvents()
            QTest.qWait(5)
        assert target.is_file()
        project = loads_project(target.read_bytes())
        assert project.workspace_state["native_desktop"]["drafts"][window.selected_entry["id"]]["note"] == "Autosave while numerical work continues"
        assert not release.is_set()
    finally:
        release.set()
        finish_jobs(window, application)
        window.recovery = None
        store.close(keep=False)


def test_report_and_annotated_png_exports_use_real_source_identity(window, tmp_path):
    csv_path, json_path, png_path = (tmp_path / name for name in ("report.csv", "report.json", "view.png"))
    assert window.export_report("csv", path=csv_path)
    assert window.export_report("json", path=json_path)
    assert window.export_png(path=png_path)
    report = json.loads(json_path.read_text())
    assert report["provenance"]["sha256"] == window.selected_entry["sha256"]
    assert "sha256" in csv_path.read_text(encoding="utf-8-sig").lower()
    image = QImage(str(png_path))
    assert not image.isNull()
    provenance = json.loads(image.text("CalcLens provenance"))
    assert provenance["sha256"] == window.selected_entry["sha256"]
    assert provenance["normal_axis"] == "c"
    assert image.height() > 1200


def test_crash_recovery_restores_native_unapplied_draft(application, tmp_path):
    first_store = RecoveryStore(tmp_path / "recovery")
    first = MainWindow(language="en", root=ROOT, recovery=first_store, research_factory=False)
    first.note_edit.setPlainText("Draft survived interruption")
    first._save_recovery()
    finish_jobs(first, application)
    first_store.close(keep=True)
    first.recovery = None  # Simulate a process exit without its normal close/discard path.
    first.dirty = False
    first.close()
    second_store = RecoveryStore(tmp_path / "recovery")
    second = MainWindow(language="en", root=ROOT, recovery=second_store, research_factory=False)
    second.show()
    application.processEvents()
    try:
        assert second.recovery_frame.isVisible()
        second.restore_recovery()
        finish_jobs(second, application)
        assert second.note_edit.toPlainText() == "Draft survived interruption"
        assert second.dirty
    finally:
        second.dirty = False
        second.close()


def test_view_rotates_zooms_and_emits_actual_atom_picks(application):
    view = StructureView(language="en")
    view.set_structure(analyze_cif((ROOT / "examples/mos2.cif").read_bytes()))
    view.resize(720, 600)
    view.show()
    application.processEvents()
    original_yaw = view.yaw
    QTest.mousePress(view, Qt.MouseButton.LeftButton, pos=QPoint(300, 250))
    QTest.mouseMove(view, QPoint(360, 280), delay=10)
    QTest.mouseRelease(view, Qt.MouseButton.LeftButton, pos=QPoint(360, 280))
    assert view.yaw != original_yaw
    event = QWheelEvent(QPointF(300, 250), QPointF(300, 250), QPoint(), QPoint(0, 120),
                        Qt.MouseButton.NoButton, Qt.KeyboardModifier.NoModifier,
                        Qt.ScrollPhase.ScrollUpdate, False)
    QApplication.sendEvent(view, event)
    assert view.zoom > 1
    application.processEvents()
    picked = QSignalSpy(view.atomPicked)
    _, x, y, _ = view._projected_atoms[-1]
    QTest.mouseClick(view, Qt.MouseButton.LeftButton, pos=QPoint(round(x), round(y)))
    assert picked.count() == 1
    view.close()


def test_electronic_values_are_not_zero_filled_and_mesh_indices_are_checked(application):
    view = StructureView(language="en")
    view.set_structure(analyze_cif((ROOT / "examples/mos2.cif").read_bytes()))
    view.set_charges([None, -0.2, 0.2], {"method": "external"})
    assert view.charges[0] is None
    with pytest.raises(ValueError):
        view.set_charges([float("nan"), 0, 0])
    with pytest.raises(ValueError):
        view.set_charges([0, 0, 0], {"color_extent": -1})
    view.set_charges([0.2, None, -0.2], {"kind": "oxidation_state", "color_extent": 2})
    assert view._charge_extent() == 2
    assert view._charge_description() == ("Oxidation state", "dimensionless")
    with pytest.raises(ValueError):
        view.set_surfaces([{"vertices": [[0, 0, 0]], "faces": [[0, 1, 2]]}])
    view.set_surfaces([{"vertices": [[0, 0, 0], [1, 0, 0], [0, 1, 0]], "faces": [[0, 1, 2]],
                        "color": "#234567", "label": "Imported positive phase"}])
    assert len(view.surfaces) == 1


def test_long_png_annotations_expand_footer_instead_of_clipping(application, tmp_path):
    view = StructureView(language="en")
    view.set_structure(analyze_cif((ROOT / "examples/mos2.cif").read_bytes()), {
        "filename": "long original source " * 30 + ".cif", "sha256": "abcdef0123456789" * 4,
    })
    plain_path = tmp_path / "plain_annotations.png"
    view.export_png(plain_path)
    plain_height = QImage(str(plain_path)).height()
    view.set_charges([0.2, None, -0.2], {"source": "charge source " * 100, "units": "e", "method": "Löwdin"})
    path = tmp_path / "long_annotations.png"
    view.export_png(path)
    image = QImage(str(path))
    assert image.height() > plain_height
    metadata = json.loads(image.text("CalcLens provenance"))
    assert metadata["charge"]["source"] == "charge source " * 100


@pytest.mark.parametrize("kind,label,detail", [
    ("density", "Total electron density", "total electron-density isosurface"),
    ("difference_density", "Difference density Δρ", "accumulation and depletion"),
    ("spin_density", "Spin density", "signed spin density"),
    ("orbital", "Orbital phase", "wavefunction phase sign"),
])
def test_surface_annotations_identify_the_actual_physical_quantity(application, kind, label, detail):
    view = StructureView(language="en")
    view.set_structure(analyze_cif((ROOT / "examples/graphene.cif").read_bytes()))
    view.set_surfaces([{"vertices": [[0, 0, 0], [1, 0, 0], [0, 1, 0]], "faces": [[0, 1, 2]],
                        "label": "+0.05"}], {"kind": kind})
    assert view._surface_description() == label
    assert detail in view._export_annotations()
    if kind != "orbital":
        assert "Orbital colors denote wavefunction" not in view._export_annotations()


def test_native_entrypoint_opens_cli_and_finder_files_without_http(application, monkeypatch):
    import slab_preflight.desktop as desktop
    import slab_preflight.web_api as web_api

    original_window = desktop.MainWindow

    def isolated_window(**kwargs):
        return original_window(**kwargs, recovery=False, research_factory=False)

    monkeypatch.setattr(desktop, "MainWindow", isolated_window)
    monkeypatch.setattr(web_api, "create_server", lambda *_args, **_kwargs: pytest.fail("Native entrypoint started HTTP"))
    assert desktop.main(language="en", root=ROOT, argv=["CalcLens", str(ROOT / "examples/hbn.cif")]) == 0
    application.processEvents()
    widget = application._calclens_window
    try:
        finish_jobs(widget, application)
        assert [entry["filename"] for entry in widget.snapshot["entries"]] == ["hbn.cif"]
        QApplication.sendEvent(application, QFileOpenEvent(str(ROOT / "examples/mos2.cif")))
        application.processEvents()
        finish_jobs(widget, application)
        assert [entry["filename"] for entry in widget.snapshot["entries"]] == ["hbn.cif", "mos2.cif"]
    finally:
        widget.dirty = False
        widget.close()
        application.removeEventFilter(application._calclens_file_filter)
        application._calclens_file_filter.deleteLater()


def test_comparison_supports_independent_cifs_same_cif_and_linked_camera(window, application):
    window.open_cifs([ROOT / "examples/graphene.cif", ROOT / "examples/hbn.cif"], mode="replace")
    finish_jobs(window, application)
    dialog = window.create_comparison_dialog()
    dialog.show()
    application.processEvents()
    try:
        assert dialog.panes[0]["view"].report["formula"] == "C2"
        assert dialog.panes[1]["view"].report["formula"] == "BN"
        assert float(dialog.metrics.item(1, 3).text()) == pytest.approx((2.5 - 2.46) / 3**0.5, rel=1e-5)
        dialog.link_cameras.setChecked(True)
        left, right = [pane["view"] for pane in dialog.panes]
        left.yaw += 0.3
        left.viewChanged.emit()
        assert right.yaw == left.yaw
        dialog.panes[1]["file"].setCurrentIndex(0)
        assert dialog.panes[1]["view"].report["formula"] == "C2"
        assert float(dialog.metrics.item(1, 3).text()) == 0
        assert window.comparison_state["panes"][0]["entry_id"] == window.comparison_state["panes"][1]["entry_id"]
    finally:
        dialog.close()


def test_old_electronic_drafts_comparison_and_camera_data_survive_native_save(window, application, tmp_path):
    from copy import deepcopy
    from dataclasses import replace
    from slab_preflight.project import dumps_project_archive

    original = loads_project((ROOT / "examples/electronic_case/real-water.calclens.zip").read_bytes())
    state = deepcopy(original.workspace_state)
    entry = original.entries[0]
    digest = __import__("hashlib").sha256(entry.data).hexdigest()
    state["drafts"][entry.id] = {"sha256": digest, "axis": "c", "cutoff": "1.5", "note": "v0.8 unapplied draft",
                                  "baseline": {"axis": "c", "cutoff": "1", "note": entry.note}}
    path = tmp_path / "old-with-draft.calclens.zip"
    path.write_bytes(dumps_project_archive(replace(original, workspace_state=state)))
    window.open_project(path, confirm=False)
    finish_jobs(window, application)
    assert window.note_edit.toPlainText() == "v0.8 unapplied draft"
    assert window.cutoff_spin.value() == 1.5
    assert window.view.show_cell is False
    assert window.view.show_labels is False
    saved = tmp_path / "native-resaved.calclens.zip"
    assert window.save_project(saved)
    restored = loads_project(saved.read_bytes()).workspace_state
    for key in ("auxiliary", "drafts", "viewers", "comparison"):
        assert restored[key] == state[key]
    assert restored["native_desktop"]["drafts"][entry.id]["note"] == "v0.8 unapplied draft"


def test_default_research_comparison_restores_normalized_old_isovalues_and_shared_ranges(application):
    from slab_preflight.density import BOHR_ANGSTROM

    widget = MainWindow(language="ko", root=ROOT, recovery=False)
    widget.show()
    dialog = None
    try:
        widget.open_project(ROOT / "examples/electronic_case/real-water.calclens.zip", confirm=False)
        finish_jobs(widget, application)
        dialog = widget.compare_structures()
        finish_jobs(widget, application)
        left, right = dialog.panes
        assert left["level"].value() == pytest.approx(0.05 / BOHR_ANGSTROM**3)
        assert right["level"].value() == pytest.approx(0.05 / BOHR_ANGSTROM**1.5)
        assert left["units"].text() == "e/Å³"
        assert right["units"].text() == "Å⁻³/²"
        assert left["view"].surfaces and right["view"].surfaces
        assert left["view"].charge_metadata["color_extent"] == right["view"].charge_metadata["color_extent"]
        assert left["view"].charges != right["view"].charges
        right["charge"].setCurrentIndex(0)
        finish_jobs(widget, application)
        assert not dialog.shared_range.isEnabled()
        assert not dialog.shared_range.isChecked()
        assert right["view"].charges is None
    finally:
        if dialog:
            dialog.close()
        finish_jobs(widget, application)
        widget.dirty = False
        widget.close()
