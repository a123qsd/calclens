"""Native, software-rendered structural viewport. No browser or web runtime."""
from __future__ import annotations

from itertools import product
import json
import math
from pathlib import Path

import numpy as np
from ase.data import atomic_numbers, covalent_radii
from PySide6.QtCore import QPointF, QRectF, Qt, Signal
from PySide6.QtGui import (
    QColor, QFont, QFontMetricsF, QImage, QLinearGradient, QPainter, QPen, QPolygonF, QRadialGradient,
)
from PySide6.QtWidgets import QWidget


ELEMENT_COLORS = {
    "H": "#e5eaf0", "B": "#e6a188", "C": "#526879", "N": "#547bd8",
    "O": "#e87770", "F": "#73b9a0", "Na": "#b09ce1", "Mg": "#94c889",
    "Al": "#a9b6c5", "Si": "#bda18b", "P": "#e9a359", "S": "#dfbe4d",
    "Cl": "#7cb991", "Fe": "#ce8a6a", "Cu": "#bd8e6c", "Zn": "#a5a4bf",
    "Se": "#c58b5f", "Mo": "#7e9fb5", "W": "#9aacc2",
}


def _color(value, fallback="#89a1b5"):
    result = QColor(str(value))
    return result if result.isValid() else QColor(fallback)


class StructureView(QWidget):
    """Rotatable 3-D scene with exact atom picking and provenance-rich PNGs.

    Mesh vertices use the report's Cartesian coordinate system in ångström.
    Faces are triangles. Charge arrays retain missing values as unknown.
    """

    atomPicked = Signal(int)
    viewChanged = Signal()
    MAX_SURFACE_FACES = 30000

    def __init__(self, parent=None, *, language="ko"):
        super().__init__(parent)
        self.language = language
        self.setObjectName("structureView")
        self.setMinimumSize(300, 280)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.setMouseTracking(True)
        self.report = None
        self.metadata = {}
        self.charge_metadata = {}
        self.surface_metadata = {}
        self.charges = None
        self.surfaces = []
        self.positions = np.zeros((0, 3))
        self.cell = np.eye(3)
        self.elements = []
        self.yaw = 0.55
        self.pitch = -0.35
        self.roll = 0.0
        self.zoom = 1.0
        self.pan = np.zeros(2)
        self.show_cell = True
        self.show_bonds = True
        self.show_gap = False
        self.show_labels = True
        self.selected_atoms = []
        self.selected_contact = None
        self._last_pointer = None
        self._press_pointer = None
        self._projected_atoms = []
        self._guides = []
        self._hover = -1

    def tr_text(self, ko, en):
        return ko if self.language == "ko" else en

    def set_structure(self, report, metadata=None):
        self.report = report
        self.metadata = dict(metadata or {})
        self.clear_electronic()
        self.selected_atoms = []
        self.selected_contact = None
        if report is None:
            self.positions = np.zeros((0, 3))
            self.elements = []
            self.cell = np.eye(3)
            self._guides = []
        else:
            self.positions = np.asarray(report["positions"], dtype=float)
            self.cell = np.asarray(report["cell"], dtype=float)
            self.elements = list(report["elements"])
            self._guides = self._contact_guides()
        self.update()

    def _contact_guides(self):
        """Displayed-site distance guides, not asserted chemical bonds or MICs."""
        count = len(self.positions)
        if count < 2:
            return []
        radii = np.array([covalent_radii[atomic_numbers[element]] for element in self.elements])
        pairs = []
        for first in range(count - 1):
            delta = self.positions[first + 1:] - self.positions[first]
            distances = np.linalg.norm(delta, axis=1)
            limits = 1.22 * (radii[first] + radii[first + 1:])
            pairs.extend((first, first + 1 + int(offset))
                         for offset in np.flatnonzero((distances > 0.1) & (distances < limits)))
        return pairs

    def set_charges(self, values=None, metadata=None):
        metadata = dict(metadata or {})
        if "color_extent" in metadata:
            extent = metadata["color_extent"]
            if type(extent) not in (int, float) or not math.isfinite(extent) or extent <= 0:
                raise ValueError("Charge color extent must be a finite positive number.")
        if values is None:
            self.charges = None
        else:
            if len(values) != len(self.positions):
                raise ValueError("Charge assignments must match the displayed atom count.")
            charges = []
            for value in values:
                if value is None:
                    charges.append(None)
                elif isinstance(value, (int, float)) and math.isfinite(value):
                    charges.append(float(value))
                else:
                    raise ValueError("Each charge must be a finite number or unknown (None).")
            self.charges = charges
        self.charge_metadata = metadata
        self.update()

    def set_surfaces(self, surfaces=None, metadata=None):
        checked = []
        total_faces = 0
        for surface in surfaces or []:
            vertices = np.asarray(surface["vertices"], dtype=float)
            raw_faces = np.asarray(surface["faces"])
            if vertices.ndim != 2 or vertices.shape[1] != 3 or not np.isfinite(vertices).all():
                raise ValueError("Surface vertices must be finite Cartesian x/y/z coordinates.")
            if raw_faces.ndim != 2 or raw_faces.shape[1] != 3 or raw_faces.dtype.kind not in "iu":
                raise ValueError("Surface faces must contain three integer vertex indices.")
            faces = raw_faces.astype(np.int64)
            if faces.size and (faces.min() < 0 or faces.max() >= len(vertices)):
                raise ValueError("Surface face index is outside the vertex array.")
            total_faces += len(faces)
            if total_faces > self.MAX_SURFACE_FACES:
                raise ValueError(f"Native surfaces support at most {self.MAX_SURFACE_FACES} triangles.")
            opacity = float(surface.get("opacity", 0.48))
            if not math.isfinite(opacity) or not 0 <= opacity <= 1:
                raise ValueError("Surface opacity must be between zero and one.")
            checked.append({
                "vertices": vertices, "faces": faces,
                "color": str(surface.get("color", "#4ca8ab")),
                "opacity": opacity, "label": str(surface.get("label", "Imported surface")),
            })
        self.surfaces = checked
        self.surface_metadata = dict(metadata or {})
        self.update()

    def clear_electronic(self):
        self.charges = None
        self.surfaces = []
        self.charge_metadata = {}
        self.surface_metadata = {}
        self.update()

    def reset_view(self, preset="perspective"):
        self.yaw, self.pitch = {
            "perspective": (0.55, -0.35), "top": (0.0, 0.0),
            "front": (0.0, -math.pi / 2), "side": (-math.pi / 2, -math.pi / 2),
        }.get(preset, (0.55, -0.35))
        self.roll = 0.0
        self.zoom = 1.0
        self.pan = np.zeros(2)
        self.update()
        self.viewChanged.emit()

    def view_state(self):
        return {
            "yaw": self.yaw, "pitch": self.pitch, "roll": self.roll, "zoom": self.zoom,
            "pan": self.pan.tolist(), "cell": self.show_cell, "bonds": self.show_bonds,
            "gap": self.show_gap, "labels": self.show_labels,
            "projection": "orthographic",
        }

    def restore_view_state(self, state):
        if not isinstance(state, dict):
            return
        for key in ("yaw", "pitch", "roll", "zoom"):
            value = state.get(key)
            if type(value) in (int, float) and math.isfinite(value):
                setattr(self, key, max(0.25, min(8.0, value)) if key == "zoom" else value)
        pan = state.get("pan")
        if (isinstance(pan, list) and len(pan) == 2
                and all(type(item) in (int, float) and math.isfinite(item) for item in pan)):
            self.pan = np.clip(np.array(pan, dtype=float), -2000, 2000)
        for key, attribute in (("cell", "show_cell"), ("bonds", "show_bonds"),
                               ("gap", "show_gap"), ("labels", "show_labels")):
            if type(state.get(key)) is bool:
                setattr(self, attribute, state[key])
        self.update()

    def set_selection(self, indices):
        self.selected_atoms = [int(index) for index in indices if 0 <= index < len(self.positions)][-2:]
        self.selected_contact = None
        self.update()

    def set_contact(self, contact=None):
        self.selected_contact = dict(contact) if contact else None
        self.update()

    def _transform(self, points):
        cy, sy = math.cos(self.yaw), math.sin(self.yaw)
        cp, sp = math.cos(self.pitch), math.sin(self.pitch)
        cr, sr = math.cos(self.roll), math.sin(self.roll)
        rotation = (np.array([[1, 0, 0], [0, cp, -sp], [0, sp, cp]])
                    @ np.array([[cr, 0, sr], [0, 1, 0], [-sr, 0, cr]])
                    @ np.array([[cy, -sy, 0], [sy, cy, 0], [0, 0, 1]]))
        center = self.cell.sum(axis=0) / 2 if self.show_cell else self.positions.mean(axis=0)
        return (np.asarray(points) - center) @ rotation.T

    def _projection(self, rect):
        corners = np.array(list(product((0, 1), repeat=3))) @ self.cell
        bounds = np.vstack([corners if self.show_cell else self.positions,
                            *(surface["vertices"] for surface in self.surfaces)])
        transformed = self._transform(bounds)
        extent = np.ptp(transformed[:, :2], axis=0)
        scale = 0.76 * min(rect.width() / max(extent[0], 2), rect.height() / max(extent[1], 2))
        scale *= self.zoom
        center = (transformed[:, :2].min(axis=0) + transformed[:, :2].max(axis=0)) / 2
        origin = np.array([rect.center().x(), rect.center().y()]) + self.pan - center * np.array([scale, -scale])

        def project(points):
            rotated = self._transform(points)
            projected = rotated[:, :2] * np.array([scale, -scale]) + origin
            return projected, rotated[:, 2]

        return project, scale, corners

    def _atom_color(self, index):
        if self.charges is None:
            return _color(ELEMENT_COLORS.get(self.elements[index], "#8faab5"))
        charge = self.charges[index]
        if charge is None:
            return QColor("#a6afb8")
        maximum = self._charge_extent()
        fraction = min(1, abs(charge) / max(maximum, 1e-12))
        end = QColor("#dd746c" if charge > 0 else "#568fc6")
        start = QColor("#e9edf0")
        return QColor(*(int(start_component + fraction * (end_component - start_component))
                        for start_component, end_component in zip(start.getRgb()[:3], end.getRgb()[:3])))

    def _charge_extent(self):
        return self.charge_metadata.get("color_extent") or max(
            [abs(value) for value in self.charges or [] if value is not None] or [1.0])

    def _charge_description(self):
        kind = self.charge_metadata.get("kind", "partial_charge")
        oxidation = kind in ("oxidation_state", "oxidation")
        labels = {"partial_charge": ("부분 전하", "Partial charge"), "formal_charge": ("형식 전하", "Formal charge"),
                  "ionic_charge": ("이온 전하", "Ionic charge"), "oxidation_state": ("산화수", "Oxidation state"),
                  "oxidation": ("산화수", "Oxidation state")}
        label = self.tr_text(*labels.get(kind, ("전하 값", "Charge assignment")))
        units = self.tr_text("무차원", "dimensionless") if oxidation else str(self.charge_metadata.get("units", "e"))
        return label, units

    def paintEvent(self, event):
        painter = QPainter(self)
        self._paint(painter, QRectF(self.rect()), export=False)
        painter.end()

    def _paint(self, painter, rect, *, export=False):
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        background = QLinearGradient(rect.topLeft(), rect.bottomRight())
        background.setColorAt(0, QColor("#f8fbfd"))
        background.setColorAt(1, QColor("#eaf1f4"))
        painter.fillRect(rect, background)
        scene = rect.adjusted(22, 48, -22, -80 if self.surfaces else -55)
        painter.setFont(QFont("Arial", 10))
        painter.setPen(QColor("#607481"))
        title = str(self.metadata.get("filename", self.tr_text("구조", "Structure")))
        painter.drawText(rect.adjusted(22, 15, -22, 0), Qt.AlignmentFlag.AlignTop, title)
        if not self.report or not len(self.positions):
            painter.setPen(QColor("#738a99"))
            painter.drawText(scene, Qt.AlignmentFlag.AlignCenter,
                             self.tr_text("CIF 파일을 열어 구조를 확인하세요", "Open a CIF to inspect its structure"))
            return
        project, scale, corners = self._projection(scene)
        points, depths = project(self.positions)
        vertices, _ = project(corners)
        if self.show_gap:
            self._draw_gap(painter, project)
        if self.show_cell:
            pen = QPen(QColor("#a1b5c2"), 1.15)
            painter.setPen(pen)
            for index, corner in enumerate(product((0, 1), repeat=3)):
                for axis in range(3):
                    if corner[axis] == 0:
                        other = list(corner)
                        other[axis] = 1
                        other_index = other[0] * 4 + other[1] * 2 + other[2]
                        painter.drawLine(QPointF(*vertices[index]), QPointF(*vertices[other_index]))
            origin, _ = project(np.zeros((1, 3)))
            for axis, color in enumerate(("#be7971", "#7ba387", "#6f94b8")):
                endpoint, _ = project([self.cell[axis]])
                painter.setPen(QPen(QColor(color), 2))
                painter.drawLine(QPointF(*origin[0]), QPointF(*endpoint[0]))
                painter.drawText(QPointF(*endpoint[0]) + QPointF(7, -5), "abc"[axis])
        if self.show_bonds:
            painter.setPen(QPen(QColor("#aebfc9"), 4, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))
            for first, second in self._guides:
                painter.drawLine(QPointF(*points[first]), QPointF(*points[second]))
        self._draw_surfaces(painter, project)
        if self.selected_contact:
            contact = self.selected_contact
            endpoints = np.array([
                self.positions[contact["i"]] + np.asarray(contact.get("start_shift", [0, 0, 0])) @ self.cell,
                self.positions[contact["j"]] + np.asarray(contact.get("end_shift", contact["shift"])) @ self.cell,
            ])
            selected_points, _ = project(endpoints)
            painter.setPen(QPen(QColor("#c28346"), 2, Qt.PenStyle.DashLine))
            painter.drawLine(QPointF(*selected_points[0]), QPointF(*selected_points[1]))
            painter.setBrush(Qt.BrushStyle.NoBrush)
            for point in selected_points:
                painter.drawEllipse(QPointF(*point), 6, 6)
            midpoint = selected_points.mean(axis=0)
            painter.setFont(QFont("Arial", 10, QFont.Weight.DemiBold))
            painter.drawText(QPointF(*midpoint) + QPointF(8, -8), f"{contact['distance_angstrom']:.3f} Å")
        painted = []
        for index in np.argsort(depths):
            index = int(index)
            x, y = points[index]
            radius = min(29, max(7.5, scale * (0.24 + covalent_radii[atomic_numbers[self.elements[index]]] * 0.27)))
            color = self._atom_color(index)
            if index in self.selected_atoms or index == self._hover:
                painter.setPen(QPen(QColor("#c7964d"), 2.4))
                painter.setBrush(Qt.BrushStyle.NoBrush)
                painter.drawEllipse(QPointF(x, y), radius + 5, radius + 5)
            gradient = QRadialGradient(QPointF(x - radius * 0.35, y - radius * 0.4), radius * 1.7)
            gradient.setColorAt(0, color.lighter(150))
            gradient.setColorAt(0.5, color)
            gradient.setColorAt(1, color.darker(145))
            painter.setPen(QPen(color.darker(110), 0.7))
            painter.setBrush(gradient)
            painter.drawEllipse(QPointF(x, y), radius, radius)
            if self.show_labels:
                painter.setPen(QColor("#f8fbfd") if color.lightness() < 155 else QColor("#243f50"))
                painter.setFont(QFont("Arial", max(8, int(radius * 0.52)), QFont.Weight.DemiBold))
                painter.drawText(QRectF(x - radius, y - radius, radius * 2, radius * 2),
                                 Qt.AlignmentFlag.AlignCenter, self.elements[index])
            painted.append((index, x, y, radius))
        if not export:
            self._projected_atoms = painted
        self._draw_legend(painter, rect, export=export)

    def _draw_gap(self, painter, project):
        axis = int(self.report.get("normal_axis_index", 2))
        others = [index for index in range(3) if index != axis]
        start, end = (self.report["metrics"][key] for key in ("gap_start_fraction", "gap_end_fraction"))
        intervals = [(start, end)] if end > start else [(start, 1.0), (0.0, end)]
        intervals = [(lo, hi) for lo, hi in intervals if hi > lo]
        for lo, hi in intervals:
            side = np.zeros((4, 3))
            side[:, axis] = [lo, lo, hi, hi]
            side[:, others[0]] = [0, 1, 1, 0]
            points, _ = project(side @ self.cell)
            painter.setPen(QPen(QColor(91, 164, 152, 80), 0.8, Qt.PenStyle.DashLine))
            painter.setBrush(QColor(91, 164, 152, 17))
            painter.drawPolygon(QPolygonF([QPointF(*point) for point in points]))
        for height in (start, end):
            fractional = np.zeros((4, 3))
            fractional[:, axis] = height
            fractional[:, others] = [[0, 0], [1, 0], [1, 1], [0, 1]]
            points, _ = project(fractional @ self.cell)
            painter.setPen(QPen(QColor("#7ab6ad"), 1, Qt.PenStyle.DashLine))
            painter.setBrush(QColor(91, 164, 152, 28))
            painter.drawPolygon(QPolygonF([QPointF(*point) for point in points]))
        if intervals:
            lo, hi = max(intervals, key=lambda interval: interval[1] - interval[0])
            location = np.zeros((1, 3))
            location[0, axis] = (lo + hi) / 2
            location[0, others[0]] = 0.5
            point, _ = project(location @ self.cell)
            painter.setPen(QColor("#568a82"))
            painter.setFont(QFont("Arial", 9))
            painter.drawText(QPointF(*point[0]) + QPointF(7, -6), self.tr_text("핵 간격 ", "Nuclei gap ")
                             + f"{self.report['metrics']['nuclei_gap_angstrom']:.3f} Å")

    def _draw_surfaces(self, painter, project):
        triangles = []
        for surface in self.surfaces:
            projected, depths = project(surface["vertices"])
            for face in surface["faces"]:
                triangles.append((float(depths[face].mean()), projected[face], surface))
        for _, points, surface in sorted(triangles, key=lambda item: item[0]):
            color = _color(surface["color"])
            color.setAlphaF(surface["opacity"])
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(color)
            painter.drawPolygon(QPolygonF([QPointF(*point) for point in points]))

    def _draw_legend(self, painter, rect, *, export):
        painter.setFont(QFont("Arial", 9))
        y = rect.bottom() - 35
        x = rect.left() + 22
        if self.surfaces:
            painter.setPen(QColor("#506978"))
            surface_y = y - 25
            kind_label = self._surface_description()
            painter.drawText(QPointF(x, surface_y + 4), kind_label)
            x += painter.fontMetrics().horizontalAdvance(kind_label) + 17
            for surface in self.surfaces:
                label = surface["label"].replace("e/angstrom^3", "e/Å³").replace("angstrom^-3/2", "Å⁻³/²")
                painter.setBrush(_color(surface["color"]))
                painter.setPen(Qt.PenStyle.NoPen)
                painter.drawEllipse(QPointF(x + 4, surface_y), 4, 4)
                painter.setPen(QColor("#506978"))
                painter.drawText(QPointF(x + 14, surface_y + 4), label)
                x += painter.fontMetrics().horizontalAdvance(label) + 29
            x = rect.left() + 22
        if self.charges is None:
            for element in dict.fromkeys(self.elements):
                painter.setBrush(_color(ELEMENT_COLORS.get(element, "#8faab5")))
                painter.setPen(Qt.PenStyle.NoPen)
                painter.drawEllipse(QPointF(x + 5, y), 4, 4)
                painter.setPen(QColor("#506978"))
                painter.drawText(QPointF(x + 17, y + 4), element)
                x += 54
        else:
            painter.setPen(QColor("#506978"))
            label, units = self._charge_description()
            extent = self._charge_extent()
            painter.drawText(QPointF(x, y + 4), f"{label} [−{extent:g}, +{extent:g}] {units} · " + self.tr_text(
                "파랑 − / 빨강 + / 회색 미상", "blue − / red + / gray unknown"))
        painter.setFont(QFont("Arial", 8))
        painter.setPen(QColor("#718694"))
        hint = self.tr_text("드래그 회전 · 휠 확대 · 원자 두 개 선택", "Drag to rotate · scroll to zoom · pick two atoms")
        painter.drawText(QPointF(rect.left() + 22, y + 25), hint if not export else self.tr_text(
            "연결선은 거리 기반 표시이며 화학 결합 판정이 아닙니다. 간격은 원자핵 기준입니다.",
            "Lines are distance guides, not chemical bonds. Gap planes refer to nuclei."))
    def _export_annotations(self):
        lines = [
            "CalcLens · annotated structure image",
            f"File: {self.metadata.get('filename', '—')}",
            f"SHA-256: {self.metadata.get('sha256', '—')}",
            f"Normal axis: {self.report.get('normal_axis', 'c')} · Cartesian lengths: Å · "
            "Gray cell edges; a red / b green / c blue; gold circles mark selected images.",
            ("Element legend: " + "; ".join(f"{element} {ELEMENT_COLORS.get(element, '#8faab5')}"
                                             for element in dict.fromkeys(self.elements))) if self.charges is None else
            "Elements: " + ", ".join(dict.fromkeys(self.elements)) + " (colors follow selected assignments).",
            "Distance guides use displayed atoms and covalent radii; they do not establish chemical bonds. "
            "Gap planes mark the largest nuclei gap, not an electron-density vacuum boundary.",
        ]
        if self.charges is not None:
            label, units = self._charge_description()
            extent = self._charge_extent()
            lines.append(f"{label}: [−{extent:g}, +{extent:g}] {units}; blue negative / red positive / gray unknown. "
                         "Values beyond the range use endpoint colors. Oxidation states are not partial charges.")
            lines.append("Charge data: " + json.dumps(self.charge_metadata, ensure_ascii=False, sort_keys=True, default=str))
        if self.surfaces:
            lines.append("Field quantity: " + self._surface_description())
            lines.append("Surface legend: " + "; ".join(
                f"{surface['label']} {surface['color']} opacity {surface['opacity']:g}" for surface in self.surfaces))
            lines.append("Surface data: " + json.dumps(self.surface_metadata, ensure_ascii=False, sort_keys=True, default=str))
            kind = self.surface_metadata.get("kind")
            if kind == "orbital":
                lines.append("Orbital colors denote wavefunction phase sign, not positive and negative electric charge or total electron density.")
            elif kind == "difference_density":
                lines.append("Positive and negative difference-density lobes show accumulation and depletion relative to the declared frozen fragments (ρAB − ρA − ρB). They are not orbital phases.")
            elif kind == "spin_density":
                lines.append("Colors denote signed spin density under the source convention, not electric charge or orbital phases.")
            elif kind == "density":
                lines.append("This is a total electron-density isosurface. Its color identifies the chosen level; it does not encode an orbital phase or positive electric charge.")
        return "\n".join(lines)

    def _surface_description(self):
        labels = {
            "density": ("총 전자밀도", "Total electron density"),
            "difference_density": ("차이 밀도 Δρ", "Difference density Δρ"),
            "spin_density": ("스핀 밀도", "Spin density"),
            "orbital": ("오비탈 위상", "Orbital phase"),
        }
        return self.tr_text(*labels.get(self.surface_metadata.get("kind"), ("외부 표면", "External surface")))

    def export_png(self, path, metadata=None):
        if self.report is None:
            raise ValueError("A supported structure must be loaded before exporting an image.")
        previous = self.metadata
        self.metadata = {**previous, **(metadata or {})}
        try:
            width, scene_height = 1600, 1200
            font = QFont("Arial")
            font.setPixelSize(17)
            annotations = self._export_annotations()
            flags = Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignTop | Qt.TextFlag.TextWrapAnywhere
            bounds = QFontMetricsF(font).boundingRect(QRectF(0, 0, width - 56, 100000), flags, annotations)
            footer_height = int(math.ceil(bounds.height())) + 46
            if footer_height > 12000:
                raise ValueError("Image annotations exceed the native PNG size limit.")
            image = QImage(width, scene_height + footer_height, QImage.Format.Format_ARGB32_Premultiplied)
            image.fill(QColor("#ffffff"))
            painter = QPainter(image)
            self._paint(painter, QRectF(0, 0, width, scene_height), export=True)
            painter.setFont(font)
            painter.setPen(QColor("#3c5665"))
            painter.drawLine(QPointF(24, scene_height), QPointF(width - 24, scene_height))
            painter.drawText(QRectF(28, scene_height + 20, width - 56, footer_height - 36), flags, annotations)
            painter.end()
            provenance = {
                **self.metadata, "normal_axis": self.report.get("normal_axis"),
                "camera": self.view_state(), "charge": self.charge_metadata,
                "surface": self.surface_metadata,
                "scope": "Supplied geometry; distance guides are not chemical bonds.",
            }
            image.setText("CalcLens provenance", json.dumps(provenance, ensure_ascii=False))
            if not image.save(str(path), "PNG"):
                raise OSError("Could not save the PNG image.")
        finally:
            self.metadata = previous
        return Path(path)

    def _picked(self, point):
        for index, x, y, radius in reversed(self._projected_atoms):
            if (point.x() - x) ** 2 + (point.y() - y) ** 2 <= (radius + 5) ** 2:
                return index
        return -1

    def mousePressEvent(self, event):
        self.setFocus()
        self._last_pointer = event.position()
        self._press_pointer = event.position()
        event.accept()

    def mouseMoveEvent(self, event):
        point = event.position()
        if self._last_pointer is not None and event.buttons():
            delta = point - self._last_pointer
            if event.buttons() & Qt.MouseButton.RightButton or event.modifiers() & Qt.KeyboardModifier.ShiftModifier:
                self.pan += [delta.x(), delta.y()]
            else:
                self.yaw += delta.x() * 0.009
                self.pitch += delta.y() * 0.009
            self._last_pointer = point
            self.viewChanged.emit()
            self.update()
        else:
            hover = self._picked(point)
            if hover != self._hover:
                self._hover = hover
                self.setToolTip(f"{self.elements[hover]} · #{hover + 1}" if hover >= 0 else "")
                self.update()

    def mouseReleaseEvent(self, event):
        if (event.button() == Qt.MouseButton.LeftButton and self._press_pointer is not None
                and (event.position() - self._press_pointer).manhattanLength() < 5):
            index = self._picked(event.position())
            if index >= 0:
                self.atomPicked.emit(index)
        self._last_pointer = None
        self._press_pointer = None

    def wheelEvent(self, event):
        self.zoom = min(8, max(0.25, self.zoom * math.exp(event.angleDelta().y() / 1200)))
        self.update()
        self.viewChanged.emit()
        event.accept()

    def keyPressEvent(self, event):
        if event.key() in (Qt.Key.Key_Plus, Qt.Key.Key_Equal, Qt.Key.Key_Minus):
            self.zoom = min(8, max(0.25, self.zoom * (0.85 if event.key() == Qt.Key.Key_Minus else 1.15)))
            self.update()
            self.viewChanged.emit()
        elif event.key() == Qt.Key.Key_R:
            self.reset_view()
        else:
            super().keyPressEvent(event)
