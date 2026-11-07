"""Native controls for external electronic fields, computational logs and convergence series."""

from __future__ import annotations

import base64
from copy import deepcopy
import csv
from hashlib import sha256
import io
import json
from pathlib import Path
from uuid import uuid4

import numpy as np
from PySide6.QtCore import QPointF, QRectF, Signal
from PySide6.QtGui import QColor, QPainter, QPainterPath, QPen
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QDoubleSpinBox,
    QFileDialog,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPlainTextEdit,
    QPushButton,
    QScrollArea,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

from .compute_devices import probe_devices
from .compute_server import RemoteComputeConfig
from .density import MAX_CUBE_BYTES, cube_bytes, density_difference, parse_cube, planar_average
from .desktop_sources import (
    evaluate_source,
    pack_series,
    read_saved_log,
    read_saved_series,
    sources_for,
)
from .native_fields import MAX_CHARGE_BYTES, bounded_read, isosurfaces, match_cube
from .project import validate_workspace_state
from .recovery import atomic_write
from .research import parse_log


class ProfileChart(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.profile = None
        self.setMinimumHeight(155)

    def set_profile(self, value):
        self.profile = value
        self.update()

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.fillRect(self.rect(), QColor("#f6f9fa"))
        if not self.profile:
            return
        x = np.asarray(self.profile["positions_angstrom"])
        y = np.asarray(self.profile["average_e_per_angstrom3"])
        if len(x) < 2 or len(y) != len(x):
            return
        xmin, xmax = float(x[0]), float(x[-1])
        ymin, ymax = min(0.0, float(y.min())), max(0.0, float(y.max()))
        if ymax == ymin:
            ymax = ymin + 1
        rect = QRectF(self.rect()).adjusted(62, 22, -18, -32)
        if rect.width() <= 1 or xmax <= xmin:
            return

        def point(a, b):
            return QPointF(
                rect.left() + (a - xmin) / (xmax - xmin) * rect.width(),
                rect.bottom() - (b - ymin) / (ymax - ymin) * rect.height(),
            )

        painter.setPen(QPen(QColor("#a0adb5"), 1))
        painter.drawLine(point(xmin, 0), point(xmax, 0))
        painter.drawLine(point(xmin, ymin), point(xmin, ymax))
        painter.drawText(QPointF(3, rect.top() + 4), f"{ymax:.3g}")
        painter.drawText(QPointF(3, rect.bottom()), f"{ymin:.3g}")
        painter.drawText(QPointF(rect.left(), self.height() - 8), f"{xmin:.3g} Å")
        painter.drawText(
            QPointF(max(rect.left() + 40, rect.right() - 55), self.height() - 8), f"{xmax:.3g} Å"
        )
        painter.drawText(QPointF(rect.left(), 15), "⟨ρ⟩ (e/Å³)")
        line = QPainterPath(point(x[0], y[0]))
        for xx, yy in zip(x[1:], y[1:]):
            line.lineTo(point(xx, yy))
        painter.setPen(QPen(QColor("#087e76"), 2))
        painter.drawPath(line)


class CubeImportDialog(QDialog):
    def __init__(self, parent, text, filename):
        super().__init__(parent)
        self.setWindowTitle(filename)
        form = QFormLayout(self)
        self.kind = QComboBox()
        for label, key in [
            (text("총 전자밀도", "Total density"), "density"),
            (text("오비탈", "Orbital"), "orbital"),
            (text("차이 밀도", "Difference density"), "difference_density"),
            (text("스핀 밀도", "Spin density"), "spin_density"),
        ]:
            self.kind.addItem(label, key)
        self.units = QComboBox()
        self.source = QLineEdit()
        self.source.setPlaceholderText(
            text("계산 프로그램과 방법", "Calculation program and method")
        )

        def options():
            self.units.clear()
            self.units.addItems(
                ["bohr^-3/2", "angstrom^-3/2", "arbitrary"]
                if self.kind.currentData() == "orbital"
                else ["e/bohr^3", "e/angstrom^3"]
            )

        options()
        self.kind.currentIndexChanged.connect(options)
        form.addRow(text("물리량", "Quantity"), self.kind)
        form.addRow(text("파일 값의 단위", "File scalar units"), self.units)
        form.addRow(text("자료 출처", "Source"), self.source)
        box = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        ok = box.button(QDialogButtonBox.StandardButton.Ok)
        ok.setEnabled(False)
        self.source.setMaxLength(500)
        self.source.textChanged.connect(lambda s: ok.setEnabled(bool(s.strip())))
        box.accepted.connect(self.accept)
        box.rejected.connect(self.reject)
        form.addRow(box)


def _blank_aux():
    return {"schemaVersion": 1, "charges": [], "volumes": []}


class ResearchPanel(QWidget):
    changed = Signal()

    def __init__(self, window):
        super().__init__(window)
        self.window = window
        self.lang = window.language
        self.entry = None
        self.aux = {}
        self.native = {}
        self._cache = {}
        self._legacy_viewers = {}
        self._digest = ""
        self._profile = None
        self._pairs = None
        self._log = None
        self._series = None
        self._epoch = 0
        self._fragments = {}
        self._filling = False
        self._signature = None
        self._surface_request = 0
        self.setObjectName("nativeResearchPanel")
        self._outer = QVBoxLayout(self)
        self._build()

    def t(self, ko, en):
        return ko if self.lang == "ko" else en

    def _button(self, ko, en, fn):
        widget = QPushButton(self.t(ko, en))
        widget.clicked.connect(lambda checked=False: self._safe(fn))
        return widget

    def _safe(self, fn):
        try:
            fn()
        except (OSError, ValueError, TypeError, KeyError, RuntimeError) as exc:
            self.window.show_error(str(exc))

    def _page(self):
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        body = QWidget()
        layout = QVBoxLayout(body)
        layout.setContentsMargins(7, 8, 7, 8)
        scroll.setWidget(body)
        self.stack.addWidget(scroll)
        return layout

    def _row(self, layout, *widgets):
        row = QHBoxLayout()
        for w in widgets:
            row.addWidget(w)
        layout.addLayout(row)

    def _build(self):
        self.mode = QComboBox()
        self.mode.setObjectName("researchMode")
        self.mode.addItems(
            [
                self.t("전자 자료", "Electronic fields"),
                self.t("연산 장치·밀도 차이", "Compute devices and density difference"),
                self.t("Gaussian 로그", "Gaussian output"),
                self.t("진공 간격 수렴", "Vacuum convergence"),
            ]
        )
        self._outer.addWidget(self.mode)
        self.stack = QStackedWidget()
        self._outer.addWidget(self.stack)
        self.mode.currentIndexChanged.connect(self.stack.setCurrentIndex)
        self.cancel_button = self._button(
            "결과 적용 취소", "Cancel pending result", self._cancel_result
        )
        self.cancel_button.setEnabled(False)
        self._outer.addWidget(self.cancel_button)
        self.window.busyChanged.connect(
            lambda busy: None if busy else self.cancel_button.setEnabled(False)
        )
        layout = self._page()
        self._row(
            layout,
            self._button("전하 JSON 열기", "Open charge JSON", self.choose_charge),
            self._button("Cube 열기", "Open Cube", self.choose_cube),
        )
        fields = QFormLayout()
        layout.addLayout(fields)
        self.charge = QComboBox()
        self.volume = QComboBox()
        self.level = QDoubleSpinBox()
        self.level.setDecimals(8)
        self.level.setRange(0.00000001, 1e9)
        self.level.setValue(0.05)
        self.opacity = QDoubleSpinBox()
        self.opacity.setRange(0.05, 1)
        self.opacity.setSingleStep(0.05)
        self.opacity.setValue(0.45)
        self.common = QCheckBox(
            self.t("같은 물리량에 공통 색상 범위", "Shared range for the same quantity")
        )
        fields.addRow(self.t("원자 색상", "Atom colors"), self.charge)
        fields.addRow(self.common)
        fields.addRow(self.t("전자 표면", "Surface data"), self.volume)
        self.unit_label = QLabel("")
        fields.addRow(self.t("등치값 단위", "Isovalue units"), self.unit_label)
        fields.addRow(self.t("등치값 크기", "Isovalue magnitude"), self.level)
        fields.addRow(self.t("불투명도", "Opacity"), self.opacity)
        self._row(
            layout,
            self._button("표면 그리기", "Draw surface", self.draw_surface),
            self._button("표면 숨기기", "Hide surface", self.hide_surface),
        )
        self.field_info = QLabel()
        self.field_info.setWordWrap(True)
        layout.addWidget(self.field_info)
        self.charge.currentIndexChanged.connect(lambda _: self._safe(self._change_charge))
        self.common.toggled.connect(lambda _: self._safe(self._change_charge))
        self.volume.currentIndexChanged.connect(lambda _: self._safe(self._change_volume))
        layout.addStretch()
        calc = self._page()
        form = QFormLayout()
        calc.addLayout(form)
        self.device = QComboBox()
        for label, key in [
            (self.t("자동", "Automatic"), "auto"),
            ("CPU", "cpu"),
            ("Apple Metal", "metal"),
            ("NVIDIA CUDA", "cuda"),
            (self.t("원격 워커", "Remote worker"), "remote"),
        ]:
            self.device.addItem(label, key)
        form.addRow(self.t("계산 장치", "Compute device"), self.device)
        self.remote_box = QWidget()
        remote = QFormLayout(self.remote_box)
        self.url = QLineEdit()
        self.url.setPlaceholderText("https://host:8768")
        self.token = QLineEdit()
        self.token.setEchoMode(QLineEdit.EchoMode.Password)
        self.ca_file = QLineEdit()
        self.ca_file.setPlaceholderText(self.t("선택 사항", "Optional"))
        remote.addRow("URL", self.url)
        remote.addRow(self.t("접속 토큰", "Token"), self.token)
        remote.addRow(self.t("CA 인증서 경로", "CA file"), self.ca_file)
        calc.addWidget(self.remote_box)
        self.remote_box.hide()
        self.device.currentIndexChanged.connect(
            lambda _: self.remote_box.setVisible(self.device.currentData() == "remote")
        )
        self._row(
            calc,
            self._button("장치 확인", "Check devices", self.check_devices),
            self._button("원자쌍 거리", "Periodic pair distances", self.calculate_pairs),
        )
        self.device_info = QLabel()
        self.device_info.setWordWrap(True)
        calc.addWidget(self.device_info)
        self.pair_save = self._button("원자쌍 CSV 저장", "Save pair CSV", self.export_pairs)
        self.pair_save.setEnabled(False)
        calc.addWidget(self.pair_save)
        self.axis = QComboBox()
        self.axis.addItems(["a", "b", "c"])
        self.axis.setCurrentIndex(2)
        f = QFormLayout()
        calc.addLayout(f)
        f.addRow(self.t("격자 평면 축", "Grid plane axis"), self.axis)
        self._row(
            calc, self._button("선택한 밀도의 평면 평균", "Average selected density", self.average)
        )
        self.chart = ProfileChart()
        calc.addWidget(self.chart)
        self._row(
            calc,
            self._button("평균 CSV 저장", "Export profile CSV", self.export_profile),
            self._button("계산 기록 저장", "Export calculation record", self.export_profile_record),
        )
        self.frag_labels = {}
        for key in ("AB", "A", "B"):
            lab = QLabel("—")
            lab.setWordWrap(True)
            self.frag_labels[key] = lab
            self._row(
                calc,
                self._button(
                    f"{key} 밀도", f"{key} density", lambda k=key: self.choose_fragment(k)
                ),
                lab,
            )
        f = QFormLayout()
        calc.addLayout(f)
        self.a_indices = QLineEdit()
        self.b_indices = QLineEdit()
        self.method = QLineEdit()
        self.conditions = QLineEdit()
        self.frag_units = QComboBox()
        self.frag_units.addItems(["e/bohr^3", "e/angstrom^3"])
        for label, widget in [
            (self.t("세 파일의 밀도 단위", "Density units (all files)"), self.frag_units),
            ("A " + self.t("원자 번호 (1부터)", "indices (one-based)"), self.a_indices),
            ("B " + self.t("원자 번호 (1부터)", "indices (one-based)"), self.b_indices),
            (self.t("공통 계산 방법", "Common method"), self.method),
            (self.t("고정한 계산 조건", "Fixed conditions"), self.conditions),
        ]:
            f.addRow(label, widget)
        self.frozen = QCheckBox(
            self.t(
                "A와 B는 AB의 원자 배치를 고정해 계산함",
                "Fragments computed at the frozen AB geometry",
            )
        )
        calc.addWidget(self.frozen)
        for entry in (self.a_indices, self.b_indices, self.method, self.conditions):
            entry.setMaxLength(4000)
            entry.textEdited.connect(lambda *_: self._safe(self._store_draft))
        self.frag_units.currentIndexChanged.connect(lambda *_: self._safe(self._store_draft))
        self.frozen.toggled.connect(lambda *_: self._safe(self._store_draft))
        self.axis.currentIndexChanged.connect(lambda *_: self._safe(self._store_draft))
        calc.addWidget(
            self._button(
                "H₂ 실제 계산 예제 열기", "Open H₂ calculation example", self.example_difference
            )
        )
        calc.addWidget(self._button("Δρ 계산 및 저장", "Compute and retain Δρ", self.difference))
        calc.addStretch()
        logs = self._page()
        self._row(
            logs,
            self._button("Gaussian 로그 열기", "Open Gaussian output", self.choose_log),
            self._button("기준 예제", "Reference example", self.example_log),
        )
        self.log_info = QPlainTextEdit()
        self.log_info.setReadOnly(True)
        logs.addWidget(self.log_info)
        self._row(
            logs,
            self._button("원본 저장", "Save original", self.export_log_raw),
            self._button("해석 JSON 저장", "Export interpretation", self.export_log),
        )
        conv = self._page()
        self._row(
            conv,
            self._button("사례 열기", "Open series", self.choose_series),
            self._button("h-BN 예제", "h-BN case", self.example_series),
        )
        self.series_info = QPlainTextEdit()
        self.series_info.setReadOnly(True)
        conv.addWidget(self.series_info)
        conv.addWidget(self._button("수렴 결과 저장", "Export comparison", self.export_series))

    def _cancel_result(self):
        self._epoch += 1
        result = self.window.cancel_job("research-compute")
        self.cancel_button.setEnabled(False)
        if result["invalidated"]:
            self.window.statusBar().showMessage(
                self.t("결과 적용을 취소했습니다.", "Pending result canceled."), 4000
            )

    def _job(self, fn, after):
        epoch = self._epoch
        digest = self._digest

        def apply(result):
            if epoch == self._epoch and digest == self._digest:
                self._safe(lambda: after(result))

        self.cancel_button.setEnabled(True)
        self.window.submit(fn, apply, key="research-compute")

    @staticmethod
    def validate_state(state, entries):
        if not isinstance(state, dict):
            raise ValueError("Invalid workspace state.")
        aux = state.get("auxiliary", {})
        native = state.get("native_research", {})
        if (
            not isinstance(aux, dict)
            or not isinstance(native, dict)
            or native.get("schema_version", 1) != 1
        ):
            raise ValueError("Unsupported research workspace format.")
        signed = native.get("signed", {})
        sel = native.get("selections", {})
        if not isinstance(signed, dict) or not isinstance(sel, dict):
            raise ValueError("Invalid saved field selection.")
        entries = {e["sha256"]: e for e in entries}
        for digest in aux.keys() | signed.keys():
            entry = entries.get(digest)
            report = (
                (entry["analysis"].get("report") or entry["analysis"].get("auxiliary_structure"))
                if entry
                else None
            )
            if not report:
                raise ValueError("An imported electronic dataset has no matching supported CIF.")
            for kind, item in sources_for(aux, signed, digest):
                evaluate_source(item, kind, report, digest)
        for digest, selection in sel.items():
            if digest not in entries or not isinstance(selection, dict):
                raise ValueError("A saved field selection has no current structure.")
            choices = sources_for(aux, signed, digest)
            for key in ("charge", "volume"):
                uid = selection.get(key)
                if uid is not None and uid not in {
                    item["id"] for kind, item in choices if kind == key
                }:
                    raise ValueError("A saved field selection references a missing dataset.")
            if any(type(selection.get(key, False)) is not bool for key in ("surface", "shared")):
                raise ValueError("Invalid saved field visibility or color scale.")
            level = selection.get("level", 0.05)
            opacity = selection.get("opacity", 0.45)
            if (
                type(level) not in (int, float)
                or not np.isfinite(level)
                or not 0 < level <= 1e9
                or type(opacity) not in (int, float)
                or not np.isfinite(opacity)
                or not 0.05 <= opacity <= 1
            ):
                raise ValueError("Invalid saved isovalue or opacity.")
        drafts = native.get("drafts", {})
        if not isinstance(drafts, dict):
            raise ValueError("Invalid saved research drafts.")
        for digest, draft in drafts.items():
            if digest not in entries or not isinstance(draft, dict):
                raise ValueError("A research draft has no matching structure.")
            if any(
                not isinstance(draft.get(k, ""), str) or len(draft.get(k, "")) > 4000
                for k in ("a", "b", "method", "conditions")
            ):
                raise ValueError("Invalid saved calculation conditions.")
            if (
                draft.get("units") not in ("e/bohr^3", "e/angstrom^3")
                or type(draft.get("frozen")) is not bool
                or type(draft.get("axis")) is not int
                or draft["axis"] not in (0, 1, 2)
            ):
                raise ValueError("Invalid research draft units or plane axis.")
            if "reference" in draft and draft["reference"] not in native.get("differences", {}).get(
                digest, {}
            ):
                raise ValueError("Research draft has no original source record.")
            sources = draft.get("sources", {})
            if not isinstance(sources, dict) or set(sources) - {"AB", "A", "B"}:
                raise ValueError("Invalid fragment set.")
            for item in sources.values():
                if (
                    not isinstance(item, dict)
                    or not isinstance(item.get("filename"), str)
                    or not isinstance(item.get("raw"), str)
                    or len(item["raw"].encode()) > MAX_CUBE_BYTES
                ):
                    raise ValueError("Invalid fragment source.")
        if "log" in native:
            read_saved_log(native["log"])
        if "series" in native:
            read_saved_series(native["series"])
        if "differences" in native:
            if not isinstance(native["differences"], dict):
                raise ValueError("Invalid difference provenance.")
            for digest, records in native["differences"].items():
                if digest not in entries or not isinstance(records, dict):
                    raise ValueError("Missing difference source structure.")
                imported = {item["id"]: item for item in signed.get(digest, [])}
                for uid, bundle in records.items():
                    if (
                        uid not in imported
                        or not isinstance(bundle, dict)
                        or bundle.get("result_id") != uid
                    ):
                        raise ValueError("Missing retained density-difference file.")
                    replay = ResearchPanel._replay_difference(bundle, entries[digest])
                    field = evaluate_source(
                        imported[uid], "volume", entries[digest]["analysis"]["report"], digest
                    )
                    if (
                        field.kind != "difference_density"
                        or field.shape != replay.grid.shape
                        or not np.allclose(
                            field.origin_angstrom, replay.grid.origin_angstrom, atol=1e-7, rtol=0
                        )
                        or not np.allclose(
                            field.voxel_vectors_angstrom,
                            replay.grid.voxel_vectors_angstrom,
                            atol=1e-7,
                            rtol=0,
                        )
                        or not np.allclose(
                            field.values,
                            replay.grid.values,
                            atol=2e-6 * max(1, float(np.max(np.abs(replay.grid.values)))),
                            rtol=2e-5,
                        )
                    ):
                        raise ValueError(
                            "Saved difference does not match the three original fields."
                        )
        validate_workspace_state(state)

    def restore_state(self, state):
        self._epoch += 1
        self._digest = ""
        self._signature = None
        self._cache.clear()
        self._fragments = {}
        self._profile = None
        self._pairs = None
        self.chart.set_profile(None)
        self.pair_save.setEnabled(False)
        self._legacy_viewers = deepcopy(state.get("viewers", {}))
        self.aux = deepcopy(state.get("auxiliary", {}))
        self.native = deepcopy(state.get("native_research", {}))
        self.native.setdefault("schema_version", 1)
        self._log = read_saved_log(self.native["log"]) if "log" in self.native else None
        self._series = read_saved_series(self.native["series"]) if "series" in self.native else None
        self._display_log()
        self._display_series()

    def portable_state(self, base_state):
        state = dict(base_state)
        active = {item["sha256"] for item in self.window.snapshot.get("entries", [])}
        native = dict(self.native)
        for key in ("signed", "selections", "differences", "drafts"):
            native[key] = {k: v for k, v in native.get(key, {}).items() if k in active}
        state["native_research"] = native
        state["auxiliary"] = {k: v for k, v in self.aux.items() if k in active}
        return state

    def _report(self):
        if not self.entry:
            raise ValueError(self.t("먼저 CIF를 여세요.", "Open a CIF first."))
        value = self.entry["analysis"].get("report") or self.entry["analysis"].get(
            "auxiliary_structure"
        )
        if not value:
            raise ValueError(
                self.t(
                    "이 CIF의 원자 위치를 확인할 수 없습니다.",
                    "No validated atomic structure for this CIF.",
                )
            )
        return value

    def _list(self):
        return sources_for(self.aux, self.native.get("signed", {}), self._digest)

    def _source(self, kind, uid):
        if not uid:
            return None
        return next((item for tag, item in self._list() if tag == kind and item["id"] == uid), None)

    def _decode(self, kind, item):
        key = (self._digest, item["id"])
        cached = self._cache.get(key)
        if cached is None:
            cached = evaluate_source(item, kind, self._report(), self._digest)
            self._cache[key] = cached
        return cached

    def set_entry(self, entry, language):
        self.lang = language
        digest = entry["sha256"] if entry else ""
        signature = (
            (digest, entry["id"], entry["normal_axis"], entry["short_distance"]) if entry else None
        )
        different = signature != self._signature
        self._signature = signature
        self.entry = entry
        self._digest = digest
        if different:
            self._epoch += 1
            self._profile = None
            self.chart.set_profile(None)
            self._pairs = None
            self.pair_save.setEnabled(False)
            self._fragments = {}
            for lab in self.frag_labels.values():
                lab.setText("—")
        if different and digest and digest not in self.native.get("selections", {}):
            self.native.setdefault("selections", {})[digest] = self.legacy_view_options(entry)
        if different and digest:
            self._restore_draft()
        self._fill_fields()
        if different:
            self._safe(lambda: self._apply_charge())
            choice = self._selection()
            if choice.get("surface") and self.volume.currentData():
                self._safe(lambda: self.draw_surface(save=False))

    def legacy_view_options(self, entry, slot="overview"):
        from .density import BOHR_ANGSTROM

        saved = self._legacy_viewers.get(f"{slot}:{entry['id']}:{entry['sha256']}", {})
        if not isinstance(saved, dict) or not saved:
            return {}
        sources = sources_for(self.aux, self.native.get("signed", {}), entry["sha256"])
        names = {item["id"]: (kind, item) for kind, item in sources}
        kind = saved.get("colorMode")
        ids = saved.get("chargeDatasetIds", {})
        charge = ids.get(kind) if isinstance(ids, dict) else None
        volume = saved.get("volumeDatasetId")
        surface = saved.get("surface", {})
        if not isinstance(surface, dict):
            surface = {}
        level = surface.get("level", 0.05)
        if type(level) not in (float, int) or not np.isfinite(level) or level <= 0:
            level = 0.05
        if volume in names:
            units = names[volume][1].get("units")
            if units == "e/bohr^3":
                level /= BOHR_ANGSTROM**3
            if units == "bohr^-3/2":
                level /= BOHR_ANGSTROM**1.5
        opacity = surface.get("opacity", 0.45)
        if type(opacity) not in (float, int) or not 0.05 <= opacity <= 1:
            opacity = 0.45
        return {
            "charge": charge if charge in names else None,
            "volume": volume if volume in names else None,
            "surface": volume in names and surface.get("enabled") is True,
            "level": min(1e9, level),
            "opacity": opacity,
        }

    def _selection(self):
        return (
            self.native.setdefault("selections", {}).setdefault(self._digest, {})
            if self._digest
            else {}
        )

    def _fill_fields(self):
        self._filling = True
        try:
            self.charge.clear()
            self.volume.clear()
            self.charge.addItem(self.t("원소 색상", "Element colors"), None)
            self.volume.addItem(self.t("선택하세요", "Select a dataset"), None)
            for kind, item in self._list():
                selector = self.charge if kind == "charge" else self.volume
                selector.addItem(item["name"], item["id"])
            choice = self._selection()
            for selector, key in ((self.charge, "charge"), (self.volume, "volume")):
                selector.setCurrentIndex(max(0, selector.findData(choice.get(key))))
            self.common.setChecked(bool(choice.get("shared", False)))
            self.level.setValue(float(choice.get("level", 0.05)))
            self.opacity.setValue(float(choice.get("opacity", 0.45)))
            self._refresh_field_info()
        finally:
            self._filling = False

    def _refresh_field_info(self):
        item = self._source("volume", self.volume.currentData())
        self.unit_label.setText("—" if not item else self._decode("volume", item).units)
        facts = []
        charge = self._source("charge", self.charge.currentData())
        if charge:
            _, meta = self._decode("charge", charge)
            facts.append(
                f"{charge['name']} · {meta['kind']} · {meta['units']}\n{meta['method']} · {meta['source']}"
            )
        if item:
            facts.append(f"{item['filename']} · {item['kind']} · {item['source']}")
        self.field_info.setText("\n\n".join(facts))

    def dataset_choices(self, entry):
        out = {"charges": [], "volumes": []}
        for kind, item in sources_for(self.aux, self.native.get("signed", {}), entry["sha256"]):
            if kind == "charge":
                _, meta = self._for_entry(entry, kind, item)
                out["charges"].append((item["id"], item["name"], meta["kind"]))
            else:
                out["volumes"].append((item["id"], item["name"], item["kind"]))
        return out

    def _for_entry(self, entry, kind, item):
        key = (entry["sha256"], item["id"])
        result = self._cache.get(key)
        if result is None:
            structure = entry["analysis"].get("report") or entry["analysis"].get(
                "auxiliary_structure"
            )
            if not structure:
                raise ValueError("No validated structure for these electronic data.")
            result = evaluate_source(item, kind, structure, entry["sha256"])
            self._cache[key] = result
        return result

    def volume_units(self, entry, volume_id):
        for kind, item in sources_for(self.aux, self.native.get("signed", {}), entry["sha256"]):
            if kind == "volume" and item["id"] == volume_id:
                return self._for_entry(entry, kind, item).units
        return ""

    def charge_extent(self, entry, charge_id):
        for tag, item in sources_for(self.aux, self.native.get("signed", {}), entry["sha256"]):
            if tag == "charge" and item["id"] == charge_id:
                vals, meta = self._for_entry(entry, tag, item)
                return meta["kind"], max([abs(v) for v in vals if v is not None] or [0.0])
        return None, 0.0

    def apply_view_dataset(
        self, view, entry, charge_id=None, volume_id=None, level=0.05, shared_extent=None
    ):
        from shiboken6 import isValid

        token = getattr(view, "_research_selection", 0) + 1
        view._research_selection = token
        sources = {
            item["id"]: (tag, item)
            for tag, item in sources_for(self.aux, self.native.get("signed", {}), entry["sha256"])
        }
        if charge_id is None:
            view.set_charges(None)
        else:
            tag, item = sources[charge_id]
            if tag != "charge":
                raise ValueError("Expected a charge dataset.")
            vals, meta = self._for_entry(entry, tag, item)
            meta = dict(meta)
            if shared_extent is not None:
                meta["color_extent"] = shared_extent
            view.set_charges(vals, meta)
        view.set_surfaces(None)
        if volume_id is None:
            return
        tag, item = sources[volume_id]
        if tag != "volume":
            raise ValueError("Expected a volume dataset.")
        grid = self._for_entry(entry, tag, item)
        digest = entry["sha256"]

        def draw(mesh):
            if (
                isValid(view)
                and getattr(view, "_research_selection", None) == token
                and view.metadata.get("sha256") == digest
            ):
                view.set_surfaces(
                    mesh,
                    {
                        "name": item["name"],
                        "kind": grid.kind,
                        "isovalue": level,
                        "units": grid.units,
                        "source": item["source"],
                        "source_sha256": grid.source_sha256,
                    },
                )

        self.window.submit(
            lambda: isosurfaces(grid, level), draw, key=f"comparison-surface-{id(view)}"
        )

    def _change_charge(self):
        if self._filling:
            return
        self._selection().update(charge=self.charge.currentData(), shared=self.common.isChecked())
        self._apply_charge()
        self.changed.emit()

    def _apply_charge(self):
        item = self._source("charge", self.charge.currentData())
        if item:
            values, meta = self._decode("charge", item)
            meta = dict(meta)
            if self.common.isChecked():
                magnitudes = []
                for tag, other in self._list():
                    if tag == "charge":
                        v, m = self._decode(tag, other)
                        if m["kind"] == meta["kind"]:
                            magnitudes.extend(abs(x) for x in v if x is not None)
                meta["color_extent"] = max(magnitudes or [1.0]) or 1.0
            self.window.view.set_charges(values, meta)
        else:
            self.window.view.set_charges(None)
        self._refresh_field_info()

    def _change_volume(self):
        if self._filling:
            return
        self._surface_request += 1
        self._selection().update(volume=self.volume.currentData(), surface=False)
        self.window.view.set_surfaces(None)
        self._refresh_field_info()
        self.changed.emit()

    def _add(self, item, kind, extra=None, *, checked=None):
        old_aux, old_native = self.aux, self.native
        self.aux, self.native = deepcopy(old_aux), deepcopy(old_native)
        try:
            if kind == "charge" or item["kind"] in ("density", "orbital"):
                blob = self.aux.setdefault(self._digest, _blank_aux())
                blob["charges" if kind == "charge" else "volumes"].append(item)
            else:
                self.native.setdefault("signed", {}).setdefault(self._digest, []).append(item)
            if extra:
                self.native.setdefault("differences", {}).setdefault(self._digest, {})[
                    item["id"]
                ] = extra
            self._list()
            if checked is None:
                checked = evaluate_source(item, kind, self._report(), self._digest)
            self._selection()[kind] = item["id"]
            validate_workspace_state(
                self.portable_state(self.window.workspace.project.workspace_state)
            )
        except Exception:
            self.aux, self.native = old_aux, old_native
            raise
        self._cache[(self._digest, item["id"])] = checked
        if kind == "volume":
            self._surface_request += 1
            self._selection()["surface"] = False
            self.window.view.set_surfaces(None)
        self._fill_fields()
        self._apply_charge()
        self.changed.emit()

    def choose_charge(self):
        self._report()
        path, _ = QFileDialog.getOpenFileName(
            self, self.t("전하 데이터", "Charge data"), "", "JSON (*.json)"
        )
        if path:
            self.import_charge(Path(path))

    def import_charge(self, path):
        raw = bounded_read(path, MAX_CHARGE_BYTES)
        name = Path(path).name
        item = {"id": uuid4().hex, "name": name, "filename": name, "rawText": raw.decode("utf-8")}
        self._add(item, "charge")

    def choose_cube(self):
        self._report()
        path, _ = QFileDialog.getOpenFileName(
            self, self.t("전자 격자", "Electronic field"), "", "Cube (*.cube *.cub);;All files (*)"
        )
        if not path:
            return
        dialog = CubeImportDialog(self, self.t, Path(path).name)
        if dialog.exec() == QDialog.DialogCode.Accepted:
            self.import_cube(
                Path(path),
                dialog.kind.currentData(),
                dialog.units.currentText(),
                dialog.source.text().strip(),
                background=True,
            )

    def import_cube(self, path, kind, units, source, *, background=False):
        report = self._report()
        digest = self._digest

        def read():
            raw = bounded_read(path, MAX_CUBE_BYTES)
            name = Path(path).name
            item = {
                "id": uuid4().hex,
                "name": name,
                "filename": name,
                "rawText": raw.decode("utf-8"),
                "kind": kind,
                "units": units,
                "source": source,
            }
            return item, evaluate_source(item, "volume", report, digest)

        def attach(result):
            self._add(result[0], "volume", checked=result[1])

        if background:
            self._job(read, attach)
        else:
            attach(read())

    def draw_surface(self, save=True):
        item = self._source("volume", self.volume.currentData())
        if not item:
            raise ValueError(self.t("Cube 자료를 선택하세요.", "Select a Cube dataset."))
        grid = self._decode("volume", item)
        level = self.level.value()
        opacity = self.opacity.value()

        self._surface_request += 1
        request = self._surface_request

        def draw(surfaces):
            if request != self._surface_request or self.volume.currentData() != item["id"]:
                return
            self.window.view.set_surfaces(
                surfaces,
                {
                    "name": item["name"],
                    "kind": grid.kind,
                    "isovalue": level,
                    "units": grid.units,
                    "source": item["source"],
                    "source_sha256": grid.source_sha256,
                },
            )
            if save:
                self._selection().update(surface=True, level=level, opacity=opacity)
                self.changed.emit()

        self._job(lambda: isosurfaces(grid, level, opacity), draw)

    def hide_surface(self):
        self._surface_request += 1
        self.window.view.set_surfaces(None)
        self._selection()["surface"] = False
        self.changed.emit()

    def _compute(self):
        device = self.device.currentData()
        remote = None
        if device == "remote":
            url = self.url.text().strip()
            token = self.token.text()
            if not url or not token:
                raise ValueError(
                    self.t("워커 주소와 토큰을 입력하세요.", "Enter the worker URL and token.")
                )
            answer = QMessageBox.question(
                self,
                self.t("원격 계산", "Remote computation"),
                self.t(
                    "이 워커에 계산에 필요한 수치 배열을 전송할까요?",
                    "Send this calculation’s numeric arrays to the worker?",
                )
                + "\n"
                + url,
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.No,
            )
            if answer != QMessageBox.StandardButton.Yes:
                return None
            remote = RemoteComputeConfig(url, token, ca_file=self.ca_file.text().strip() or None)
        return device, remote

    def check_devices(self):
        def show(result):
            self.device_info.setText(
                "\n".join(
                    f"{r['id']}: {r.get('device_name') or r.get('reason') or '—'}" for r in result
                )
            )

        self._job(probe_devices, show)

    def _normal(self):
        report = self._report()
        axis = report.get("normal_axis_index")
        return report["cell"][axis] if axis is not None else None

    def average(self):
        item = self._source("volume", self.volume.currentData())
        if not item:
            raise ValueError(
                self.t(
                    "전자 자료에서 밀도를 선택하세요.", "Select a density under Electronic fields."
                )
            )
        grid = self._decode("volume", item)
        axis = self.axis.currentIndex()
        normal = self._normal()
        choice = self._compute()
        if choice:
            self._job(
                lambda: planar_average(
                    grid, axis=axis, normal=normal, device=choice[0], remote=choice[1]
                ),
                self._show_profile,
            )

    def _show_profile(self, profile):
        self._profile = profile
        self.chart.set_profile(profile)
        run = profile["execution"]
        self.device_info.setText(
            f"{run.get('effective_device', run.get('effective_backend', ''))} · {run.get('device_name', '')} · {run.get('precision', '')}\n{run.get('fallback_reason') or ''}"
        )

    def choose_fragment(self, key):
        path, _ = QFileDialog.getOpenFileName(
            self, f"{key} Cube", "", "Cube (*.cube *.cub);;All files (*)"
        )
        if path:
            raw = bounded_read(Path(path), MAX_CUBE_BYTES)
            previous = self._fragments
            self._fragments = {
                **previous,
                key: {"filename": Path(path).name, "raw": raw.decode("utf-8")},
            }
            try:
                self._store_draft(verify_size=True)
            except (ValueError, OSError):
                self._fragments = previous
                raise
            self.frag_labels[key].setText(Path(path).name)

    def _store_draft(self, *, verify_size=False):
        if self._filling or not self._digest:
            return
        draft = {
            "a": self.a_indices.text(),
            "b": self.b_indices.text(),
            "method": self.method.text(),
            "conditions": self.conditions.text(),
            "frozen": self.frozen.isChecked(),
            "units": self.frag_units.currentText(),
            "axis": self.axis.currentIndex(),
        }
        records = self.native.get("differences", {}).get(self._digest, {})
        reference = next(
            (uid for uid, record in records.items() if record.get("sources") == self._fragments),
            None,
        )
        if reference is None:
            draft["sources"] = deepcopy(self._fragments)
        else:
            draft["reference"] = reference
        drafts = {**self.native.get("drafts", {}), self._digest: draft}
        state = self.portable_state(self.window.workspace.project.workspace_state)
        state["native_research"]["drafts"] = drafts
        if verify_size:
            validate_workspace_state(state)
        self.native["drafts"] = drafts
        self.changed.emit()

    def _restore_draft(self):
        self._filling = True
        try:
            records = self.native.get("differences", {}).get(self._digest, {})
            draft = self.native.get("drafts", {}).get(self._digest)
            if draft is None and records:
                uid, record = next(reversed(records.items()))
                draft = {
                    "reference": uid,
                    "a": ", ".join(map(str, record["a_indices"])),
                    "b": ", ".join(map(str, record["b_indices"])),
                    "method": record["method"],
                    "conditions": record["conditions"],
                    "frozen": record["frozen"],
                    "units": record["units"],
                    "axis": record["axis"],
                }
            draft = draft or {}
            sources = records.get(draft.get("reference"), {}).get(
                "sources", draft.get("sources", {})
            )
            self._fragments = deepcopy(sources)
            for key, label in self.frag_labels.items():
                label.setText(sources.get(key, {}).get("filename", "—"))
            self.a_indices.setText(draft.get("a", ""))
            self.b_indices.setText(draft.get("b", ""))
            self.method.setText(draft.get("method", ""))
            self.conditions.setText(draft.get("conditions", ""))
            self.frag_units.setCurrentText(draft.get("units", "e/bohr^3"))
            self.frozen.setChecked(draft.get("frozen", False))
            self.axis.setCurrentIndex(draft.get("axis", 2))
        finally:
            self._filling = False

    def example_difference(self):
        self.window.open_project(
            self.window.root / "examples/research_cases/h2_density/h2-density.calclens.zip"
        )

    @staticmethod
    def _replay_difference(bundle, entry, device="cpu", remote=None):
        if not isinstance(bundle.get("sources"), dict) or set(bundle["sources"]) != {
            "AB",
            "A",
            "B",
        }:
            raise ValueError("Missing density-difference originals.")
        grids = []
        for k in ("AB", "A", "B"):
            raw = bundle["sources"][k]
            grids.append(
                parse_cube(
                    raw["raw"], kind="density", units=bundle["units"], source_name=raw["filename"]
                )
            )
        report = entry["analysis"].get("report")
        if not report:
            raise ValueError("A supported slab CIF is required for this difference.")
        match_cube(grids[0], report)
        return density_difference(
            *grids,
            a_indices=bundle["a_indices"],
            b_indices=bundle["b_indices"],
            method=bundle["method"],
            reference_conditions=bundle["conditions"],
            frozen_geometry=bundle["frozen"],
            axis=bundle["axis"],
            normal=report["cell"][report["normal_axis_index"]],
            device=device,
            remote=remote,
        )

    def difference(self):
        self._report()
        choice = self._compute()
        if not choice:
            return

        def indexes(edit):
            return [int(x) for x in edit.text().replace(",", " ").split()]

        bundle = {
            "sources": deepcopy(self._fragments),
            "units": self.frag_units.currentText(),
            "a_indices": indexes(self.a_indices),
            "b_indices": indexes(self.b_indices),
            "method": self.method.text(),
            "conditions": self.conditions.text(),
            "frozen": self.frozen.isChecked(),
            "axis": self.axis.currentIndex(),
        }
        entry = self.entry

        def applied(result):
            text = cube_bytes(result.grid).decode("utf-8")
            item = {
                "id": uuid4().hex,
                "name": "Δρ (AB − A − B)",
                "filename": "difference.cube",
                "kind": "difference_density",
                "units": result.grid.units,
                "rawText": text,
                "source": bundle["method"] + " · " + bundle["conditions"],
            }
            bundle["result_id"] = item["id"]
            self._add(item, "volume", bundle)
            self._show_profile(result.profile)

        self._job(lambda: self._replay_difference(bundle, entry, choice[0], choice[1]), applied)

    def calculate_pairs(self):
        from .compute_devices import minimum_image_pair_distances

        report = self._report()
        if "cell" not in report:
            raise ValueError("A supported geometric report is required.")
        choice = self._compute()
        if not choice:
            return

        def done(result):
            self._pairs = result
            self.pair_save.setEnabled(True)
            run = result["execution"]
            self.device_info.setText(
                f"{run.get('effective_device', '')} · {run.get('device_name', '')} · {result['pair_count']} "
                + self.t("원자쌍", "pairs")
            )

        self._job(
            lambda: minimum_image_pair_distances(
                report["positions"], report["cell"], device=choice[0], remote=choice[1]
            ),
            done,
        )

    def _save(self, data, name, filter):
        path, _ = QFileDialog.getSaveFileName(self, self.t("저장", "Save"), name, filter)
        if path:
            atomic_write(Path(path), data)

    def export_pairs(self):
        if not self._pairs:
            return
        stream = io.StringIO()
        writer = csv.writer(stream)
        writer.writerow(
            (
                "site_i",
                "site_j",
                "shift_a",
                "shift_b",
                "shift_c",
                "ase_distance_angstrom",
                "device_distance_angstrom",
                "effective_device",
            )
        )
        for pair in self._pairs["pairs"]:
            writer.writerow(
                [
                    pair["site_i"],
                    pair["site_j"],
                    *pair["shift"],
                    pair["distance_angstrom"],
                    pair["device_distance_angstrom"],
                    self._pairs["execution"]["effective_device"],
                ]
            )
        self._save(stream.getvalue().encode("utf-8-sig"), "pair-distances.csv", "CSV (*.csv)")

    def export_profile(self):
        if not self._profile:
            return
        stream = io.StringIO()
        writer = csv.writer(stream)
        writer.writerow(
            (
                "normal_position_angstrom",
                "plane_mean_e_per_angstrom3",
                "line_density_e_per_angstrom",
            )
        )
        writer.writerows(
            zip(
                self._profile["positions_angstrom"],
                self._profile["average_e_per_angstrom3"],
                self._profile["line_density_e_per_angstrom"],
            )
        )
        self._save(stream.getvalue().encode("utf-8-sig"), "plane-average.csv", "CSV (*.csv)")

    def export_profile_record(self):
        if self._profile:
            self._save(
                json.dumps(self._profile, indent=2, ensure_ascii=False).encode(),
                "plane-average.json",
                "JSON (*.json)",
            )

    def _log_from_path(self, path):
        data = bounded_read(path, 32 * 1024 * 1024)
        record = {
            "filename": path.name,
            "sha256": sha256(data).hexdigest(),
            "data": base64.b64encode(data).decode("ascii"),
        }
        return record, parse_log(data, source_name=path.name)

    def import_log(self, path):
        def done(result):
            record, report = result
            self._retain("log", record)
            self._log = report
            self._display_log()

        self._job(lambda: self._log_from_path(path), done)

    def choose_log(self):
        path, _ = QFileDialog.getOpenFileName(
            self, "Gaussian", "", "Gaussian (*.log *.out);;All files (*)"
        )
        if path:
            self.import_log(Path(path))

    def example_log(self):
        files = sorted(
            p
            for p in (self.window.root / "examples/research_cases/gaussian_reference").iterdir()
            if p.suffix.lower() in (".log", ".out")
        )
        if not files:
            raise ValueError("The Gaussian example is missing.")
        self.import_log(files[0])

    def _retain(self, key, value):
        proposed = dict(self.native)
        proposed[key] = value
        state = self.portable_state(self.window.workspace.project.workspace_state)
        state["native_research"] = proposed
        validate_workspace_state(state)
        self.native = proposed
        self.changed.emit()

    def _display_log(self):
        if not self._log:
            self.log_info.clear()
            return
        report = self._log
        info = report["provenance"]
        program = report["program"]
        lines = [
            info["name"],
            f"{program.get('name', 'Gaussian')} {program.get('version') or ''} · {report['status']}",
            f"SHA-256 {info['sha256']}",
        ]
        for step in report["steps"]:
            lines.extend(
                [
                    "",
                    f"{self.t('계산', 'Job')} {step['index']} · {step['status']} · {step['line_start']}–{step['line_end']}",
                    step.get("route") or "",
                ]
            )
            lines.append(
                f"{self.t('전하 / 다중도', 'Charge / multiplicity')}: {step.get('charge')} / {step.get('multiplicity')}"
            )
            lines.append(
                f"SCF: {step['scf']['status']}  ·  {self.t('최적화', 'Optimization')}: {step['optimization']['status']}"
            )
            energy = step.get("final_scf_energy")
            if energy:
                lines.append(
                    f"E(SCF) = {energy['value']:.12g} {energy['unit']}  ({self.t('원본 행', 'source line')} {energy.get('line')})"
                )
            modes = step["frequencies"]
            if modes["values"]:
                frequencies = ", ".join(
                    str(v.get("value_cm1", v.get("value"))) for v in modes["values"]
                )
                lines.append(f"ν (cm⁻¹): {frequencies}")
                lines.append(
                    f"{self.t('허수 진동수', 'Imaginary modes')}: {modes.get('imaginary_mode_count')}"
                )
            lines.extend(step.get("warnings", []))
        lines += report.get("warnings", [])
        self.log_info.setPlainText("\n".join(str(v) for v in lines))

    def export_log(self):
        if self._log:
            self._save(
                json.dumps(self._log, ensure_ascii=False, indent=2).encode(),
                "gaussian-report.json",
                "JSON (*.json)",
            )

    def export_log_raw(self):
        if self._log:
            raw = self.native["log"]
            self._save(
                base64.b64decode(raw["data"]), Path(raw["filename"]).name, "Gaussian (*.log *.out)"
            )

    def import_series(self, path):
        def done(result):
            bundle, report = result
            self._retain("series", bundle)
            self._series = report
            self._display_series()

        self._job(lambda: pack_series(path), done)

    def choose_series(self):
        path, _ = QFileDialog.getOpenFileName(
            self, self.t("수렴 사례", "Convergence series"), "", "JSON (*.json)"
        )
        if path:
            self.import_series(Path(path))

    def example_series(self):
        self.import_series(self.window.root / "examples/research_cases/hbn_vacuum/series.json")

    def _display_series(self):
        if not self._series:
            self.series_info.clear()
            return
        r = self._series
        lines = [
            r.get("name", ""),
            r.get("status", ""),
            r.get("summary", ""),
            f"{self.t('허용오차', 'Tolerance')}: {r.get('tolerance_mev_per_atom')} meV/atom",
            "",
        ]
        for row in r["cases"]:
            lines.append(
                f"{row['vacuum_angstrom']:g} Å  ·  {row['status']}  ·  {row.get('energy_hartree')} Eh"
            )
        for item in r.get("comparisons", []):
            lines.append(
                f"{item.get('id', item.get('case_id', ''))}: {item.get('delta_mev_per_atom')} meV/atom"
            )
        lines += r.get("warnings", [])
        self.series_info.setPlainText("\n".join(str(x) for x in lines))

    def export_series(self):
        if self._series:
            self._save(
                json.dumps(self._series, ensure_ascii=False, indent=2).encode(),
                "convergence.json",
                "JSON (*.json)",
            )
