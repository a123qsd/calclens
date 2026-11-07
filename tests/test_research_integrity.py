"""Retained numerical work is independent of later native UI choices."""

from copy import deepcopy
from hashlib import sha256
import json
import os
from pathlib import Path
import threading
import time

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
pytest.importorskip("PySide6")
from PySide6.QtTest import QTest
from PySide6.QtGui import QImage
from PySide6.QtWidgets import QApplication

from slab_preflight.desktop import MainWindow
from slab_preflight.project import dumps_project_archive, loads_project
from slab_preflight.recovery import RecoveryStore
from test_density_records import retained

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture(scope="module")
def app():
    return QApplication.instance() or QApplication([])


@pytest.fixture
def window(app):
    widget = MainWindow("en", root=ROOT, recovery=False)
    widget.show()
    errors = []

    def immediate(fn, after=None, **kwargs):
        try:
            value = fn()
        except Exception as error:
            errors.append(str(error))
            return
        return after(value) if after else None

    widget.submit = immediate
    widget.show_error = lambda error: errors.append(str(error))
    yield widget, errors
    widget.dirty = False
    widget.close()
    app.processEvents()


def h2(window):
    window.open_project(
        ROOT / "examples/research_cases/h2_density/h2-density.calclens.zip", confirm=False
    )
    panel = window.research_panel
    panel.device.setCurrentIndex(panel.device.findData("cpu"))
    return panel


def water(window):
    window.open_project(ROOT / "examples/electronic_case/real-water.calclens.zip", confirm=False)
    panel = window.research_panel
    panel.device.setCurrentIndex(panel.device.findData("cpu"))
    for index in range(panel.volume.count()):
        if "density" in panel.volume.itemText(index).lower():
            panel.volume.setCurrentIndex(index)
            break
    return panel


def choose_homo(panel):
    for index in range(panel.volume.count()):
        if "homo" in panel.volume.itemText(index).lower():
            panel.volume.setCurrentIndex(index)
            return
    raise AssertionError("The real water project must retain its HOMO source.")


def test_h2_difference_reopens_after_main_axis_changes_without_losing_originals(window, tmp_path):
    win, errors = window
    panel = h2(win)
    win.note_edit.setPlainText("Original calculation note · 원본 보존")
    win.apply_settings()
    panel.difference()
    uid = panel.volume.currentData()
    digest = panel._digest
    record = deepcopy(panel.native["differences"][digest][uid])
    source_hashes = {k: sha256(v["raw"].encode()).hexdigest() for k, v in record["sources"].items()}
    retained = panel._source("volume", uid)["rawText"]
    profile = deepcopy(panel._profile)
    win.axis_combo.setCurrentText("a")
    win.apply_settings()
    path = tmp_path / "axis-a.calclens.zip"
    assert win.save_project(path=path)
    win.open_project(path, confirm=False)
    assert not errors
    assert win.selected_entry["normal_axis"] == "a"
    assert win.selected_entry["note"] == "Original calculation note · 원본 보존"
    panel = win.research_panel
    reopened = panel.native["differences"][digest][uid]
    assert reopened["sources"] == record["sources"]
    assert {k: sha256(v["raw"].encode()).hexdigest() for k, v in reopened["sources"].items()} == source_hashes
    assert panel._source("volume", uid)["rawText"] == retained
    assert reopened["computation"]["profile"] == profile
    assert reopened["calculation"]["structure_normal_axis"] == "c"
    assert "current" in panel.archive_info.text().lower()
    assert "differ" in panel.archive_info.text().lower()


def test_selecting_homo_clears_density_chart_and_disables_exports(window):
    win, errors = window
    panel = water(win)
    panel.average()
    assert panel.chart.profile is not None
    choose_homo(panel)
    assert panel.chart.profile is None and panel._profile is None
    assert panel.device_info.text() == ""
    assert not panel.profile_save.isEnabled()
    assert not panel.profile_record_save.isEnabled()
    exported = []
    panel._save = lambda *args: exported.append(args)
    panel.export_profile()
    panel.export_profile_record()
    assert exported == []
    assert not errors


def test_completed_difference_record_is_bound_to_inputs_and_exports_complete_json(window):
    win, errors = window
    panel = h2(win)
    panel.difference()
    uid = panel.volume.currentData()
    retained = deepcopy(panel.native["differences"][panel._digest][uid])
    exported = []
    panel._save = lambda *args: exported.append(args)
    panel.export_profile_record()
    record = json.loads(exported[-1][0])
    assert record["schema_version"] >= 1
    assert record["dataset"]["dataset_id"] == uid
    assert record["dataset"]["source_sha256"] == sha256(panel._source("volume", uid)["rawText"].encode()).hexdigest()
    assert record["profile"]["units"] == record["grid"]["units"] == "e/angstrom^3"
    assert record["calculation"]["normal_vector"] == retained["calculation"]["normal_vector"]
    assert record["execution"]["effective_device"] == "cpu"
    assert record["provenance"]["a_indices_one_based"] == [1]
    assert record["provenance"]["b_indices_one_based"] == [2]
    assert record["provenance"]["frozen_geometry_confirmed"] is True
    assert len(record["provenance"]["sources"]) == 3
    assert all(v["source_sha256"] and v["source_name"] for v in record["provenance"]["sources"])
    panel.method.setText("Changed future calculation")
    panel._store_draft()
    assert panel._profile is None
    assert panel.native["differences"][panel._digest][uid] == retained
    assert "reference" in panel.native["drafts"][panel._digest]
    assert "sources" not in panel.native["drafts"][panel._digest]
    assert not errors


@pytest.mark.parametrize("change", ["dataset", "axis", "fragments", "conditions", "main-axis",
                                   "raw-source", "units", "kind", "device", "location",
                                   "credentials", "changed-back"])
def test_old_numeric_completion_cannot_apply_after_inputs_change(window, change):
    win, errors = window
    panel = water(win)
    captured = []
    win.submit = lambda fn, after=None, **kwargs: captured.append((fn, after, kwargs))
    panel.average()
    fn, done, kwargs = captured[-1]
    computed = fn()
    if change == "dataset":
        choose_homo(panel)
    elif change == "axis":
        panel.axis.setCurrentIndex(0)
    elif change == "fragments":
        panel._fragments = {"AB": {"filename": "changed.cube", "raw": "changed"}}
        panel._store_draft()
    elif change == "conditions":
        panel.conditions.setText("New conditions")
        panel._store_draft()
    elif change == "main-axis":
        changed_entry = deepcopy(panel.entry)
        changed_entry["normal_axis"] = "a"
        panel.set_entry(changed_entry, "en")
    elif change == "raw-source":
        panel._source("volume", panel.volume.currentData())["rawText"] += "\n"
    elif change == "units":
        panel._source("volume", panel.volume.currentData())["units"] = "e/angstrom^3"
    elif change == "kind":
        panel._source("volume", panel.volume.currentData())["kind"] = "spin_density"
    elif change == "device":
        panel.device.setCurrentIndex(panel.device.findData("auto"))
    elif change == "location":
        panel.devices.location.setCurrentIndex(panel.devices.location.findData("remote"))
    elif change == "credentials":
        panel.token.setText("session-only-secret")
        panel.token.clear()
    else:
        index = panel.volume.currentIndex()
        choose_homo(panel)
        panel.volume.setCurrentIndex(index)
    done(computed)
    assert panel._profile is None and panel.chart.profile is None
    assert not panel.profile_save.isEnabled()
    assert not errors


def test_device_settings_do_not_discard_an_independent_log_import(window):
    win, errors = window
    panel = water(win)
    captured = []
    win.submit = lambda fn, after=None, **kwargs: captured.append((fn, after, kwargs))
    panel.example_log()
    fn, done, kwargs = captured[-1]
    result = fn()
    panel.device.setCurrentIndex(panel.device.findData("auto"))
    done(result)
    assert "Gaussian" in panel.log_info.toPlainText()
    assert panel._log is not None
    assert not errors


def test_pair_and_profile_csv_identify_the_exact_dataset_and_conditions(window):
    win, errors = window
    panel = water(win)
    panel.average()
    exported = []
    panel._save = lambda *args: exported.append(args)
    panel.export_profile()
    import csv
    import io
    rows = list(csv.DictReader(io.StringIO(exported[-1][0].decode("utf-8-sig"))))
    item = panel._source("volume", panel.volume.currentData())
    assert rows[0]["dataset_id"] == item["id"]
    assert rows[0]["source_sha256"] == sha256(item["rawText"].encode()).hexdigest()
    assert rows[0]["structure_sha256"] == panel._digest
    assert rows[0]["field_units"] == "e/angstrom^3"
    assert rows[0]["grid_plane_axis"] == "2"
    panel.calculate_pairs()
    panel.export_pairs()
    rows = list(csv.DictReader(io.StringIO(exported[-1][0].decode("utf-8-sig"))))
    assert rows[0]["structure_sha256"] == panel._digest
    assert rows[0]["operation"] == "minimum_image_pair_distances"
    assert not errors


def test_language_display_snapshot_restores_only_matching_inputs(window):
    win, errors = window
    panel = water(win)
    panel.average()
    original = deepcopy(panel._profile)
    transient = panel.transient_results()
    panel._clear_profile()
    panel.restore_transient_results(transient)
    assert panel._profile == original
    choose_homo(panel)
    panel.restore_transient_results(transient)
    assert panel._profile is None
    assert not errors


def test_actual_language_rebuild_keeps_the_valid_profile_record_and_cpu_choice(window, app):
    win, errors = window
    panel = water(win)
    panel.mode.setCurrentIndex(1)
    panel.average()
    original_profile = deepcopy(panel._profile)
    original_record = deepcopy(panel._profile_record)
    win.language_combo.setCurrentIndex(win.language_combo.findData("ko"))
    app.processEvents()
    panel = win.research_panel
    assert win.language == "ko"
    assert panel.mode.currentIndex() == 1
    assert panel.device.currentData() == "cpu"
    assert panel._profile == original_profile
    assert panel._profile_record == original_record
    assert panel.profile_save.isEnabled()
    assert not errors


def test_blocked_geometry_can_reopen_inspect_and_export_retained_originals(window, tmp_path):
    win, errors = window
    project, _, _, _, _ = retained(legacy=True)
    path = tmp_path / "legacy-skew.calclens.zip"
    path.write_bytes(dumps_project_archive(project))
    win.open_project(path, confirm=False)
    panel = win.research_panel
    raw = panel.native["differences"][panel._digest]["difference"]["sources"]["AB"]["raw"]
    win.axis_combo.setCurrentText("a")
    win.apply_settings()
    assert win.selected_entry["analysis"]["report"] is None
    assert win.save_project(path=path)
    win.open_project(path, confirm=False)
    panel = win.research_panel
    assert panel.archive_export.isEnabled()
    assert "orientation not recorded" in panel.archive_info.text()
    assert "CPU replay" in panel.archive_details.toPlainText()
    exported = []
    panel._save = lambda *args: exported.append(args)
    # A selected legacy record is not a current profile until explicitly computed.
    panel.export_fragment("AB")
    assert exported[-1][0] == raw.encode()
    assert win.selected_entry["normal_axis"] == "a"
    assert not errors


def test_rejected_save_protects_the_previous_file_and_original_save_identity(window, tmp_path):
    win, errors = window
    panel = h2(win)
    path = tmp_path / "protected.calclens.zip"
    assert win.save_project(path=path)
    previous = path.read_bytes()
    uid = panel.volume.currentData()
    panel.native["differences"][panel._digest][uid]["sources"]["AB"]["raw"] += "\ncorrupt"
    win.mark_dirty()
    assert not win.save_project(path=path)
    assert path.read_bytes() == previous
    assert win.project_path == path and win.dirty
    assert errors


def test_autorecovery_retains_originals_calculation_and_unapplied_note(window, tmp_path):
    win, errors = window
    panel = h2(win)
    panel.difference()
    uid, digest = panel.volume.currentData(), panel._digest
    original = deepcopy(panel.native["differences"][digest][uid])
    win.axis_combo.setCurrentText("a")
    win.apply_settings()
    win.note_edit.setPlainText("Draft after calculation · 복구 메모")
    store = RecoveryStore(tmp_path / "recovery")
    win.recovery = store
    win._save_recovery()
    store.close(keep=True)
    win.recovery = None
    reader = RecoveryStore(tmp_path / "recovery")
    try:
        candidates = reader.candidates()
        assert len(candidates) == 1
        archive = reader.load(candidates[0])
        recovered = loads_project(archive)
        assert recovered.workspace_state["native_research"]["differences"][digest][uid] == original
        assert recovered.workspace_state["native_desktop"]["drafts"][win.selected_entry["id"]]["note"] == "Draft after calculation · 복구 메모"
        win._validated_import(archive)
        assert not errors
    finally:
        reader.close(keep=False)


def test_difference_project_csv_json_cube_and_png_share_identity_and_units(window, tmp_path):
    win, errors = window
    panel = h2(win)
    panel.difference()
    uid = panel.volume.currentData()
    item = panel._source("volume", uid)
    digest = sha256(item["rawText"].encode()).hexdigest()
    assert f'"dataset_id": "{uid}"' in item["rawText"].splitlines()[1]
    assert "difference_density; e/angstrom^3" in item["rawText"].splitlines()[1]
    captures = []
    panel._save = lambda *args: captures.append(args)
    panel.export_profile_record()
    record = json.loads(captures[-1][0])
    panel.export_profile()
    import csv
    import io
    first = next(csv.DictReader(io.StringIO(captures[-1][0].decode("utf-8-sig"))))
    panel.draw_surface()
    path = tmp_path / "identified.png"
    assert win.export_png(path=path)
    metadata = json.loads(QImage(str(path)).text("CalcLens provenance"))["surface"]
    assert metadata["dataset_id"] == record["dataset"]["dataset_id"] == first["dataset_id"] == uid
    assert metadata["source_sha256"] == record["dataset"]["source_sha256"] == first["source_sha256"] == digest
    assert metadata["units"] == record["profile"]["units"] == first["field_units"] == "e/angstrom^3"
    assert metadata["calculation"] == record["calculation"]
    assert metadata["provenance"]["frozen_geometry_confirmed"] is True
    assert not errors


def test_device_probe_does_not_replace_a_running_density_job(app, monkeypatch):
    win = MainWindow("en", root=ROOT, recovery=False)
    errors = []
    win.show_error = lambda error: errors.append(str(error))
    deadline = time.monotonic() + 10
    win.open_project(ROOT / "examples/electronic_case/real-water.calclens.zip", confirm=False)
    while win.is_busy and time.monotonic() < deadline:
        app.processEvents()
        QTest.qWait(5)
    panel = win.research_panel
    panel.device.setCurrentIndex(panel.device.findData("cpu"))
    for i in range(panel.volume.count()):
        if "density" in panel.volume.itemText(i).lower():
            panel.volume.setCurrentIndex(i)
            break
    started = threading.Event()
    release = threading.Event()
    import slab_preflight.desktop_research as research
    original = research.planar_average

    def delayed(*args, **kwargs):
        started.set()
        assert release.wait(5)
        return original(*args, **kwargs)

    monkeypatch.setattr(research, "planar_average", delayed)
    monkeypatch.setattr("slab_preflight.desktop_devices.probe_devices", lambda: [
        {"id": "cpu", "available": True, "device_name": "CPU test probe"}
    ])
    try:
        panel.average()
        assert started.wait(5)
        panel.check_devices()
        until = time.monotonic() + 5
        while any(job.key == "device-probe" for job, _, _ in win._jobs.values()) and time.monotonic() < until:
            app.processEvents()
            QTest.qWait(5)
        release.set()
        until = time.monotonic() + 5
        while win.is_busy and time.monotonic() < until:
            app.processEvents()
            QTest.qWait(5)
        assert panel._profile is not None
        assert panel._profile["execution"]["effective_device"] == "cpu"
        assert not errors
    finally:
        release.set()
        win.dirty = False
        win.close()
        app.processEvents()
