"""Native, software-rendered structural viewport. No browser or web runtime."""
from __future__ import annotations

from itertools import product
from collections import deque
from html import escape
import json
import math
from pathlib import Path
import time

import numpy as np
from ase.data import atomic_numbers, covalent_radii, vdw_radii
from PySide6.QtCore import QPointF, QRectF, Qt, Signal, QTimer
from PySide6.QtGui import (
    QColor, QFont, QFontMetricsF, QImage, QLinearGradient, QPainter, QTextDocument, QTextOption,
)
from PySide6.QtWidgets import QWidget

from .desktop_raster import Primitive, rasterize


ELEMENT_COLORS = {
    "H": "#e5eaf0", "B": "#e6a188", "C": "#526879", "N": "#547bd8",
    "O": "#e87770", "F": "#73b9a0", "Na": "#b09ce1", "Mg": "#94c889",
    "Al": "#a9b6c5", "Si": "#bda18b", "P": "#e9a359", "S": "#dfbe4d",
    "Cl": "#7cb991", "Fe": "#ce8a6a", "Cu": "#bd8e6c", "Zn": "#a5a4bf",
    "Se": "#c58b5f", "Mo": "#7e9fb5", "W": "#9aacc2",
}

# Software display controls. They do not change atom data, mesh topology, the
# physical isovalue or scientific analysis. Export chooses a separate preset.
GRAPHICS_PRESETS = {
    "light": {"sample_scale": 0.7, "labels": 40, "shaded": False, "antialias": False,
              "interaction_scale": 0.5},
    "balanced": {"sample_scale": 1.0, "labels": 120, "shaded": True, "antialias": True,
                 "interaction_scale": 0.7},
    "high": {"sample_scale": 1.5, "labels": 240, "shaded": True, "antialias": True,
             "interaction_scale": 1.0},
}


def _color(value, fallback="#89a1b5"):
    result = QColor(str(value))
    return result if result.isValid() else QColor(fallback)


def _display_vdw_radius(element):
    number = atomic_numbers[element]
    value = vdw_radii[number] if number < len(vdw_radii) else math.nan
    return float(value) if math.isfinite(value) and value > 0 else float(covalent_radii[number]) * 1.5


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
        self.setMinimumSize(160, 100)
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
        self.graphics_quality = "auto"
        self.representation = "ball-stick"
        self.background = "gradient"
        self._auto_quality = "balanced"
        self._frame_times = deque(maxlen=12)
        self._interacting = False
        self._interaction_timer = QTimer(self)
        self._interaction_timer.setSingleShot(True)
        self._interaction_timer.timeout.connect(self._finish_interaction)
        self._pick_map = None
        self._pick_rect = QRectF()
        self._text_cache = {}
        self._last_render_stats = {}
        self.selected_atoms = []
        self.selected_contact = None
        self._last_pointer = None
        self._press_pointer = None
        self._projected_atoms = []
        self._guides = []
        self._hover = -1

    def set_graphics_quality(self, quality):
        if quality not in ("auto", *GRAPHICS_PRESETS):
            raise ValueError("Graphics quality must be auto, light, balanced or high.")
        self.graphics_quality = quality
        self._frame_times.clear()
        self.update()

    def set_representation(self, representation):
        if representation not in ("ball-stick", "stick", "spacefill"):
            raise ValueError("Choose ball-stick, stick or spacefill representation.")
        self.representation = representation
        self.update()
        self.viewChanged.emit()

    def set_background(self, background):
        if background not in ("gradient", "white", "dark", "transparent"):
            raise ValueError("Choose gradient, white, dark or transparent background.")
        self.background = background
        self.update()
        self.viewChanged.emit()

    def effective_graphics_quality(self):
        if self.graphics_quality != "auto":
            return self.graphics_quality
        complexity = len(self.positions) * 12 + sum(len(surface["faces"]) for surface in self.surfaces)
        if complexity > 18000:
            return "light"
        if self._frame_times:
            mean_ms = sum(self._frame_times) / len(self._frame_times)
            if mean_ms > 70:
                self._auto_quality = "light"
            elif len(self._frame_times) == self._frame_times.maxlen and mean_ms < 18 and complexity < 3000:
                self._auto_quality = "high"
            elif mean_ms < 40 and self._auto_quality == "light":
                self._auto_quality = "balanced"
        return self._auto_quality

    def _finish_interaction(self):
        self._interacting = False
        self.update()

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
        self._pick_map = None
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
            "representation": self.representation, "background": self.background,
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
        if state.get("representation") in ("ball-stick", "stick", "spacefill"):
            self.representation = state["representation"]
        if state.get("background") in ("gradient", "white", "dark", "transparent"):
            self.background = state["background"]
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

    def _projection(self, rect, *, pan_scale=1.0):
        corners = np.array(list(product((0, 1), repeat=3))) @ self.cell
        bounds = np.vstack([corners if self.show_cell else self.positions,
                            *(surface["vertices"] for surface in self.surfaces)])
        if self.representation == "spacefill":
            padding = max(_display_vdw_radius(element) for element in self.elements) * 0.75
            bounds = np.vstack((bounds, self.positions.min(axis=0) - padding, self.positions.max(axis=0) + padding))
        transformed = self._transform(bounds)
        extent = np.ptp(transformed[:, :2], axis=0)
        scale = 0.76 * min(rect.width() / max(extent[0], 2), rect.height() / max(extent[1], 2))
        scale *= self.zoom
        center = (transformed[:, :2].min(axis=0) + transformed[:, :2].max(axis=0)) / 2
        origin = np.array([rect.center().x(), rect.center().y()]) + self.pan * pan_scale - center * np.array([scale, -scale])

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

    def _legend_text(self, *, export=False):
        lines = []
        if self.surfaces:
            surfaces = "; ".join(surface["label"].replace("e/angstrom^3", "e/Å³").replace("angstrom^-3/2", "Å⁻³/²")
                                 + f" · α {surface['opacity']:g}" for surface in self.surfaces)
            lines.append(self._surface_description() + ": " + surfaces)
        if self.charges is None:
            lines.append(self.tr_text("원소: ", "Elements: ") + ", ".join(dict.fromkeys(self.elements)))
        else:
            label, units = self._charge_description()
            extent = self._charge_extent()
            lines.append(f"{label} [−{extent:g}, +{extent:g}] {units} · " + self.tr_text(
                "파랑 − / 빨강 + / 회색 미상", "blue − / red + / gray unknown"))
        lines.append(self.tr_text(
            "연결선은 거리 가이드이며 화학 결합 판정이 아닙니다. 간격은 원자핵 기준입니다." if export else
            "드래그 회전 · 휠 확대 · 원자 두 개 선택",
            "Lines are distance guides, not chemical bonds. Gap planes refer to nuclei." if export else
            "Drag to rotate · scroll to zoom · pick two atoms"))
        return "\n".join(lines)

    def _legend_document(self, font, width, foreground, *, export=False, compact=False):
        rows = []

        def swatch(color, text):
            return '<span style="color:' + _color(color).name() + '">●</span> ' + escape(text)

        if self.surfaces:
            rows.append(escape(self._surface_description()) + ": " + " &nbsp; ".join(
                swatch(surface["color"], surface["label"].replace("e/angstrom^3", "e/Å³").replace("angstrom^-3/2", "Å⁻³/²")
                       + f" · α {surface['opacity']:g}") for surface in self.surfaces))
        if self.charges is None:
            elements = list(dict.fromkeys(self.elements))
            shown = elements[:4] if compact else elements
            rows.append(" &nbsp; ".join(swatch(ELEMENT_COLORS.get(element, "#8faab5"), element) for element in shown)
                        + (f" (+{len(elements) - 4})" if compact and len(elements) > 4 else ""))
        else:
            label, units = self._charge_description()
            extent = self._charge_extent()
            rows.append(escape(f"{label} [−{extent:g}, +{extent:g}] {units}") + " · "
                        + swatch("#568fc6", "−") + " / " + swatch("#dd746c", "+") + " / "
                        + swatch("#a6afb8", self.tr_text("미상", "unknown")))
        if not compact:
            rows.append(escape(self._legend_text(export=export).split("\n")[-1]))
        document = QTextDocument()
        document.setDefaultFont(font)
        document.setDocumentMargin(0)
        option = QTextOption()
        option.setWrapMode(QTextOption.WrapMode.WrapAtWordBoundaryOrAnywhere)
        document.setDefaultTextOption(option)
        document.setHtml('<div style="color:' + foreground.name() + '">' + "<br>".join(rows) + "</div>")
        document.setTextWidth(max(10, width))
        return document

    def _paint(self, painter, rect, *, export=False, quality=None, background=None):
        started = time.perf_counter()
        effective = quality or self.effective_graphics_quality()
        preset = GRAPHICS_PRESETS[effective]
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, preset["antialias"])
        painter.setRenderHint(QPainter.RenderHint.TextAntialiasing, preset["antialias"])
        selected_background = background or self.background
        if selected_background == "gradient":
            gradient = QLinearGradient(rect.topLeft(), rect.bottomRight())
            gradient.setColorAt(0, QColor("#f8fbfd"))
            gradient.setColorAt(1, QColor("#eaf1f4"))
            painter.fillRect(rect, gradient)
        elif selected_background != "transparent":
            painter.fillRect(rect, QColor("#152431" if selected_background == "dark" else "#ffffff"))
        foreground = QColor("#e7f0f5" if selected_background == "dark" else "#334f60")
        compact = not export and rect.height() < 220
        font = QFont("Arial")
        font.setPixelSize((10 if compact else 12) if not export else 17)
        painter.setFont(font)
        margin = (12 if compact else 22) if not export else 28
        legend = self._legend_document(font, rect.width() - margin * 2, foreground, export=export, compact=compact)
        legend_height = math.ceil(legend.size().height()) + (10 if compact else 20)
        scene = rect.adjusted(margin, (26 if compact else 44) if not export else 52, -margin, -legend_height)
        painter.setPen(foreground)
        title = str(self.metadata.get("filename", self.tr_text("구조", "Structure")))
        painter.drawText(rect.adjusted(margin, 14, -margin, 0), Qt.AlignmentFlag.AlignTop,
                         QFontMetricsF(font).elidedText(title, Qt.TextElideMode.ElideMiddle, max(10, rect.width() - margin * 2)))
        if not self.report or not len(self.positions):
            painter.drawText(scene, Qt.AlignmentFlag.AlignCenter,
                             self.tr_text("CIF 파일을 열어 구조를 확인하세요", "Open a CIF to inspect its structure"))
            self._pick_map = None
            return
        sample_scale = preset["sample_scale"]
        if not export and self._interacting:
            sample_scale = min(sample_scale, preset["interaction_scale"])
        width, height = max(1, round(scene.width() * sample_scale)), max(1, round(scene.height() * sample_scale))
        # Pan is a display-space translation: preserve the same camera when the
        # scene is sampled more densely or exported at a different resolution.
        view_scale = sample_scale * (scene.width() / max(1, self.width() - 44) if export else 1)
        project, scale, corners = self._projection(QRectF(0, 0, width, height), pan_scale=view_scale)
        primitives, painted, label_count = self._scene_primitives(project, scale, corners, preset, sample_scale, export)
        pixels, pick_map = rasterize(width, height, primitives, world_per_pixel=1 / scale)
        # QImage owns a detached copy; it must not outlive a borrowed NumPy buffer.
        image = QImage(pixels.data, width, height, pixels.strides[0], QImage.Format.Format_RGBA8888).copy()
        painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform, preset["antialias"])
        painter.drawImage(scene, image)
        painter.setFont(font)
        painter.setPen(foreground)
        painter.save()
        painter.translate(rect.left() + margin, rect.bottom() - legend_height + 4)
        legend.drawContents(painter, QRectF(0, 0, rect.width() - margin * 2, legend_height - 8))
        painter.restore()
        if not export:
            self._pick_map, self._pick_rect = pick_map, QRectF(scene)
            self._projected_atoms = [(index, scene.x() + x / sample_scale, scene.y() + y / sample_scale, radius / sample_scale)
                                     for index, x, y, radius in painted]
            frame_ms = (time.perf_counter() - started) * 1000
            self._frame_times.append(frame_ms)
            self._last_render_stats = {"quality": effective, "requested_quality": self.graphics_quality,
                                       "frame_ms": frame_ms, "raster_size": (width, height),
                                       "labels": label_count, "interacting": self._interacting,
                                       "surface_faces": sum(len(surface["faces"]) for surface in self.surfaces),
                                       "mesh_simplification": "none; original triangles retained"}

    @staticmethod
    def _rgba(color, alpha=1.0):
        value = color if isinstance(color, QColor) else _color(color)
        return value.redF(), value.greenF(), value.blueF(), alpha

    def _text_texture(self, text, size, color, *, square=None):
        key = text, int(size), color, square
        if key in self._text_cache:
            return self._text_cache[key]
        font = QFont("Arial")
        font.setPixelSize(max(7, int(size)))
        metrics = QFontMetricsF(font)
        width = int(square or math.ceil(metrics.horizontalAdvance(text)) + 6)
        height = int(square or math.ceil(metrics.height()) + 4)
        image = QImage(max(1, width), max(1, height), QImage.Format.Format_RGBA8888)
        image.fill(Qt.GlobalColor.transparent)
        painter = QPainter(image)
        painter.setRenderHint(QPainter.RenderHint.TextAntialiasing)
        painter.setFont(font)
        painter.setPen(QColor(color))
        painter.drawText(QRectF(0, 0, width, height), Qt.AlignmentFlag.AlignCenter, text)
        painter.end()
        texture = np.frombuffer(image.constBits(), np.uint8).reshape(image.height(), image.bytesPerLine())[:, :image.width() * 4].reshape(image.height(), image.width(), 4).copy()
        if len(self._text_cache) > 400:
            self._text_cache.clear()
        self._text_cache[key] = texture
        return texture

    def _scene_primitives(self, project, scale, corners, preset, sampling, export):
        primitives = []
        points, depths = project(self.positions)
        atom_points = np.column_stack((points, depths))
        display_scale = max(0.25, min(self.width() / 800, self.height() / 560)) * sampling
        if export:
            # Export radii scale with scene geometry, independent of the chosen
            # screen quality and output pixel count.
            display_scale = max(sampling, scale / 70)

        def projected(xyz):
            xy, z = project(np.asarray(xyz))
            return np.column_stack((xy, z))

        def line(xyz, color, width=1.1, dashed=False, alpha=1):
            primitives.append(Primitive("line", projected(xyz), self._rgba(color, alpha),
                                        radius=max(0.55, width * display_scale / 2), dashed=dashed))

        def sprite(text, point, color="#426a70", size=11):
            texture = self._text_texture(text, max(8, size * display_scale), color)
            location = projected([point])[0]
            location[:2] += [6 * display_scale, -texture.shape[0]]
            primitives.append(Primitive("sprite", location[None, :], (1, 1, 1, 1), texture=texture))

        if self.show_gap:
            axis = int(self.report.get("normal_axis_index", 2))
            others = [index for index in range(3) if index != axis]
            start, end = (self.report["metrics"][key] for key in ("gap_start_fraction", "gap_end_fraction"))
            for value in (start, end):
                fractional = np.zeros((4, 3))
                fractional[:, axis] = value
                fractional[:, others] = [[0, 0], [1, 0], [1, 1], [0, 1]]
                xyz = fractional @ self.cell
                quad = projected(xyz)
                for indices in ((0, 1, 2), (0, 2, 3)):
                    primitives.append(Primitive("triangle", quad[list(indices)], self._rgba("#5ba498", 0.13)))
                for first, second in ((0, 1), (1, 2), (2, 3), (3, 0)):
                    line(xyz[[first, second]], "#7ab6ad", dashed=True)
            location = np.zeros(3)
            location[axis] = (start + (end + 1 if end <= start else end)) / 2 % 1
            location[others] = 0.5
            sprite(self.tr_text("핵 간격 ", "Nuclei gap ") + f"{self.report['metrics']['nuclei_gap_angstrom']:.3f} Å", location @ self.cell)
        if self.show_cell:
            for index, corner in enumerate(product((0, 1), repeat=3)):
                for axis in range(3):
                    if corner[axis] == 0:
                        other = list(corner)
                        other[axis] = 1
                        other_index = other[0] * 4 + other[1] * 2 + other[2]
                        line(corners[[index, other_index]], "#8fa7b6")
            for axis, color in enumerate(("#b45d55", "#4a8861", "#4b7eac")):
                line([np.zeros(3), self.cell[axis]], color, 2)
                sprite("abc"[axis], self.cell[axis], color)
        if self.show_bonds and self.representation != "spacefill":
            width = 5 if self.representation == "stick" else 3
            for first, second in self._guides:
                line(self.positions[[first, second]], "#9badb8", width)
        for surface in self.surfaces:
            xyz = projected(surface["vertices"])
            for face in surface["faces"]:
                primitives.append(Primitive("triangle", xyz[face], self._rgba(surface["color"], surface["opacity"])))
        if self.selected_contact:
            contact = self.selected_contact
            endpoints = np.array([
                self.positions[contact["i"]] + np.asarray(contact.get("start_shift", [0, 0, 0])) @ self.cell,
                self.positions[contact["j"]] + np.asarray(contact.get("end_shift", contact.get("shift", [0, 0, 0]))) @ self.cell,
            ])
            line(endpoints, "#ae722f", 2, dashed=True)
            for center in projected(endpoints):
                angles = np.linspace(0, math.tau, 25)
                ring = np.column_stack((center[0] + 6 * display_scale * np.cos(angles),
                                        center[1] + 6 * display_scale * np.sin(angles), np.full(25, center[2])))
                for first, second in zip(ring[:-1], ring[1:]):
                    primitives.append(Primitive("line", np.array([first, second]), self._rgba("#ae722f"), max(0.7, display_scale)))
            sprite(f"{contact['distance_angstrom']:.3f} Å", endpoints.mean(axis=0), "#8a551c")
        priorities = list(dict.fromkeys([*self.selected_atoms, *([self._hover] if self._hover >= 0 else []), *range(len(self.positions))]))
        label_indices = set(priorities[:preset["labels"]]) if self.show_labels else set()
        painted = []
        for index in np.argsort(depths):
            index = int(index)
            number = atomic_numbers[self.elements[index]]
            if self.representation == "spacefill":
                radius = scale * _display_vdw_radius(self.elements[index]) * 0.75
            elif self.representation == "stick":
                radius = max(3 * display_scale, min(9 * display_scale, scale * 0.13))
            else:
                radius = min(29 * display_scale, max(7.5 * display_scale, scale * (0.24 + covalent_radii[number] * 0.27)))
            color = self._atom_color(index)
            texture = None
            if index in label_indices:
                text_color = "#ffffff" if color.lightness() < 155 else "#183447"
                texture = self._text_texture(self.elements[index], max(8, radius * 0.83), text_color, square=max(10, round(radius * 2)))
            primitives.append(Primitive("sphere", atom_points[index:index + 1], self._rgba(color), radius,
                                        atom=index, shaded=preset["shaded"], texture=texture))
            if index in self.selected_atoms or index == self._hover:
                center = atom_points[index]
                angles = np.linspace(0, math.tau, 33)
                ring = np.column_stack((center[0] + (radius + 4 * display_scale) * np.cos(angles),
                                        center[1] + (radius + 4 * display_scale) * np.sin(angles), np.full(33, center[2])))
                for first, second in zip(ring[:-1], ring[1:]):
                    primitives.append(Primitive("line", np.array([first, second]), self._rgba("#bf9148"), max(0.8, display_scale)))
            painted.append((index, *points[index], radius))
        return primitives, painted, len(label_indices)

    def _export_annotations(self):
        lines = [
            "CalcLens · annotated structure image",
            f"File: {self.metadata.get('filename', '—')}",
            f"SHA-256: {self.metadata.get('sha256', '—')}",
            f"Normal axis: {self.report.get('normal_axis', 'c')} · Cartesian lengths: Å · "
            "Gray cell edges; a red / b green / c blue; gold circles mark selected images.",
            f"Display: {self.representation}; orthographic projection; atoms {len(self.positions)}; "
            "software per-pixel depth; opaque surfaces hide geometry and block picking, "
            "translucent surfaces composite per-pixel depth layers. Full mesh triangles are retained at the declared isovalue.",
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

    def export_png(self, path, metadata=None, *, width=None, height=None, quality="high", background="white"):
        if self.report is None:
            raise ValueError("A supported structure must be loaded before exporting an image.")
        previous = self.metadata
        self.metadata = {**previous, **(metadata or {})}
        try:
            if quality not in GRAPHICS_PRESETS:
                raise ValueError("Export quality must be light, balanced or high.")
            width = 1600 if width is None else width
            scene_height = round(width * 0.75) if height is None and type(width) is int else height
            if (type(width) is not int or type(scene_height) is not int
                    or not 400 <= width <= 3200 or not 300 <= scene_height <= 3200):
                raise ValueError("PNG scene dimensions must be integer pixels: width 400–3200, height 300–3200.")
            if background not in ("white", "transparent", "gradient", "dark"):
                raise ValueError("Choose white, transparent, gradient or dark PNG background.")
            font = QFont("Arial")
            font.setPixelSize(17)
            annotations = self._export_annotations()
            footer = QTextDocument()
            footer.setDocumentMargin(0)
            footer.setDefaultFont(font)
            options = QTextOption()
            options.setWrapMode(QTextOption.WrapMode.WrapAtWordBoundaryOrAnywhere)
            footer.setDefaultTextOption(options)
            footer.setPlainText(annotations)
            footer.setTextWidth(width - 56)
            footer_height = int(math.ceil(footer.size().height())) + 46
            if footer_height > 12000:
                raise ValueError("Image annotations exceed the native PNG size limit.")
            image = QImage(width, scene_height + footer_height, QImage.Format.Format_ARGB32_Premultiplied)
            image.fill(Qt.GlobalColor.transparent if background == "transparent" else QColor("#ffffff"))
            painter = QPainter(image)
            self._paint(painter, QRectF(0, 0, width, scene_height), export=True, quality=quality, background=background)
            painter.fillRect(QRectF(0, scene_height, width, footer_height), QColor("#ffffff"))
            painter.setFont(font)
            painter.setPen(QColor("#3c5665"))
            painter.drawLine(QPointF(24, scene_height), QPointF(width - 24, scene_height))
            # QTextDocument wraps ordinary prose at words and long hashes at
            # characters, using the very same layout for measurement and paint.
            painter.translate(28, scene_height + 20)
            footer.drawContents(painter, QRectF(0, 0, width - 56, footer_height - 36))
            painter.end()
            provenance = {
                **self.metadata, "normal_axis": self.report.get("normal_axis"),
                "camera": self.view_state(), "charge": self.charge_metadata,
                "surface": self.surface_metadata,
                "rendering": {"quality": quality, "background": background,
                              "scene_width": width, "scene_height": scene_height,
                              "renderer": "software-per-pixel-depth", "mesh_simplification": "none"},
                "scope": "Supplied geometry; distance guides are not chemical bonds.",
            }
            image.setText("CalcLens provenance", json.dumps(provenance, ensure_ascii=False))
            image.setText("CalcLens annotations", annotations)
            if not image.save(str(path), "PNG"):
                raise OSError("Could not save the PNG image.")
        finally:
            self.metadata = previous
        return Path(path)

    def _picked(self, point):
        if self._pick_map is None or not self._pick_rect.contains(point):
            return -1
        height, width = self._pick_map.shape
        x = min(width - 1, max(0, int((point.x() - self._pick_rect.x()) / self._pick_rect.width() * width)))
        y = min(height - 1, max(0, int((point.y() - self._pick_rect.y()) / self._pick_rect.height() * height)))
        return int(self._pick_map[y, x])

    def mousePressEvent(self, event):
        self.setFocus()
        self._last_pointer = event.position()
        self._press_pointer = event.position()
        event.accept()

    def mouseMoveEvent(self, event):
        point = event.position()
        if self._last_pointer is not None and event.buttons():
            self._interacting = True
            self._interaction_timer.start(140)
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
        self._interacting = True
        self._interaction_timer.start(140)
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
