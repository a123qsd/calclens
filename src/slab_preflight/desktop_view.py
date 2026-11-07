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
    QColor, QFont, QFontMetricsF, QImage, QLinearGradient, QPainter, QPen, QTextDocument, QTextOption,
)
from PySide6.QtWidgets import QApplication, QWidget

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
# Far beyond the supported structural coordinates and any usable screen pan.
# Keep restored cameras in the same numeric range as live interaction.
MAX_CAMERA_VALUE = 1e9


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
        self.cell = np.zeros((3, 3))
        self.has_cell = False
        self.elements = []
        self.yaw = 0.55
        self.pitch = -0.35
        self.roll = 0.0
        self.zoom = 1.0
        self.pan = np.zeros(2)
        self._camera_center = np.zeros(3)
        self._camera_radius = 1.0
        self._fit_target = "cell"
        self.show_cell = True
        self.show_bonds = True
        self.show_gap = False
        self.show_labels = True
        self.graphics_quality = "auto"
        self.representation = "ball-stick"
        self.background = "gradient"
        self._auto_quality = "balanced"
        self._frame_times = deque(maxlen=12)
        self._auto_quality_changed = 0.0
        self._interacting = False
        self._interaction_timer = QTimer(self)
        self._interaction_timer.setSingleShot(True)
        self._interaction_timer.timeout.connect(self._finish_interaction)
        self._pick_map = None
        self._pick_rect = QRectF()
        self._text_cache = {}
        self._last_render_stats = {}
        self._scene_revision = 0
        self._scene_cache = None
        self.selected_atoms = []
        self.selected_contact = None
        self._last_pointer = None
        self._press_pointer = None
        self._dragging = False
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
        # Only uncached, stationary scene renders enter this window. A dwell
        # and separated thresholds prevent the cheaper drag/hover frames from
        # repeatedly promoting a scene that is expensive at full resolution.
        if self._frame_times and time.monotonic() - self._auto_quality_changed >= 2:
            mean_ms = sum(self._frame_times) / len(self._frame_times)
            candidate = self._auto_quality
            if mean_ms > 90 or (candidate == "high" and mean_ms > 65):
                candidate = "light" if mean_ms > 90 else "balanced"
            elif len(self._frame_times) == self._frame_times.maxlen:
                if mean_ms < 12 and complexity < 3000 and candidate == "balanced":
                    candidate = "high"
                elif mean_ms < 25 and candidate == "light":
                    candidate = "balanced"
            if candidate != self._auto_quality:
                self._auto_quality = candidate
                self._auto_quality_changed = time.monotonic()
                self._frame_times.clear()
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
            self.cell = np.zeros((3, 3))
            self.has_cell = False
            self._guides = []
        else:
            self.positions = np.asarray(report["positions"], dtype=float)
            self.has_cell = report.get("cell") is not None
            # The zero transform represents absent periodic translations only;
            # it is never presented as a molecular lattice or written to data.
            self.cell = np.asarray(report["cell"], dtype=float) if self.has_cell else np.zeros((3, 3))
            self.elements = list(report["elements"])
            self._guides = self._contact_guides()
        self._scene_revision += 1
        self._scene_cache = None
        self._hover = -1
        self._frame_times.clear()
        self.fit_view("cell" if self.show_cell and self.has_cell else "atoms", emit=False)
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
        self._scene_revision += 1
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
        self._scene_revision += 1
        self.update()

    def clear_electronic(self):
        self.charges = None
        self.surfaces = []
        self.charge_metadata = {}
        self.surface_metadata = {}
        self._scene_revision += 1
        self.update()

    def reset_view(self, preset="perspective"):
        self.yaw, self.pitch = {
            "perspective": (0.55, -0.35), "top": (0.0, 0.0),
            "front": (0.0, -math.pi / 2), "side": (-math.pi / 2, -math.pi / 2),
        }.get(preset, (0.55, -0.35))
        self.roll = 0.0
        self.fit_view("cell" if self.show_cell and self.has_cell else "atoms", emit=False)
        self.update()
        self.viewChanged.emit()

    def view_state(self):
        return {
            "yaw": self.yaw, "pitch": self.pitch, "roll": self.roll, "zoom": self.zoom,
            "pan": self.pan.tolist(), "cell": self.show_cell, "bonds": self.show_bonds,
            "gap": self.show_gap, "labels": self.show_labels,
            "representation": self.representation, "background": self.background,
            "projection": "orthographic",
            "camera_center": self._camera_center.tolist(), "camera_radius": self._camera_radius,
            "fit_target": self._fit_target,
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
            self.pan = np.clip(np.asarray(pan, dtype=float), -MAX_CAMERA_VALUE, MAX_CAMERA_VALUE)
        for key, attribute in (("cell", "show_cell"), ("bonds", "show_bonds"),
                               ("gap", "show_gap"), ("labels", "show_labels")):
            if type(state.get(key)) is bool:
                setattr(self, attribute, state[key])
        if state.get("representation") in ("ball-stick", "stick", "spacefill"):
            self.representation = state["representation"]
        if state.get("background") in ("gradient", "white", "dark", "transparent"):
            self.background = state["background"]
        center, radius = state.get("camera_center"), state.get("camera_radius")
        if (isinstance(center, list) and len(center) == 3
                and all(type(value) in (int, float) and abs(value) <= MAX_CAMERA_VALUE for value in center)
                and type(radius) in (int, float) and 1 <= radius <= MAX_CAMERA_VALUE):
            self._camera_center = np.array(center, dtype=float)
            self._camera_radius = float(radius)
            target = state.get("fit_target")
            if target in ("cell", "atoms", "measurement"):
                self._fit_target = target
        self.update()

    def set_selection(self, indices):
        self.selected_atoms = [int(index) for index in indices if 0 <= index < len(self.positions)][-2:]
        self.selected_contact = None
        self.update()

    def set_contact(self, contact=None):
        self.selected_contact = dict(contact) if contact else None
        self.update()

    def _contact_endpoints(self):
        if not self.selected_contact:
            return None
        contact = self.selected_contact
        return np.array([
            self.positions[contact["i"]] + np.asarray(contact.get("start_shift", [0, 0, 0])) @ self.cell,
            self.positions[contact["j"]] + np.asarray(contact.get("end_shift", contact.get("shift", [0, 0, 0]))) @ self.cell,
        ])

    def fit_view(self, target="cell", *, emit=True):
        """Fit once using a world-space sphere, safe under any later rotation.

        A fit is an explicit camera operation. Measurements, visibility changes
        and subsequent paints never recompute its pivot or magnification.
        """
        if target not in ("cell", "atoms", "measurement"):
            raise ValueError("Fit target must be cell, atoms or measurement.")
        if not len(self.positions):
            return False
        if target == "measurement":
            points = self._contact_endpoints()
            if points is None:
                if not self.selected_atoms:
                    return False
                points = self.positions[self.selected_atoms]
                elements = [self.elements[index] for index in self.selected_atoms]
            else:
                elements = [self.elements[self.selected_contact[key]] for key in ("i", "j")]
        else:
            points = self.positions.copy()
            elements = list(self.elements)
        radii = np.array([_display_vdw_radius(element) * 0.75 if self.representation == "spacefill"
                          else 0.24 + covalent_radii[atomic_numbers[element]] * 0.27 for element in elements])
        if target == "cell" and self.has_cell:
            corners = np.array(list(product((0, 1), repeat=3))) @ self.cell
            points = np.vstack((points, corners))
            radii = np.r_[radii, np.zeros(len(corners))]
        if target in ("cell", "atoms"):
            for surface in self.surfaces:
                points = np.vstack((points, surface["vertices"]))
                radii = np.r_[radii, np.zeros(len(surface["vertices"]))]
        lower = (points - radii[:, None]).min(axis=0)
        upper = (points + radii[:, None]).max(axis=0)
        self._camera_center = (lower + upper) / 2
        self._camera_radius = max(1.0, float(np.max(np.linalg.norm(points - self._camera_center, axis=1) + radii)))
        self._fit_target = target
        self.zoom = 1.0
        self.pan = np.zeros(2)
        self.update()
        if emit:
            self.viewChanged.emit()
        return True

    def fit_cell(self):
        return self.fit_view("cell")

    def fit_atoms(self):
        return self.fit_view("atoms")

    def fit_measurement(self):
        return self.fit_view("measurement")

    def _transform(self, points):
        cy, sy = math.cos(self.yaw), math.sin(self.yaw)
        cp, sp = math.cos(self.pitch), math.sin(self.pitch)
        cr, sr = math.cos(self.roll), math.sin(self.roll)
        rotation = (np.array([[1, 0, 0], [0, cp, -sp], [0, sp, cp]])
                    @ np.array([[cr, 0, sr], [0, 1, 0], [-sr, 0, cr]])
                    @ np.array([[cy, -sy, 0], [sy, cy, 0], [0, 0, 1]]))
        return (np.asarray(points) - self._camera_center) @ rotation.T

    def _projection(self, rect, *, pan_scale=1.0):
        corners = np.array(list(product((0, 1), repeat=3))) @ self.cell
        scale = 0.86 * max(1, min(rect.width(), rect.height()) - 32) / (2 * self._camera_radius) * self.zoom
        origin = np.array([rect.center().x(), rect.center().y()]) + self.pan * pan_scale

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
        self._draw_scene(painter, scene, export=export, quality=effective, background=selected_background)
        painter.setFont(font)
        painter.setPen(foreground)
        painter.save()
        painter.translate(rect.left() + margin, rect.bottom() - legend_height + 4)
        legend.drawContents(painter, QRectF(0, 0, rect.width() - margin * 2, legend_height - 8))
        painter.restore()

    def _scene_key(self, scene, quality, sampling, pan_scale):
        # Public camera/toggle values remain assignable. Include them directly
        # so picking after a wheel, resize or programmatic edit cannot consult
        # the preceding frame. Hover and selected atom IDs are overlays only.
        return (self._scene_revision, scene.width(), scene.height(), quality, sampling, pan_scale,
                self.yaw, self.pitch, self.roll, self.zoom, *self.pan, *self._camera_center,
                self._camera_radius, self.show_cell, self.show_bonds, self.show_gap,
                self.show_labels, self.representation,
                tuple((surface["opacity"], surface["color"], id(surface["vertices"]), id(surface["faces"]))
                      for surface in self.surfaces),
                json.dumps(self.selected_contact, sort_keys=True, default=str))

    def _draw_scene(self, painter, scene, *, export=False, quality=None, background=None):
        started = time.perf_counter()
        effective = quality or self.effective_graphics_quality()
        preset = GRAPHICS_PRESETS[effective]
        # All geometry, pen widths and annotations start in logical widget
        # coordinates. Only the offscreen sample buffer uses physical pixels.
        # Print already specifies its desired physical pixel grid; rendering
        # another 1.5x buffer adds memory without adding requested resolution.
        if export:
            sampling = min(1.0, preset["sample_scale"]) * abs(painter.deviceTransform().m11())
        else:
            sample_scale = min(preset["sample_scale"], preset["interaction_scale"]) if self._interacting else preset["sample_scale"]
            sampling = sample_scale * self.devicePixelRatioF()
        sampling = max(0.1, sampling)
        pan_scale = scene.width() / max(1, self.width() - 44) if export else 1.0
        key = self._scene_key(scene, effective, sampling, pan_scale)
        cached = not export and self._scene_cache is not None and self._scene_cache["key"] == key
        project, scale, corners = self._projection(QRectF(0, 0, scene.width(), scene.height()), pan_scale=pan_scale)
        if cached:
            frame = self._scene_cache
        else:
            width, height = max(1, round(scene.width() * sampling)), max(1, round(scene.height() * sampling))
            sx, sy = width / scene.width(), height / scene.height()

            def raster_project(points):
                xy, depths = project(points)
                return xy * [sx, sy], depths

            raw_scale = scale * min(sx, sy)
            primitives, painted, label_count = self._scene_primitives(
                raster_project, raw_scale, corners, preset, min(sx, sy), export)
            pixels, pick_map = rasterize(width, height, primitives, world_per_pixel=1 / raw_scale)
            # Detach from the borrowed NumPy buffer before returning/caching.
            image = QImage(pixels.data, width, height, pixels.strides[0], QImage.Format.Format_RGBA8888).copy()
            frame = {"key": key, "image": image, "pick_map": pick_map, "labels": label_count,
                     "painted": [(index, x / sx, y / sy, radius / min(sx, sy))
                                 for index, x, y, radius in painted], "sampling": min(sx, sy),
                     "widget_size": (self.width(), self.height()), "language": self.language}
            if not export:
                self._scene_cache = frame
        painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform, preset["antialias"])
        painter.drawImage(scene, frame["image"])
        self._draw_highlights(painter, scene, frame, include_hover=not export)
        self._draw_annotations(painter, scene, project, frame["painted"], background or self.background, frame)
        if not export:
            self._pick_map, self._pick_rect = frame["pick_map"], QRectF(scene)
            self._projected_atoms = [(index, scene.x() + x, scene.y() + y, radius)
                                     for index, x, y, radius in frame["painted"]]
            frame_ms = (time.perf_counter() - started) * 1000
            if not cached and not self._interacting:
                self._frame_times.append(frame_ms)
            self._last_render_stats = {"quality": effective, "requested_quality": self.graphics_quality,
                                       "frame_ms": frame_ms, "raster_size": (frame["image"].width(), frame["image"].height()),
                                       "labels": frame["labels"], "interacting": self._interacting,
                                       "cached_scene": cached, "device_pixel_ratio": self.devicePixelRatioF(),
                                       "surface_faces": sum(len(surface["faces"]) for surface in self.surfaces),
                                       "mesh_simplification": "none; original triangles retained"}
        return scale

    def _draw_highlights(self, painter, scene, frame, *, include_hover=True):
        """Outline visible atom fragments without rerasterizing the 3-D scene.

        The exact depth-tested pick map is the mask: an atom hidden behind an
        opaque mesh receives no ring, and a partly hidden atom is outlined only
        where it is visible. The array operations touch its small screen bounds.
        """
        indices = tuple(dict.fromkeys([*self.selected_atoms, *([self._hover] if include_hover and self._hover >= 0 else [])]))
        overlay_key = indices, scene.x(), scene.y(), scene.width(), scene.height()
        if frame.get("highlight_key") != overlay_key:
            picks = frame["pick_map"]
            height, width = picks.shape
            sx, sy = width / scene.width(), height / scene.height()
            padding = max(1, math.ceil(2 * min(sx, sy)))
            overlays = []
            centers = {index: (x * sx, y * sy, radius * min(sx, sy)) for index, x, y, radius in frame["painted"]}
            for index in indices:
                if index not in centers:
                    continue
                x, y, radius = centers[index]
                x0, y0 = max(0, math.floor(x - radius - padding - 2)), max(0, math.floor(y - radius - padding - 2))
                x1, y1 = min(width, math.ceil(x + radius + padding + 2)), min(height, math.ceil(y + radius + padding + 2))
                if x1 <= x0 or y1 <= y0:
                    continue
                mask = picks[y0:y1, x0:x1] == index
                if not mask.any():
                    continue
                expanded = mask.copy()
                padded = np.pad(mask, padding)
                for dy in range(-padding, padding + 1):
                    for dx in range(-padding, padding + 1):
                        if dx * dx + dy * dy <= padding * padding:
                            expanded |= padded[padding + dy:padding + dy + mask.shape[0],
                                               padding + dx:padding + dx + mask.shape[1]]
                rgba = np.zeros((*mask.shape, 4), dtype=np.uint8)
                rgba[expanded & ~mask] = [201, 149, 58, 255]
                if self.show_labels and index >= frame["labels"]:
                    # Keep selected/hovered atoms identifiable even beyond a
                    # preset's ordinary label budget. Paint just that glyph
                    # through its visible fragments; the base scene is reused.
                    color = self._atom_color(index)
                    glyph = self._text_texture(self.elements[index], max(8 * min(sx, sy), radius * 0.83),
                                               "#ffffff" if color.lightness() < 155 else "#183447",
                                               square=max(1, round(max(10 * min(sx, sy), radius * 2))))
                    yy, xx = np.mgrid[y0:y1, x0:x1]
                    gx = np.clip(((xx + 0.5 - x + radius) * glyph.shape[1] / (2 * radius)).astype(int), 0, glyph.shape[1] - 1)
                    gy = np.clip(((yy + 0.5 - y + radius) * glyph.shape[0] / (2 * radius)).astype(int), 0, glyph.shape[0] - 1)
                    rgba[mask] = glyph[gy[mask], gx[mask]]
                overlay = QImage(rgba.data, rgba.shape[1], rgba.shape[0], rgba.strides[0], QImage.Format.Format_RGBA8888).copy()
                overlays.append((QRectF(scene.x() + x0 / sx, scene.y() + y0 / sy,
                                        (x1 - x0) / sx, (y1 - y0) / sy), overlay))
            frame["highlight_key"], frame["highlights"] = overlay_key, overlays
        for target, image in frame.get("highlights", []):
            painter.drawImage(target, image)

    def _scene_annotations(self, project, background):
        annotations = []
        dark = background == "dark"

        def annotation(text, point, color):
            xy, _ = project(np.asarray([point]))
            annotations.append((text, xy[0], color))

        if self.show_cell and self.has_cell:
            colors = ("#ffb1a9", "#b8e1be", "#b5d7ff") if dark else ("#923d35", "#28643d", "#2d6090")
            for axis, color in enumerate(colors):
                annotation("abc"[axis], self.cell[axis], color)
        endpoints = self._contact_endpoints()
        if endpoints is not None:
            annotation(f"{self.selected_contact['distance_angstrom']:.3f} Å", endpoints.mean(axis=0),
                       "#ffe3a8" if dark else "#68410d")
        if self.show_gap and self.has_cell and "nuclei_gap_angstrom" in self.report.get("metrics", {}):
            axis = int(self.report.get("normal_axis_index", 2))
            metrics = self.report["metrics"]
            start, end = metrics["gap_start_fraction"], metrics["gap_end_fraction"]
            location = np.full(3, 0.5)
            location[axis] = (start + (end + 1 if end <= start else end)) / 2 % 1
            annotation(self.tr_text("핵 간격 ", "Nuclei gap ") + f"{metrics['nuclei_gap_angstrom']:.3f} Å",
                       location @ self.cell, "#bce2db" if dark else "#265f58")
        return annotations

    def _draw_annotations(self, painter, scene, project, painted, background, frame):
        # Text is a screen annotation, deliberately outside the depth buffer.
        # Font metrics/layout are evaluated once in logical units; Qt rasterizes
        # them sharply at the actual screen/print DPR after the 3-D image blit.
        painter.save()
        painter.setClipRect(scene)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        painter.setRenderHint(QPainter.RenderHint.TextAntialiasing, True)
        font = QFont("Arial")
        font.setPixelSize(12)
        painter.setFont(font)
        metrics = QFontMetricsF(font)
        layout_key = background, self.language
        if frame.get("annotation_key") != layout_key:
            occupied, layout, boxes = [], [], []
            atoms = np.array([[x - radius, y - radius, x + radius, y + radius] for _, x, y, radius in painted])
            for text, anchor, color in self._scene_annotations(project, background):
                width, height = math.ceil(metrics.horizontalAdvance(text)) + 12, math.ceil(metrics.height()) + 6
                ax, ay = anchor
                candidates = []
                for dx, dy in ((8, -height - 8), (8, 8), (-width - 8, -height - 8), (-width - 8, 8),
                               (-width / 2, -height - 22), (-width / 2, 22)):
                    candidate = QRectF(max(3, min(scene.width() - width - 3, ax + dx)),
                                       max(3, min(scene.height() - height - 3, ay + dy)), width, height)
                    overlap = np.maximum(0, np.minimum(atoms[:, 2:], [candidate.right(), candidate.bottom()])
                                         - np.maximum(atoms[:, :2], [candidate.left(), candidate.top()]))
                    score = np.prod(overlap, axis=1).sum() + 8 * sum(
                        candidate.intersected(other).width() * candidate.intersected(other).height() for other in occupied)
                    candidates.append((score, candidate))
                box = min(candidates, key=lambda item: item[0])[1]
                occupied.append(box)
                layout.append((text, anchor, color, box))
                boxes.append({"text": text, "rect": (box.x(), box.y(), box.width(), box.height()),
                              "foreground": color, "background": "#223646" if background == "dark" else "#ffffff"})
            frame["annotation_key"], frame["annotation_layout"], frame["annotation_boxes"] = layout_key, layout, boxes
        for text, anchor, color, box in frame["annotation_layout"]:
            ax, ay = anchor
            target = box.translated(scene.topLeft())
            painter.setPen(QPen(QColor(color), 0.8))
            painter.drawLine(QPointF(scene.x() + ax, scene.y() + ay), target.center())
            painter.setBrush(QColor("#223646" if background == "dark" else "#ffffff"))
            painter.drawRoundedRect(target, 4, 4)
            painter.drawText(target, Qt.AlignmentFlag.AlignCenter, text)
        self._last_annotation_boxes = frame["annotation_boxes"]
        painter.restore()

    def render_scene_image(self, width, height, *, quality="high", background="white", logical_width=800):
        """Return a scene-only QImage on a fixed logical publication canvas.

        Doubling physical output dimensions doubles every font/line width while
        preserving camera framing. Text metadata contains the actual physical
        pixels per ångström for scientific scale bars. No viewer state changes.
        """
        if self.report is None or not len(self.positions):
            raise ValueError("A supported structure must be loaded before exporting an image.")
        if (type(width) is not int or type(height) is not int or not 1 <= width <= 16000
                or not 1 <= height <= 16000 or width * height > 64_000_000):
            raise ValueError("Scene image dimensions must be positive pixels, at most 64 megapixels.")
        if quality not in GRAPHICS_PRESETS or background not in ("white", "transparent", "gradient", "dark"):
            raise ValueError("Choose a supported scene quality and background.")
        if type(logical_width) not in (int, float) or not math.isfinite(logical_width) or logical_width < 100:
            raise ValueError("Logical scene width must be at least 100 pixels.")
        logical_height = height * logical_width / width
        image = QImage(width, height, QImage.Format.Format_ARGB32_Premultiplied)
        image.fill(Qt.GlobalColor.transparent if background == "transparent" else QColor("#152431" if background == "dark" else "#ffffff"))
        painter = QPainter(image)
        factor = width / logical_width
        painter.scale(factor, factor)
        rect = QRectF(0, 0, logical_width, logical_height)
        if background == "gradient":
            gradient = QLinearGradient(rect.topLeft(), rect.bottomRight())
            gradient.setColorAt(0, QColor("#f8fbfd"))
            gradient.setColorAt(1, QColor("#eaf1f4"))
            painter.fillRect(rect, gradient)
        scale = self._draw_scene(painter, rect, export=True, quality=quality, background=background)
        painter.end()
        image.setText("CalcLens scene", json.dumps({"pixels_per_angstrom": scale * factor,
                      "logical_width": logical_width, "logical_height": logical_height,
                      "raster_width": width, "raster_height": height, "projection": "orthographic"}))
        return image

    @staticmethod
    def _rgba(color, alpha=1.0):
        value = color if isinstance(color, QColor) else _color(color)
        return value.redF(), value.greenF(), value.blueF(), alpha

    def _text_texture(self, text, size, color, *, square=None):
        key = text, int(size), color, square
        if key in self._text_cache:
            return self._text_cache[key]
        font = QFont("Arial")
        font.setPixelSize(max(1, round(size)))
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
        display_scale = sampling

        def projected(xyz):
            xy, z = project(np.asarray(xyz))
            return np.column_stack((xy, z))

        def line(xyz, color, width=1.1, dashed=False, alpha=1):
            primitives.append(Primitive("line", projected(xyz), self._rgba(color, alpha),
                                        radius=width * display_scale / 2, dashed=dashed,
                                        dash_length=7 * display_scale, dash_gap=4 * display_scale))

        if self.show_gap and self.has_cell and "nuclei_gap_angstrom" in self.report.get("metrics", {}):
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
        if self.show_cell and self.has_cell:
            for index, corner in enumerate(product((0, 1), repeat=3)):
                for axis in range(3):
                    if corner[axis] == 0:
                        other = list(corner)
                        other[axis] = 1
                        other_index = other[0] * 4 + other[1] * 2 + other[2]
                        line(corners[[index, other_index]], "#8fa7b6")
            for axis, color in enumerate(("#b45d55", "#4a8861", "#4b7eac")):
                line([np.zeros(3), self.cell[axis]], color, 2)
        if self.show_bonds and self.representation != "spacefill":
            width = 5 if self.representation == "stick" else 3
            for first, second in self._guides:
                line(self.positions[[first, second]], "#9badb8", width)
        for surface in self.surfaces:
            xyz = projected(surface["vertices"])
            for face in surface["faces"]:
                primitives.append(Primitive("triangle", xyz[face], self._rgba(surface["color"], surface["opacity"])))
        if self.selected_contact:
            endpoints = self._contact_endpoints()
            line(endpoints, "#ae722f", 2, dashed=True)
            for center in projected(endpoints):
                angles = np.linspace(0, math.tau, 25)
                ring = np.column_stack((center[0] + 6 * display_scale * np.cos(angles),
                                        center[1] + 6 * display_scale * np.sin(angles), np.full(25, center[2])))
                for first, second in zip(ring[:-1], ring[1:]):
                    primitives.append(Primitive("line", np.array([first, second]), self._rgba("#ae722f"), display_scale))
        label_indices = set(range(min(len(self.positions), preset["labels"]))) if self.show_labels else set()
        painted = []
        for index in np.argsort(depths):
            index = int(index)
            radius = self._atom_radius(index, scale, display_scale)
            color = self._atom_color(index)
            texture = None
            if index in label_indices:
                text_color = "#ffffff" if color.lightness() < 155 else "#183447"
                texture = self._text_texture(self.elements[index], max(8 * display_scale, radius * 0.83), text_color,
                                             square=max(1, round(max(10 * display_scale, radius * 2))))
            primitives.append(Primitive("sphere", atom_points[index:index + 1], self._rgba(color), radius,
                                        atom=index, shaded=preset["shaded"], texture=texture))
            painted.append((index, *points[index], radius))
        return primitives, painted, len(label_indices)

    def _atom_radius(self, index, scale, display_scale=1.0):
        element = self.elements[index]
        if self.representation == "spacefill":
            return scale * _display_vdw_radius(element) * 0.75
        if self.representation == "stick":
            return max(3 * display_scale, min(9 * display_scale, scale * 0.13))
        return min(29 * display_scale, max(7.5 * display_scale,
                   scale * (0.24 + covalent_radii[atomic_numbers[element]] * 0.27)))

    def _export_annotations(self):
        lines = [
            "CalcLens · annotated structure image",
            f"File: {self.metadata.get('filename', '—')}",
            f"SHA-256: {self.metadata.get('sha256', '—')}",
            (f"Normal axis: {self.report.get('normal_axis', 'c')} · Cartesian lengths: Å · "
             "Gray cell edges; a red / b green / c blue; gold circles mark selected images.") if self.has_cell else
            "Cartesian molecular geometry · lengths: Å · no periodic cell or crystal axes.",
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
        self._ensure_pick_map()
        if self._pick_map is None or not self._pick_rect.contains(point):
            return -1
        height, width = self._pick_map.shape
        x = min(width - 1, max(0, int((point.x() - self._pick_rect.x()) / self._pick_rect.width() * width)))
        y = min(height - 1, max(0, int((point.y() - self._pick_rect.y()) / self._pick_rect.height() * height)))
        return int(self._pick_map[y, x])

    def _ensure_pick_map(self):
        if not self.report or not len(self.positions):
            self._pick_map = None
            return
        effective = self.effective_graphics_quality()
        preset = GRAPHICS_PRESETS[effective]
        sampling = (min(preset["sample_scale"], preset["interaction_scale"]) if self._interacting
                    else preset["sample_scale"]) * self.devicePixelRatioF()
        frame = self._scene_cache
        if (frame is not None and frame["widget_size"] == (self.width(), self.height())
                and frame["language"] == self.language
                and frame["key"] == self._scene_key(self._pick_rect, effective, max(0.1, sampling), 1.0)):
            return
        # Qt may not have delivered the queued paint yet. Rebuild synchronously
        # against the current camera, without processing events or trusting the
        # previous pick map. The eventual paint will reuse this exact frame.
        image = QImage(max(1, self.width()), max(1, self.height()), QImage.Format.Format_ARGB32_Premultiplied)
        image.fill(Qt.GlobalColor.transparent)
        painter = QPainter(image)
        self._paint(painter, QRectF(self.rect()), export=False)
        painter.end()

    def mousePressEvent(self, event):
        self.setFocus()
        self._last_pointer = event.position()
        self._press_pointer = event.position()
        self._dragging = False
        event.accept()

    def mouseMoveEvent(self, event):
        point = event.position()
        if self._last_pointer is not None and self._press_pointer is not None and event.buttons():
            if not self._dragging:
                if (point - self._press_pointer).manhattanLength() < QApplication.startDragDistance():
                    event.accept()
                    return
                self._dragging = True
            self._interacting = True
            self._interaction_timer.start(140)
            delta = point - self._last_pointer
            if event.buttons() & Qt.MouseButton.RightButton or event.modifiers() & Qt.KeyboardModifier.ShiftModifier:
                self.pan = np.clip(self.pan + [delta.x(), delta.y()], -MAX_CAMERA_VALUE, MAX_CAMERA_VALUE)
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
                and not self._dragging
                and (event.position() - self._press_pointer).manhattanLength() < QApplication.startDragDistance()):
            index = self._picked(event.position())
            if index >= 0:
                self.atomPicked.emit(index)
        self._last_pointer = None
        self._press_pointer = None
        self._dragging = False
        event.accept()

    def leaveEvent(self, event):
        if self._hover >= 0:
            self._hover = -1
            self.setToolTip("")
            self.update()
        super().leaveEvent(event)

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
