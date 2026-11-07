"""Capture real native widgets and measure layout/palette on this display backend."""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import platform
import tempfile
import time

from PySide6.QtCore import QEventLoop, QPoint, qVersion
from PySide6.QtGui import QColor, QPalette
from PySide6.QtWidgets import QApplication, QFileDialog
from slab_preflight.desktop import MainWindow
from slab_preflight.desktop_preferences import DesktopPreferences

ROOT = Path(__file__).resolve().parents[1]


def process(app, window):
    until = time.monotonic() + 30
    while window.is_busy and time.monotonic() < until:
        app.processEvents(QEventLoop.ProcessEventsFlag.AllEvents, 20)
        time.sleep(.01)
    assert not window.is_busy
    app.processEvents()


def contrast(pal):
    def luminance(key):
        c = pal.color(QPalette.ColorRole[key])
        rgb = [v / 12.92 if v <= .04045 else ((v + .055) / 1.055) ** 2.4
               for v in (c.redF(), c.greenF(), c.blueF())]
        return sum(a * b for a, b in zip(rgb, (.2126, .7152, .0722)))
    a, b = sorted((luminance("Text"), luminance("Base")))
    return round((b + .05) / (a + .05), 2)


def capture(directory, app):
    result = {"platform": platform.platform(), "backend": app.platformName(), "qt": qVersion(),
              "screen_dpr": app.primaryScreen().devicePixelRatio(), "themes": [], "layouts": []}
    for language in ("ko", "en"):
        for dark in (False, True):
            theme = "dark" if dark else "light"
            pal = QPalette(app.palette())
            pal.setColor(QPalette.ColorRole.Base, QColor("#181c22" if dark else "#ffffff"))
            pal.setColor(QPalette.ColorRole.Text, QColor("#ffffff" if dark else "#202128"))
            app.setPalette(pal)
            DesktopPreferences().set("theme", "system")
            w = MainWindow(language, root=ROOT, recovery=False)
            w.show()
            w.resize(1366, 768)
            w.tabs.setCurrentIndex(1)
            process(app, w)
            def save(widget, name):
                image = widget.grab()
                assert not image.isNull() and image.save(str(directory / (name + ".png")))
            save(w, f"after-{theme}-report-{language}")
            ratio = contrast(w.report_text.palette())
            assert ratio >= 4.5
            result["themes"].append({"lang": language, "theme": theme, "report_contrast": ratio})
            if language == "ko" or dark:
                w.open_compute_settings()
                process(app, w)
                save(w, f"after-{theme}-devices-{language}")
                assert w.tabs.currentWidget() is w.research_panel
            if dark and language == "en":
                dialog = w.create_comparison_dialog()
                dialog.show()
                process(app, w)
                save(dialog, "after-dark-comparison-en")
                dialog.close()
                picker = QFileDialog(w, "Export structure image")
                picker.setAcceptMode(QFileDialog.AcceptMode.AcceptSave)
                picker.setNameFilter("PNG (*.png)")
                picker.selectFile("graphene.png")
                picker.show()
                process(app, w)
                save(picker, "after-dark-export-en")
                picker.close()
                w.open_project(directory / "missing-file.calclens.zip", confirm=False)
                process(app, w)
                assert w.error_label.isVisible()
                save(w, "after-dark-error-en")
                w.error_label.hide()
            w.tabs.setCurrentIndex(0)
            w._compact_panel = "scene"
            for width, height in ((1920, 1080), (1366, 768), (1093, 614), (911, 512), (683, 384)):
                w.resize(width, height)
                process(app, w)
                assert w.size().width() == width and w.size().height() == height
                below_card = w.view.mapTo(w, QPoint(0, w.view.height())).y()
                assert below_card <= height, (width, height, below_card)
                result["layouts"].append({"lang": language, "theme": theme, "requested": [width, height],
                                         "actual": [w.width(), w.height()], "view_bottom": below_card,
                                         "panels": w.splitter.sizes()})
                if language == "ko" and not dark and width in (1366, 683):
                    save(w, f"after-light-{width}x{height}-ko")
                    if width == 683:
                        w._toggle_inspector()
                        process(app, w)
                        save(w, "after-light-683x384-inspector-ko")
            w.dirty = False
            w.close()
            app.processEvents()
    return result


if __name__ == "__main__":
    cli = argparse.ArgumentParser(description=__doc__)
    cli.add_argument("directory", type=Path)
    args = cli.parse_args()
    args.directory.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory() as temp:
        os.environ["CALCLENS_SETTINGS_FILE"] = str(Path(temp) / "capture.ini")
        app = QApplication([])
        details = capture(args.directory, app)
    (args.directory / "native-ui.json").write_text(json.dumps(details, indent=2), encoding="utf-8")
