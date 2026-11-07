"""Research tools must remain usable at the inspector's actual minimum width."""
import os
import json
from pathlib import Path

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
from PySide6.QtCore import QPoint, Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QCheckBox, QComboBox, QLineEdit, QPushButton, QWidget

from slab_preflight.desktop import MainWindow


ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture(scope="module")
def app():
    return QApplication.instance() or QApplication([])


def _layout_diagnostics(scroll, context):
    viewport, body = scroll.viewport(), scroll.widget()

    def size(value):
        return [value.width(), value.height()]

    def rect(value):
        return [value.x(), value.y(), value.width(), value.height()]

    def widget_record(widget):
        point = widget.mapTo(body, widget.rect().topLeft())
        text = ""
        if isinstance(widget, QLineEdit) and widget.echoMode() != QLineEdit.EchoMode.Normal:
            text = "<redacted credential>"
        elif isinstance(widget, QComboBox):
            text = widget.currentText()
        elif hasattr(widget, "text"):
            text = widget.text()
        elif hasattr(widget, "toPlainText"):
            text = widget.toPlainText()
        return {
            "type": type(widget).__name__, "name": widget.objectName(), "visible": widget.isVisible(),
            "text": text[:1000], "text_length": len(text), "font": widget.font().toString(),
            "body_rect": [point.x(), point.y(), widget.width(), widget.height()],
            "size_hint": size(widget.sizeHint()), "minimum_size_hint": size(widget.minimumSizeHint()),
            "minimum_size": size(widget.minimumSize()), "maximum_size": size(widget.maximumSize()),
            "horizontal_policy": widget.sizePolicy().horizontalPolicy().name,
            "past_viewport": point.x() < 0 or point.x() + widget.width() > viewport.width(),
        }

    def layout_record(layout):
        margins = layout.contentsMargins()
        children = []
        for index in range(layout.count()):
            item = layout.itemAt(index)
            if item.layout() is not None:
                children.append({"index": index, "layout": layout_record(item.layout())})
            elif item.widget() is not None:
                children.append({"index": index, "widget": widget_record(item.widget())})
            else:
                children.append({"index": index, "spacer_minimum": size(item.minimumSize())})
        return {
            "type": type(layout).__name__, "geometry": rect(layout.geometry()),
            "minimum_size": size(layout.minimumSize()), "size_hint": size(layout.sizeHint()),
            "spacing": layout.spacing(), "margins": [margins.left(), margins.top(), margins.right(), margins.bottom()],
            "direction": layout.direction().name if hasattr(layout, "direction") else None,
            "row_wrap": layout.rowWrapPolicy().name if hasattr(layout, "rowWrapPolicy") else None,
            "children": children,
        }

    visible = [widget_record(widget) for widget in body.findChildren(QWidget) if widget.isVisible()]
    diagnostics = {
        "context": context, "scroll_size": size(scroll.size()), "viewport_size": size(viewport.size()),
        "body_size": size(body.size()), "body_size_hint": size(body.sizeHint()),
        "body_minimum_size_hint": size(body.minimumSizeHint()), "body_minimum_size": size(body.minimumSize()),
        "horizontal_scroll_maximum": scroll.horizontalScrollBar().maximum(),
        "vertical_scroll_maximum": scroll.verticalScrollBar().maximum(),
        "past_viewport": [record for record in visible if record["past_viewport"]],
        "visible_widgets": visible, "inner_layouts": layout_record(body.layout()),
    }
    text = "RESEARCH_LAYOUT_DIAGNOSTICS\n" + json.dumps(diagnostics, ensure_ascii=True, indent=2)
    print(text, flush=True)
    return text


def assert_controls_fit(scroll, context):
    viewport, body = scroll.viewport(), scroll.widget()
    assert scroll.horizontalScrollBar().maximum() == 0, _layout_diagnostics(scroll, context)
    assert body.width() <= viewport.width(), _layout_diagnostics(scroll, context)
    for control in body.findChildren(QPushButton):
        if not control.isVisible():
            continue
        point = control.mapTo(body, control.rect().topLeft())
        assert point.x() >= 0, _layout_diagnostics(scroll, context)
        assert point.x() + control.width() <= viewport.width(), _layout_diagnostics(scroll, context)
    for kind in (QCheckBox, QComboBox, QLineEdit):
        for control in body.findChildren(kind):
            if control.isVisible():
                point = control.mapTo(body, control.rect().topLeft())
                assert point.x() >= 0, _layout_diagnostics(scroll, context)
                assert point.x() + control.width() <= viewport.width(), _layout_diagnostics(scroll, context)


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
                assert_controls_fit(panel.stack.currentWidget(), {
                    "language": language, "font_pixels": font_pixels, "inspector_requested": inspector_width,
                    "inspector_actual": window.tabs.width(), "panel_size": [panel.width(), panel.height()],
                    "mode": mode, "mode_name": panel.mode.currentText(), "location": "local",
                })
            panel.devices.location.setCurrentIndex(panel.devices.location.findData("remote"))
            app.processEvents()
            assert_controls_fit(panel.stack.currentWidget(), {
                "language": language, "font_pixels": font_pixels, "inspector_requested": inspector_width,
                "inspector_actual": window.tabs.width(), "panel_size": [panel.width(), panel.height()],
                "mode": panel.mode.currentIndex(), "mode_name": panel.mode.currentText(), "location": "remote",
            })
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
