import json
import os
from pathlib import Path

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
from PySide6.QtGui import QImage
from PySide6.QtWidgets import QApplication

from slab_preflight.desktop import MainWindow


@pytest.fixture
def window():
    app = QApplication.instance() or QApplication([])
    win = MainWindow("en", root=Path(__file__).resolve().parents[1], recovery=False)
    win.view.fit_atoms()
    yield win
    win.dirty = False
    win.close()
    app.processEvents()


def test_print_png_preserves_physical_width_scale_and_source_in_both_resolutions(window, tmp_path):
    original = window.view.view_state()
    scales = []
    for dpi in (300, 600):
        path = tmp_path / f"figure-{dpi}.png"
        assert window.export_publication(path=path, dpi=dpi, transparent=True)
        image = QImage(str(path))
        note = json.loads(image.text("CalcLens provenance"))
        fig = note["figure"]
        assert image.width() == round(85 * dpi / 25.4) and image.height() == round(63.75 * dpi / 25.4)
        assert image.pixelColor(0, 0).alpha() == 0
        assert image.dotsPerMeterX() == image.dotsPerMeterY() == round(dpi / .0254)
        assert note["source"]["sha256"] == window.selected_entry["sha256"]
        assert note["camera"] == original == window.view.view_state()
        scale = fig["projection"]["pixels_per_angstrom"]
        scales.append(scale)
        assert fig["scale_bar"]["pixels"] == pytest.approx(fig["scale_bar"]["angstrom"] * scale)
    assert scales[1] / scales[0] == pytest.approx(2, rel=.004)


def test_one_page_pdf_embeds_provenance_and_failed_export_preserves_destination(window, tmp_path):
    path = tmp_path / "figure.pdf"
    assert window.export_publication(path=path)
    data = path.read_bytes()
    assert data.startswith(b"%PDF-") and b"/EmbeddedFiles" in data and b"%%EOF" in data[-40:]
    assert not window.export_publication(path=path, dpi=120)
    assert path.read_bytes() == data
