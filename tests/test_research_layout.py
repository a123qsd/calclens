"""Research tools must remain usable at the inspector's actual minimum width."""
import os
from pathlib import Path

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
from PySide6.QtCore import QPoint, Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QCheckBox, QComboBox, QLineEdit, QPushButton

from slab_preflight.desktop import MainWindow


ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture(scope="module")
def app():
    return QApplication.instance() or QApplication([])


def assert_controls_fit(scroll):
    viewport, body = scroll.viewport(), scroll.widget()
    assert scroll.horizontalScrollBar().maximum() == 0
    assert body.width() <= viewport.width()
    for control in body.findChildren(QPushButton):
        if not control.isVisible():
            continue
        point = control.mapTo(body, control.rect().topLeft())
        assert point.x() >= 0
        assert point.x() + control.width() <= viewport.width(), control.text()
    for kind in (QCheckBox, QComboBox, QLineEdit):
        for control in body.findChildren(kind):
            if control.isVisible():
                point = control.mapTo(body, control.rect().topLeft())
                assert point.x() >= 0
                assert point.x() + control.width() <= viewport.width(), control


@pytest.mark.parametrize("language", ["en", "ko"])
@pytest.mark.parametrize("font_pixels", [12, 14])
def test_research_pages_fit_minimum_inspector_after_mode_and_font_changes(app, monkeypatch, language, font_pixels):
    # Layout verification must not depend on a background driver probe finishing.
    monkeypatch.setattr("slab_preflight.desktop_devices.DeviceControls.ensure_local_probe", lambda _self: None)
    window = MainWindow(language, root=ROOT, recovery=False)
    window.resize(1366, 768)
    window.show()
    app.processEvents()
    panel = window.research_panel
    window.tabs.setCurrentWidget(panel)
    panel.setStyleSheet(f"QWidget {{ font-size: {font_pixels}px; }}")
    try:
        for inspector_width in (230, 244, 310):
            window.splitter.setSizes([195, window.splitter.width() - 195 - inspector_width - 12, inspector_width])
            for mode in (0, 1, 2, 3, 1):
                panel.mode.setCurrentIndex(mode)
                app.processEvents()
                assert_controls_fit(panel.stack.currentWidget())
            panel.devices.location.setCurrentIndex(panel.devices.location.findData("remote"))
            app.processEvents()
            assert_controls_fit(panel.stack.currentWidget())
            assert panel.url.width() > 30 and panel.token.width() > 30
            panel.devices.location.setCurrentIndex(panel.devices.location.findData("local"))
            app.processEvents()
        # Stacking/wrapping must retain the complete labels and editable state.
        expected = "Open H₂ calculation example" if language == "en" else "H₂ 실제 계산 예제 열기"
        button = next(button for button in panel.findChildren(QPushButton) if button.accessibleName() == expected)
        assert "".join(button.text().split()) == "".join(expected.split())
        scroll = panel.stack.currentWidget()
        scroll.ensureWidgetVisible(panel.method)
        panel.method.setFocus()
        QTest.keyClicks(panel.method, "PBEsol")
        assert panel.method.text() == "PBEsol"
        scroll.ensureWidgetVisible(panel.frozen)
        QTest.mouseClick(panel.frozen, Qt.MouseButton.LeftButton, pos=QPoint(6, panel.frozen.height() // 2))
        assert panel.frozen.isChecked()
        app.processEvents()
        app.processEvents()
        wrapping = []
        original = type(panel)._wrap_control_text

        def counted(*args):
            wrapping.append(True)
            return original(*args)

        monkeypatch.setattr(type(panel), "_wrap_control_text", staticmethod(counted))
        for _ in range(5):
            panel._fit_rows()
            window.statusBar().showMessage("Unrelated status update")
            app.processEvents()
        assert wrapping == []
    finally:
        window.dirty = False
        window.close()
        app.processEvents()
