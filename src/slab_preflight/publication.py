"""Print-sized scientific figures and their embedded source records."""
from __future__ import annotations

import json
import math
from pathlib import Path

from PySide6.QtCore import QIODevice, QMarginsF, QPointF, QRectF, QSaveFile, QSizeF, Qt
from PySide6.QtGui import QColor, QFont, QImage, QPageLayout, QPageSize, QPainter, QPdfWriter, QPen
from PySide6.QtWidgets import QCheckBox, QComboBox, QDialog, QDialogButtonBox, QFormLayout, QLabel

from . import __version__


class FigureDialog(QDialog):
    def __init__(self, window, *, profile=False):
        super().__init__(window)
        t = window.text
        self.setWindowTitle(t("논문용 그림 내보내기", "Export publication figure"))
        form = QFormLayout(self)
        self.width_choice = QComboBox()
        for mm in (85, 180):
            self.width_choice.addItem(f"{mm} mm", mm)
        self.dpi_choice = QComboBox()
        for dpi in (300, 600):
            self.dpi_choice.addItem(f"{dpi} dpi", dpi)
        self.format_choice = QComboBox()
        self.format_choice.addItems(["PNG", "PDF"])
        self.transparent = QCheckBox(t("투명 배경", "Transparent background"))
        self.scale_bar = QCheckBox(t("길이 눈금 표시 (Å)", "Include scale bar (Å)"))
        self.scale_bar.setChecked(True)
        self.format_choice.currentTextChanged.connect(
            lambda fmt: self.transparent.setEnabled(fmt == "PNG"))
        form.addRow(t("인쇄 너비", "Print width"), self.width_choice)
        form.addRow(t("해상도", "Resolution"), self.dpi_choice)
        form.addRow(t("파일 형식", "File format"), self.format_choice)
        form.addRow(self.transparent)
        if not profile:
            form.addRow(self.scale_bar)
        self.dimensions = QLabel()
        for control in (self.width_choice, self.dpi_choice):
            control.currentIndexChanged.connect(self._dimensions)
        self._dimensions()
        form.addRow(self.dimensions)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Save | QDialogButtonBox.StandardButton.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        form.addRow(buttons)

    def _dimensions(self):
        mm, dpi = self.width_choice.currentData(), self.dpi_choice.currentData()
        self.dimensions.setText(f"{mm} × {mm * .75:g} mm   ·   {round(mm*dpi/25.4)} × {round(mm*.75*dpi/25.4)} px")


def _scale_bar(width, pixels_per_angstrom):
    target = width * 0.21 / pixels_per_angstrom
    power = 10 ** math.floor(math.log10(target))
    length = max(step * power for step in (1, 2, 5) if step * power <= target * (1 + 1e-12))
    return {"angstrom": length, "pixels": length * pixels_per_angstrom}


def _paint_figure(painter, scene, width, height, dpi, bar):
    painter.drawImage(QRectF(0, 0, width, scene.height()), scene)
    if bar is None:
        return
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    mm = dpi / 25.4
    x, y = 4 * mm, height - 3 * mm
    painter.setPen(QPen(QColor("#26333c"), 0.35 * mm, Qt.PenStyle.SolidLine, Qt.PenCapStyle.FlatCap))
    painter.drawLine(QPointF(x, y), QPointF(x + bar["pixels"], y))
    font = QFont("Arial")
    font.setPixelSize(round(8 * dpi / 72))
    painter.setFont(font)
    painter.drawText(QPointF(x, y - 0.9 * mm), f"{bar['angstrom']:g} Å")


def _dimensions(path, width_mm, dpi, transparent):
    fmt = Path(path).suffix.lower()
    if (fmt not in (".pdf", ".png") or width_mm not in (85, 180) or dpi not in (300, 600)
            or (transparent and fmt == ".pdf")):
        raise ValueError("Choose PNG or PDF, 85 or 180 mm, and 300 or 600 dpi. Transparency is available for PNG.")
    return round(width_mm * dpi / 25.4), round(width_mm * .75 * dpi / 25.4)


def export_figure(view, path, *, width_mm=85, dpi=300, transparent=False, scale_bar=True):
    """Export a structure at the desired physical scale and retain its camera."""
    if not view.report:
        raise ValueError("Open a supported structure before exporting a figure.")
    width, height = _dimensions(path, width_mm, dpi, transparent)
    scene_height = height - round(9 * dpi / 25.4) if scale_bar else height
    background = "transparent" if transparent else "white"
    scene = view.render_scene_image(width, scene_height, quality="high", background=background,
                                    logical_width=width_mm * 96 / 25.4)
    projection = json.loads(scene.text("CalcLens scene"))
    bar = _scale_bar(width, projection["pixels_per_angstrom"]) if scale_bar else None
    provenance = {
        "source": view.metadata,
        "camera": view.view_state(), "charge": view.charge_metadata, "surface": view.surface_metadata,
        "surface_layers": [{key: layer[key] for key in ("label", "opacity", "color")} for layer in view.surfaces],
        "selected_atoms_zero_based": list(view.selected_atoms), "measurement": view.selected_contact,
        "figure": {"kind": "structure", "scene_height_px": scene_height,
                   "quality": "high", "scale_bar": bar, "projection": projection},
    }
    def paint(painter, page_width, page_height):
        _paint_figure(painter, scene, page_width, page_height, dpi, bar)
    return write_print_figure(path, width_mm=width_mm, dpi=dpi, transparent=transparent,
                              record=provenance, paint=paint)


def write_print_figure(path, *, width_mm, dpi, transparent, record, paint):
    """Paint into a lossless PNG or one physical PDF page and atomically commit it."""
    width, height = _dimensions(path, width_mm, dpi, transparent)
    fmt = Path(path).suffix.lower()
    provenance = {**record, "calclens_version": __version__, "schema_version": 1, "figure": {
        **record.get("figure", {}), "format": fmt[1:], "width_mm": width_mm, "height_mm": width_mm * .75,
        "dpi": dpi, "width_px": width, "height_px": height, "background": "transparent" if transparent else "white",
    }}
    serialized = json.dumps(provenance, ensure_ascii=False, allow_nan=False, indent=2)
    output = QSaveFile(str(path))
    if not output.open(QIODevice.OpenModeFlag.WriteOnly):
        raise OSError(output.errorString())
    try:
        if fmt == ".png":
            page = QImage(width, height, QImage.Format.Format_ARGB32_Premultiplied)
            if page.isNull():
                raise OSError("Could not allocate the requested figure size.")
            page.fill(Qt.GlobalColor.transparent if transparent else Qt.GlobalColor.white)
            page.setDotsPerMeterX(round(dpi / 0.0254))
            page.setDotsPerMeterY(round(dpi / 0.0254))
            painter = QPainter(page)
            try:
                paint(painter, width, height)
            finally:
                painter.end()
            page.setText("CalcLens provenance", serialized)
            if not page.save(output, "PNG"):
                raise OSError("Could not write the PNG figure.")
        else:
            writer = QPdfWriter(output)
            writer.setCreator(f"CalcLens {__version__}")
            writer.setTitle(str(record.get("title") or record.get("source", {}).get("filename") or "CalcLens figure"))
            writer.setResolution(dpi)
            paper = QPageSize(QSizeF(width_mm, width_mm * .75), QPageSize.Unit.Millimeter,
                              "CalcLens figure", QPageSize.SizeMatchPolicy.ExactMatch)
            writer.setPageLayout(QPageLayout(paper, QPageLayout.Orientation.Portrait, QMarginsF(),
                                             QPageLayout.Unit.Millimeter))
            writer.addFileAttachment("calclens-figure.json", serialized.encode(), "application/json")
            painter = QPainter(writer)
            try:
                if not painter.isActive():
                    raise OSError("Could not open the PDF page for painting.")
                painter.scale(writer.width() / width, writer.height() / height)
                paint(painter, width, height)
            finally:
                painter.end()
            del writer  # Flush the PDF trailer before committing the file.
        if not output.commit():
            raise OSError(output.errorString())
    except BaseException:
        output.cancelWriting()
        raise
    return provenance
