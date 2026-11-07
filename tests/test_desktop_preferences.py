import os
import time
from pathlib import Path

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
from PySide6.QtGui import QColor, QPalette
from PySide6.QtWidgets import QApplication, QMessageBox

from slab_preflight.desktop import MainWindow
from slab_preflight.desktop_devices import format_execution
from slab_preflight.desktop_preferences import DesktopPreferences


ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture(scope="module")
def app():
    return QApplication.instance() or QApplication([])


def _luminance(color):
    rgb = [color.redF(), color.greenF(), color.blueF()]
    values = [(v / 12.92 if v <= 0.04045 else ((v + 0.055) / 1.055) ** 2.4) for v in rgb]
    return sum(factor * value for factor, value in zip((0.2126, 0.7152, 0.0722), values))


def contrast(palette, group, fg, bg):
    a, b = sorted(_luminance(palette.color(group, QPalette.ColorRole[key])) for key in (fg, bg))
    return (b + 0.05) / (a + 0.05)


def drain(win, app):
    deadline = time.monotonic() + 8
    while win.is_busy and time.monotonic() < deadline:
        app.processEvents()
        time.sleep(.005)
    assert not win.is_busy


@pytest.mark.parametrize("mode,system_dark", [("light", True), ("dark", False), ("system", True), ("system", False)])
@pytest.mark.parametrize("language", ["ko", "en"])
def test_effective_palette_in_main_research_popups_dialogs(app, mode, system_dark, language):
    base = QColor("#171b21" if system_dark else "#fafbfb")
    pal = QPalette(app.palette())
    pal.setColor(QPalette.ColorRole.Base, base)
    pal.setColor(QPalette.ColorRole.Text, QColor("white" if system_dark else "black"))
    app.setPalette(pal)
    DesktopPreferences().set("theme", mode)
    win = MainWindow(language, root=ROOT, recovery=False)
    win.resize(1100, 700)
    win.show()
    dialog = win.create_comparison_dialog()
    dialog.show()
    error = QMessageBox(QMessageBox.Icon.Warning, "CalcLens", "Error", parent=win)
    error.show()
    try:
        win.tabs.setCurrentIndex(1)
        app.processEvents()
        groups = (QPalette.ColorGroup.Active, QPalette.ColorGroup.Inactive, QPalette.ColorGroup.Disabled)
        for widget, fg, bg in [
            (win.report_text, "Text", "Base"), (win.note_edit, "Text", "Base"),
            (win.research_panel.device, "Text", "Base"), (win.axis_combo.view(), "Text", "Base"),
            (win.settings_menu, "Text", "Base"), (win.statusBar(), "WindowText", "Window"),
            (dialog, "WindowText", "Window"), (error, "WindowText", "Window"),
            (win.report_text, "HighlightedText", "Highlight"), (win, "ToolTipText", "ToolTipBase"),
        ]:
            widget.ensurePolished()
            for group in groups:
                assert contrast(widget.palette(), group, fg, bg) >= 4.5, (widget, fg, bg, group)
        dark = mode == "dark" or (mode == "system" and system_dark)
        assert (win.report_text.palette().color(QPalette.ColorRole.Base).lightnessF() < .5) is dark
        assert not win.grab().isNull() and not dialog.grab().isNull()
    finally:
        error.close()
        dialog.close()
        win.dirty = False
        win.close()
        app.processEvents()


@pytest.mark.parametrize("language", ["en", "ko"])
def test_layout_narrow_windows_preserve_editable_controls_and_complete_hash(app, language):
    win = MainWindow(language, root=ROOT, recovery=False)
    win.show()
    try:
        for width, height in [(1920, 1080), (1366, 768), (1093, 614), (911, 512), (683, 384)]:
            win.resize(width, height)
            app.processEvents()
            assert (win.width(), win.height()) == (width, height)
            if not win.tabs.isVisible():
                win._toggle_inspector()
            assert win.tabs.isVisible() and win.tabs.width() > 210
            win.tabs.setCurrentWidget(win.research_panel)
            win.research_panel.mode.setCurrentIndex(1)
            app.processEvents()
            assert win.research_panel.stack.currentWidget().horizontalScrollBar().maximum() == 0
            assert win.tabs.geometry().right() < win.splitter.width()
        win.tabs.setCurrentIndex(0)
        digest = win.selected_entry["sha256"]
        assert digest not in win.hash_label.text()
        assert digest in win.source_details.toPlainText()
        win.copy_hash()
        assert app.clipboard().text() == digest
    finally:
        win.dirty = False
        win.close()


def test_preferences_and_research_context_survive_language_rebuild_and_restart(app):
    win = MainWindow("en", root=ROOT, recovery=False)
    win.show()
    panel = win.research_panel
    panel.device.setCurrentIndex(panel.device.findData("cpu"))
    win.tabs.setCurrentWidget(panel)
    panel.mode.setCurrentIndex(2)
    win.change_preference("theme", "dark")
    win.change_preference("quality", "light")
    win.submit(lambda: time.sleep(.06), key="test-long-job")
    win.language_combo.setCurrentIndex(0)
    assert win.language_combo.currentData() == win.language == "en"
    drain(win, app)
    win.language_combo.setCurrentIndex(0)
    assert win.language_combo.currentData() == win.language == "ko"
    assert win.tabs.currentWidget() is win.research_panel
    assert win.research_panel.mode.currentIndex() == 2
    assert win.research_panel.device.currentData() == "cpu"
    assert not win.dirty
    win.close()
    fresh = MainWindow(root=ROOT, recovery=False)
    try:
        assert fresh.language == "ko" and fresh.preferences.get("theme") == "dark"
        assert fresh.view.graphics_quality == "light"
        assert fresh.research_panel.device.currentData() == "cpu"
        assert "theme" not in fresh.portable_state()["native_desktop"]
    finally:
        fresh.close()


def test_settings_open_compute_probe_does_not_connect_remote_unless_requested(app, monkeypatch):
    records = [{"id": "cpu", "device_name": "Test CPU", "available": True},
               {"id": "cuda", "available": False, "reason": "Test: no CUDA driver"}]
    monkeypatch.setattr("slab_preflight.desktop_devices.probe_devices", lambda: records)
    monkeypatch.setattr("slab_preflight.desktop_devices.remote_capabilities", lambda *_: pytest.fail("unexpected network"))
    win = MainWindow("en", root=ROOT, recovery=False)
    win.show()
    try:
        win.settings_menu.actions()[0].trigger()
        drain(win, app)
        p = win.research_panel
        assert win.tabs.currentWidget() is p and p.mode.currentIndex() == 1
        disabled = p.device.model().item(p.device.findData("cuda"))
        assert not disabled.isEnabled() and "driver" in disabled.toolTip()
        assert "driver" in p.devices.probe_info.text()
        p.devices.location.setCurrentIndex(1)
        p.token.setText("private-credential-sentinel")
        assert "private-credential-sentinel" not in str(win.portable_state())
        settings_file = Path(os.environ["CALCLENS_SETTINGS_FILE"])
        if settings_file.exists():
            assert "private-credential-sentinel" not in settings_file.read_text()
    finally:
        win.dirty = False
        win.close()


def test_run_label_includes_actual_remote_selected_worker_parity_and_fallback():
    text = format_execution({"effective_device": "remote", "requested_device": "remote", "requested_worker_device": "auto",
                             "device_name": "worker CPU", "worker_effective_device": "cpu", "precision": "float64",
                             "parity": {"passed": True}, "elapsed_seconds": .125, "fallback_reasons": [],
                             "worker_execution": {"fallback_reasons": ["no CUDA driver"]}}, "en")
    for value in ("auto → cpu", "float64", "passed", "0.1250 s", "no CUDA driver"):
        assert value in text


def test_lazy_research_tab_prunes_only_removed_structures_before_save(app, tmp_path):
    win = MainWindow("en", root=ROOT, recovery=False, defer_startup=True)
    win.show()
    try:
        win.open_project(ROOT / "examples/research_cases/h2_density/h2-density.calclens.zip", confirm=False)
        drain(win, app)
        hydrogen = win.selected_entry["id"]
        digest = win.selected_entry["sha256"]
        win.open_cifs([ROOT / "examples/hbn.cif"])
        drain(win, app)
        win.select_entry(hydrogen)
        drain(win, app)
        win.remove_selected()
        drain(win, app)
        assert win.research_panel is None
        target = tmp_path / "remaining.calclens.zip"
        assert win.save_project(path=target)
        win.open_project(target, confirm=False)
        drain(win, app)
        assert win.selected_entry["filename"] == "hbn.cif"
        state = win.workspace.project.workspace_state
        assert digest not in state.get("auxiliary", {})
        for key in ("signed", "selections", "differences", "drafts"):
            assert digest not in state.get("native_research", {}).get(key, {})
        win._ensure_research()
        assert win.research_panel.entry["id"] == win.selected_entry["id"]
    finally:
        win.dirty = False
        win.close()


def test_original_cif_bytes_can_be_inspected_and_exported_with_unsupported_geometry(app, tmp_path):
    win = MainWindow("en", root=ROOT, recovery=False)
    win.show()
    try:
        source = ROOT / "examples/partial_occupancy.cif"
        win.open_cifs([source], mode="replace")
        drain(win, app)
        assert win.selected_entry["analysis"]["report"] is None
        win.details_button.click()
        assert source.read_text().splitlines()[0] in win.source_details.toPlainText()
        dest = tmp_path / "original.cif"
        assert win.save_original_cif(path=dest)
        assert dest.read_bytes() == source.read_bytes()
    finally:
        win.dirty = False
        win.close()
