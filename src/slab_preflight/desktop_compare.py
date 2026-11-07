"""Native two-structure comparison, including independent electronic datasets."""
from __future__ import annotations

from copy import deepcopy
from hashlib import sha256
import json

import numpy as np

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QCheckBox, QComboBox, QDialog, QDialogButtonBox, QDoubleSpinBox, QFormLayout,
    QFileDialog, QGridLayout, QHBoxLayout, QLabel, QPushButton, QScrollArea, QSizePolicy, QSplitter,
    QTableWidget, QTableWidgetItem, QVBoxLayout, QWidget,
)

from .desktop_compat import legacy_camera_state
from .desktop_view import StructureView
from .structure_compare import compare_coordinates, energy_comparison


class ComparisonDialog(QDialog):
    changed = Signal(object)

    def __init__(self, window):
        super().__init__(window)
        self.window = window
        self._updating = True
        self._linking = False
        self._entries = {}
        self._signature = None
        self._closed = False
        self.panes = []
        self.setObjectName("nativeComparison")
        self.setWindowTitle(self.t("구조 비교", "Compare structures"))
        available = window.screen().availableGeometry()
        self.resize(min(1300, max(520, available.width() - 24)), min(880, max(300, available.height() - 24)))
        self.setMinimumSize(520, 300)
        outer = QVBoxLayout(self)
        self.scroll = QScrollArea()
        self.scroll.setWidgetResizable(True)
        content = QWidget()
        layout = QVBoxLayout(content)
        self.scroll.setWidget(content)
        outer.addWidget(self.scroll, 1)
        heading = QLabel(self.t("같은 기준으로 나란히 보기", "LOOK AT THE SAME EVIDENCE, SIDE BY SIDE"))
        heading.setObjectName("eyebrow")
        layout.addWidget(heading)
        splitter = QSplitter(Qt.Orientation.Horizontal)
        self.splitter = splitter
        splitter.setHandleWidth(14)
        for side in range(2):
            body = QWidget()
            panel = QVBoxLayout(body)
            panel.setContentsMargins(2, 0, 2, 0)
            files, charge, volume = QComboBox(), QComboBox(), QComboBox()
            for selector in (files, charge, volume):
                selector.setSizeAdjustPolicy(QComboBox.SizeAdjustPolicy.AdjustToMinimumContentsLengthWithIcon)
                selector.setMinimumContentsLength(8)
                selector.setMinimumWidth(0)
                selector.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
            files.setObjectName(f"compareFile{side}")
            charge.setObjectName(f"compareCharge{side}")
            volume.setObjectName(f"compareVolume{side}")
            form = QFormLayout()
            form.setRowWrapPolicy(QFormLayout.RowWrapPolicy.WrapLongRows)
            form.setFieldGrowthPolicy(QFormLayout.FieldGrowthPolicy.AllNonFixedFieldsGrow)
            form.addRow(self.t("왼쪽 구조" if side == 0 else "오른쪽 구조", "Left structure" if side == 0 else "Right structure"), files)
            form.addRow(self.t("원자 색상", "Atom colors"), charge)
            form.addRow(self.t("전자 표면", "Surface data"), volume)
            row = QHBoxLayout()
            surface = QCheckBox(self.t("표면 표시", "Show surface"))
            level = QDoubleSpinBox()
            level.setDecimals(8)
            level.setRange(1e-8, 1e9)
            level.setValue(0.05)
            row.addWidget(surface)
            row.addWidget(level, 1)
            form.addRow(self.t("등치값 크기", "Isovalue magnitude"), row)
            units = QLabel("—")
            units.setObjectName("muted")
            form.addRow(self.t("등치값 단위", "Isovalue units"), units)
            panel.addLayout(form)
            view = StructureView(language=window.language)
            view.setMinimumSize(160, 100)
            view.set_graphics_quality(window.view.graphics_quality)
            view.restore_view_state({"representation": window.view.representation, "background": window.view.background})
            display = QHBoxLayout()
            representation = QComboBox()
            for ko, en, value in (("구·막대", "Ball and stick", "ball-stick"),
                                  ("막대", "Sticks", "stick"), ("공간 채움", "Space filling", "spacefill")):
                representation.addItem(self.t(ko, en), value)
            representation.setCurrentIndex(max(0, representation.findData(view.representation)))
            representation.setAccessibleName(self.t("원자 표현", "Representation"))
            representation.currentIndexChanged.connect(lambda _index, view=view, selector=representation: view.set_representation(selector.currentData()))
            background = QComboBox()
            for ko, en, value in (("밝은 배경", "Light background", "gradient"), ("흰색", "White", "white"),
                                  ("어두운 배경", "Dark background", "dark"), ("투명", "Transparent", "transparent")):
                background.addItem(self.t(ko, en), value)
            background.setCurrentIndex(max(0, background.findData(view.background)))
            background.setAccessibleName(self.t("화면 배경", "Scene background"))
            background.currentIndexChanged.connect(lambda _index, view=view, selector=background: view.set_background(selector.currentData()))
            display.addWidget(representation, 1)
            display.addWidget(background, 1)
            panel.addLayout(display)
            toggles = QGridLayout()
            display_toggles = {}
            for key, ko, en, attr in (("cell", "셀", "Cell", "show_cell"), ("bonds", "연결선", "Guides", "show_bonds"),
                                       ("gap", "간격", "Gap", "show_gap"), ("labels", "원소", "Labels", "show_labels")):
                toggle = QCheckBox(self.t(ko, en))
                toggle.setChecked(getattr(view, attr))
                toggle.toggled.connect(lambda checked, view=view, attr=attr: self._display_toggle(view, attr, checked))
                toggle_index = len(display_toggles)
                toggles.addWidget(toggle, toggle_index // 2, toggle_index % 2)
                display_toggles[key] = toggle
            save = QPushButton("PNG…")
            save.clicked.connect(lambda _checked=False, view=view: self._export_view(view))
            toggles.addWidget(save, 2, 0)
            figure = QPushButton(self.t("논문용…", "Figure…"))
            figure.setAccessibleName(self.t("이 비교 구조의 논문용 그림 저장", "Export publication figure for this comparison pane"))
            figure.clicked.connect(lambda _checked=False, view=view: self.window.export_publication(view=view))
            toggles.addWidget(figure, 2, 1)
            panel.addLayout(toggles)
            panel.addWidget(view, 1)
            info = QLabel()
            info.setWordWrap(True)
            info.setObjectName("muted")
            panel.addWidget(info)
            self.panes.append({"file": files, "charge": charge, "volume": volume,
                               "surface": surface, "level": level, "units": units, "view": view, "info": info,
                               "figure": figure,
                               "representation": representation, "background": background, "display_toggles": display_toggles})
            files.currentIndexChanged.connect(lambda _index, side=side: self._select_file(side))
            charge.currentIndexChanged.connect(lambda _index, side=side: self._render_electronic(side))
            volume.currentIndexChanged.connect(lambda _index, side=side: self._render_electronic(side))
            surface.toggled.connect(lambda _checked, side=side: self._render_electronic(side))
            level.valueChanged.connect(lambda _value, side=side: self._render_electronic(side))
            view.viewChanged.connect(lambda side=side: self._camera_changed(side))
            splitter.addWidget(body)
        layout.addWidget(splitter, 1)
        comparison_form = QFormLayout()
        comparison_form.setRowWrapPolicy(QFormLayout.RowWrapPolicy.WrapLongRows)
        self.coordinate_mode = QComboBox()
        for ko, en, key in (("입력 직교좌표 그대로", "Supplied Cartesian coordinates", "cartesian"),
                            ("분자 회전·이동 정렬", "Rigid fit (molecules only)", "rigid"),
                            ("같은 셀의 최소 이미지", "Minimum image (same cell)", "minimum_image")):
            self.coordinate_mode.addItem(self.t(ko, en), key)
        self.coordinate_mode.setObjectName("compareCoordinateMode")
        self.coordinate_mode.setAccessibleName(self.t("변위 계산 기준", "Displacement convention"))
        self.coordinate_mode.currentIndexChanged.connect(self._comparison_conditions_changed)
        comparison_form.addRow(self.t("변위 기준", "Displacement convention"), self.coordinate_mode)
        self.correspondence = QCheckBox(self.t("두 구조의 같은 원자 번호가 대응함을 확인", "I confirm matching source atom indices"))
        self.correspondence.setObjectName("compareCorrespondence")
        self.correspondence.toggled.connect(self._comparison_conditions_changed)
        self.conditions_reviewed = QCheckBox(self.t("에너지 비교: 원본 계산 조건의 동등성을 검토함", "Energy comparison: full original inputs reviewed as equivalent"))
        self.conditions_reviewed.setObjectName("compareConditionsReviewed")
        self.conditions_reviewed.toggled.connect(self._comparison_conditions_changed)
        comparison_form.addRow(self.correspondence)
        comparison_form.addRow(self.conditions_reviewed)
        layout.addLayout(comparison_form)
        self.metrics = QTableWidget(8, 4)
        self.metrics.setMaximumHeight(260)
        self.metrics.setHorizontalHeaderLabels([self.t("항목", "Metric"), self.t("왼쪽", "Left"),
                                                self.t("오른쪽", "Right"), self.t("차이 (오른쪽 − 왼쪽)", "Δ (right − left)")])
        self.metrics.verticalHeader().hide()
        self.metrics.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.metrics.horizontalHeader().setStretchLastSection(True)
        self.metrics.setColumnWidth(0, 240)
        self.metrics.setColumnWidth(1, 190)
        self.metrics.setColumnWidth(2, 190)
        layout.addWidget(self.metrics)
        self.coordinate_info = QLabel()
        self.coordinate_info.setObjectName("muted")
        self.coordinate_info.setWordWrap(True)
        self.coordinate_info.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        layout.addWidget(self.coordinate_info)
        controls = QGridLayout()
        self.link_cameras = QCheckBox(self.t("시점 함께 움직이기", "Link camera orientation"))
        self.shared_range = QCheckBox(self.t("같은 물리량의 색상 범위 공유", "Share range for the same quantity"))
        self.link_cameras.toggled.connect(lambda: self._camera_changed(0))
        self.shared_range.toggled.connect(lambda: self._render_electronic())
        controls.addWidget(self.link_cameras, 0, 0)
        controls.addWidget(self.shared_range, 0, 1)
        refresh = QPushButton(self.t("자료 목록 새로 고침", "Refresh datasets"))
        refresh.clicked.connect(self._refresh_datasets)
        controls.addWidget(refresh, 1, 1)
        layout.addLayout(controls)
        self.scope = QLabel(self.t(
            "원자 번호는 원본의 1번부터 시작합니다. 원자 재배열·결정 정합은 자동 수행하지 않습니다. CIF의 축과 거리 기준은 각 파일에 따릅니다. 구조·에너지 차이가 안정성이나 개선을 뜻하지 않습니다.",
            "One-based source atom indices; no automatic permutation or crystal registration. CIF metrics use each file's own axis/cutoff. Geometry or energy differences do not establish stability or improvement."))
        self.scope.setObjectName("muted")
        self.scope.setWordWrap(True)
        layout.addWidget(self.scope)
        close = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
        close.button(QDialogButtonBox.StandardButton.Close).setText(self.t("닫기", "Close"))
        close.rejected.connect(self.close)
        outer.addWidget(close)
        window.workspaceChanged.connect(self.refresh_entries)
        if window.research_panel:
            window.research_panel.changed.connect(self._refresh_datasets)
        self.refresh_entries(window.snapshot, initial=True)

    def t(self, ko, en):
        return self.window.text(ko, en)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        if hasattr(self, "splitter"):
            self.splitter.setOrientation(Qt.Orientation.Vertical if self.width() < 850 else Qt.Orientation.Horizontal)

    def _display_toggle(self, view, attribute, checked):
        setattr(view, attribute, checked)
        view.update()
        view.viewChanged.emit()

    def _export_view(self, view):
        if not view.report:
            return
        path, _ = QFileDialog.getSaveFileName(self, self.t("비교 이미지 저장", "Save comparison pane image"),
                                             "comparison.png", "PNG (*.png)")
        if path:
            try:
                preferences = getattr(self.window, "preferences", None)
                view.export_png(path, width=int(preferences.get("export_width")) if preferences else 1600,
                                background=preferences.get("export_background") if preferences else "white")
            except (OSError, ValueError, RuntimeError) as error:
                self.window.show_error(error)

    def _initial_state(self):
        if self.window.comparison_state:
            return deepcopy(self.window.comparison_state)
        state = self.window.workspace.project.workspace_state
        legacy = state.get("comparison", {})
        legacy = legacy if isinstance(legacy, dict) else {}
        viewers = state.get("viewers", {})
        viewers = viewers if isinstance(viewers, dict) else {}
        sides = []
        ids = list(self._entries)
        for side, old_key in enumerate(("before", "after")):
            entry_id = legacy.get(old_key)
            if entry_id not in self._entries:
                entry_id = ids[min(side, len(ids) - 1)]
            entry = self._entries[entry_id]
            viewer = viewers.get(f"{'left' if side == 0 else 'right'}:{entry_id}:{entry['sha256']}", {})
            viewer = viewer if isinstance(viewer, dict) else {}
            charge_ids = viewer.get("chargeDatasetIds", {})
            mode = viewer.get("colorMode")
            surface = viewer.get("surface", {})
            surface = surface if isinstance(surface, dict) else {}
            options = (self.window.research_panel.legacy_view_options(entry, "left" if side == 0 else "right")
                       if self.window.research_panel else {})
            sides.append({"entry_id": entry_id, "charge_id": options.get("charge", charge_ids.get(mode) if isinstance(charge_ids, dict) else None),
                          "volume_id": options.get("volume", viewer.get("volumeDatasetId")),
                          "surface": options.get("surface", surface.get("enabled", False)),
                          "level": options.get("level", surface.get("level", 0.05)),
                          "camera": legacy_camera_state(viewer)})
        return {"schema_version": 1, "panes": sides, "linked": bool(legacy.get("sync", False)),
                "shared_range": legacy.get("rangeMode") == "shared"}

    def refresh_entries(self, snapshot, *, initial=False):
        if self._closed:
            return
        entries = list(snapshot["entries"])
        panel = self.window.research_panel
        if panel:
            entries.extend(panel.output_entries())
        signature = [self._entry_identity(entry) for entry in entries]
        if signature == self._signature and not initial:
            return
        saved = self.portable_state() if self._signature is not None else None
        self._signature = signature
        self._entries = {entry["id"]: entry for entry in entries}
        if not self._entries:
            self._updating = True
            for pane in self.panes:
                for key in ("file", "charge", "volume"):
                    pane[key].clear()
                pane["view"].set_structure(None, {})
                pane["info"].clear()
                pane["figure"].setEnabled(False)
            self.correspondence.setChecked(False)
            self.conditions_reviewed.setChecked(False)
            self._updating = False
            self._update_metrics()
            self.changed.emit(self.portable_state())
            return
        saved = saved or self._initial_state()
        self._updating = True
        for side, pane in enumerate(self.panes):
            pane["file"].clear()
            for entry in entries:
                pane["file"].addItem(entry["filename"], entry["id"])
            previous = saved.get("panes", [])
            previous = previous[side] if isinstance(previous, list) and len(previous) > side and isinstance(previous[side], dict) else {}
            pane["file"].setCurrentIndex(max(0, pane["file"].findData(previous.get("entry_id"))))
            self._populate_datasets(side, previous)
            level = previous.get("level", 0.05)
            if type(level) in (int, float) and 0 < level <= 1e9:
                pane["level"].setValue(level)
            pane["surface"].setChecked(previous.get("surface") is True)
            self._set_structure(side)
            pane["view"].restore_view_state(previous.get("camera", {}))
            pane["representation"].setCurrentIndex(max(0, pane["representation"].findData(pane["view"].representation)))
            pane["background"].setCurrentIndex(max(0, pane["background"].findData(pane["view"].background)))
            for key, attribute in (("cell", "show_cell"), ("bonds", "show_bonds"), ("gap", "show_gap"), ("labels", "show_labels")):
                pane["display_toggles"][key].setChecked(getattr(pane["view"], attribute))
        self.link_cameras.setChecked(saved.get("linked") is True)
        self.shared_range.setChecked(saved.get("shared_range") is True)
        # Confirmations belong to this ordered pair of exact sources/geometry,
        # never to combo-box positions. Missing IDs can silently fall back when
        # a project is replaced, so restore consent only after identity matching.
        same_pair = saved.get("pair_identity") == self._pair_identity()
        self.correspondence.setChecked(same_pair and saved.get("correspondence") is True)
        self.conditions_reviewed.setChecked(same_pair and saved.get("conditions_reviewed") is True)
        self.coordinate_mode.setCurrentIndex(max(0, self.coordinate_mode.findData(saved.get("coordinate_mode"))))
        self._updating = False
        self._update_metrics()
        self._render_electronic()

    def _entry(self, side):
        return self._entries.get(self.panes[side]["file"].currentData())

    @staticmethod
    def _entry_identity(entry):
        if entry is None:
            return None
        report = entry.get("analysis", {}).get("report") or {}
        geometry = {key: report.get(key) for key in
                    ("elements", "positions", "cell", "periodic_axes", "units")}
        digest = sha256(json.dumps(geometry, sort_keys=True, allow_nan=False,
                                   separators=(",", ":")).encode()).hexdigest()
        return {"entry_id": entry["id"], "source_sha256": entry["sha256"],
                "geometry_sha256": digest, "normal_axis": entry["normal_axis"],
                "short_distance": entry["short_distance"]}

    def _pair_identity(self):
        return [self._entry_identity(self._entry(side)) for side in range(2)]

    def _populate_datasets(self, side, saved=None):
        pane = self.panes[side]
        saved = saved or {"charge_id": pane["charge"].currentData(), "volume_id": pane["volume"].currentData()}
        entry = self._entry(side)
        choices = self.window.research_panel.dataset_choices(entry) if self.window.research_panel and entry and not entry.get("output") else {"charges": [], "volumes": []}
        for key, datasets, placeholder in (
            ("charge", choices["charges"], self.t("원소 색상", "Element colors")),
            ("volume", choices["volumes"], self.t("표면 없음", "No surface")),
        ):
            selector = pane[key]
            selector.clear()
            selector.addItem(placeholder, None)
            for identifier, name, kind in datasets:
                selector.addItem(name, identifier)
                selector.setItemData(selector.count() - 1, kind, Qt.ItemDataRole.UserRole + 1)
            selector.setCurrentIndex(max(0, selector.findData(saved.get(f"{key}_id"))))

    def _select_file(self, side):
        if self._updating:
            return
        self._updating = True
        self.correspondence.setChecked(False)
        self.conditions_reviewed.setChecked(False)
        self._populate_datasets(side, {})
        self.panes[side]["surface"].setChecked(False)
        self._set_structure(side)
        self._updating = False
        self._update_metrics()
        self._render_electronic()

    def _set_structure(self, side):
        pane, entry = self.panes[side], self._entry(side)
        report = entry["analysis"].get("report") if entry else None
        metadata = {"filename": entry["filename"], "sha256": entry["sha256"]} if entry else {}
        if entry and entry.get("output"):
            output = entry["output"]
            geometry = output["step"]["final_geometry"]
            metadata.update({"source_filename": output["provenance"]["name"],
                             "source_sha256": entry["sha256"],
                             "program": output["program"], "job_index": output["step"]["index"],
                             "execution_status": output["step"]["status"],
                             "electronic_status": output["step"]["scf"]["status"],
                             "geometry_source": geometry["source"],
                             "geometry_line_start": geometry["line_start"],
                             "geometry_line_end": geometry["line_end"],
                             "coordinate_units": "angstrom"})
        pane["view"].set_structure(report, metadata)
        pane["figure"].setEnabled(report is not None)
        if report:
            description = f"{report['formula']} · {report['atom_count']} " + self.t("원자", "atoms")
            if entry.get("output"):
                output = entry["output"]
                geometry = output["step"]["final_geometry"]
                description += (f" · Å · {geometry['source']} · {geometry['line_start']}–{geometry['line_end']}\n"
                                f"SHA-256 {entry['sha256']}\n"
                                f"{self.t('실행 / 전자 수렴', 'Execution / electronic convergence')}: "
                                f"{output['step']['status']} / {output['step']['scf']['status']}")
                energy = output["step"].get("final_energy")
                if energy:
                    description += f"\n{energy['kind']}: {energy['value']:.12g} {energy['unit']} (line {energy['line']})"
            else:
                description += self.t(f" · {entry['normal_axis']}축 · 짧은 거리 {entry['short_distance']:g} Å",
                                      f" · axis {entry['normal_axis']} · cutoff {entry['short_distance']:g} Å")
            pane["info"].setText(description)
        else:
            error = entry["analysis"].get("error_ko" if self.window.language == "ko" else "error") if entry else ""
            pane["info"].setText(str(error or ""))

    def _refresh_datasets(self):
        if self._updating or self._closed:
            return
        self.refresh_entries(self.window.snapshot)
        saved = self.portable_state()
        self._updating = True
        for side in range(2):
            self._populate_datasets(side, saved["panes"][side])
        self._updating = False
        self._render_electronic()

    def _render_electronic(self, changed_side=None):
        if self._updating or self._closed:
            return
        extents = []
        panel = self.window.research_panel
        try:
            for side, pane in enumerate(self.panes):
                entry = self._entry(side)
                charge_id = pane["charge"].currentData()
                extents.append(panel.charge_extent(entry, charge_id) if panel and entry and charge_id else None)
                get_units = getattr(panel, "volume_units", None)
                units = get_units(entry, pane["volume"].currentData()) if get_units and entry and pane["volume"].currentData() else "—"
                pane["units"].setText({"e/angstrom^3": "e/Å³", "angstrom^-3/2": "Å⁻³/²",
                                        "arbitrary": self.t("임의 단위", "Arbitrary units")}.get(units, units))
            comparable = bool(extents[0] and extents[1] and extents[0][0] == extents[1][0])
            self.shared_range.setEnabled(comparable)
            if not comparable:
                if self.shared_range.isChecked():
                    changed_side = None
                self.shared_range.blockSignals(True)
                self.shared_range.setChecked(False)
                self.shared_range.blockSignals(False)
            shared = (max(extent[1] for extent in extents) or 1.0) if comparable and self.shared_range.isChecked() else None
            for side, pane in enumerate(self.panes):
                if changed_side is not None and side != changed_side and shared is None:
                    continue
                entry = self._entry(side)
                if panel and entry and pane["view"].report and not entry.get("output"):
                    panel.apply_view_dataset(pane["view"], entry, charge_id=pane["charge"].currentData(),
                                             volume_id=pane["volume"].currentData() if pane["surface"].isChecked() else None,
                                             level=pane["level"].value(), shared_extent=shared)
                else:
                    pane["view"].clear_electronic()
            self.changed.emit(self.portable_state())
        except (OSError, ValueError, TypeError, KeyError, RuntimeError) as error:
            self.window.show_error(error)

    def _update_metrics(self):
        entries = [self._entry(side) for side in range(2)]
        reports = [entry["analysis"].get("report") if entry else None for entry in entries]
        rows = [
            (self.t("원자 수", "Atom count"), "atom_count", False),
            (self.t("최소 주기 거리 / Å", "Minimum periodic distance / Å"), "minimum_distance_angstrom", True),
            (self.t("원자핵 두께 / Å", "Nuclei thickness / Å"), "nuclei_thickness_angstrom", True),
            (self.t("원자핵 간격 / Å", "Nuclei gap / Å"), "nuclei_gap_angstrom", True),
        ]
        for row, (name, key, metric) in enumerate(rows):
            values = [(report.get("metrics", {}).get(key) if metric else report.get(key)) if report else None for report in reports]
            comparable = all(value is not None for value in values)
            if key in ("nuclei_thickness_angstrom", "nuclei_gap_angstrom"):
                comparable = comparable and entries[0]["normal_axis"] == entries[1]["normal_axis"]
            cells = [name, *(f"{value:.6g}" if value is not None else "—" for value in values),
                     f"{values[1] - values[0]:+.6g}" if comparable else "—"]
            for column, value in enumerate(cells):
                self.metrics.setItem(row, column, QTableWidgetItem(value))
        comparison = compare_coordinates(*reports, correspondence=self.correspondence.isChecked(),
                                         mode=self.coordinate_mode.currentData())
        self.coordinate_comparison = comparison
        for row, name, key in ((4, self.t("대응 원자 RMSD / Å", "Matched-atom RMSD / Å"), "rmsd"),
                               (5, self.t("최대 원자 변위 / Å", "Maximum atom displacement / Å"), "maximum")):
            value = comparison.get(key)
            for column, cell in enumerate([name, "—", "—", f"{value:.6g}" if value is not None else "—"]):
                self.metrics.setItem(row, column, QTableWidgetItem(cell))
        volumes = []
        for report in reports:
            cell = np.asarray(report.get("cell"), float) if report else np.asarray(None)
            volumes.append(abs(float(np.linalg.det(cell))) if cell.shape == (3, 3) else None)
        cells = [self.t("셀 부피 / Å³", "Cell volume / Å³"),
                 *(f"{v:.6g}" if v is not None else "—" for v in volumes),
                 f"{volumes[1] - volumes[0]:+.6g}" if all(v is not None for v in volumes) else "—"]
        for column, cell in enumerate(cells):
            self.metrics.setItem(6, column, QTableWidgetItem(cell))
        energy = energy_comparison(*entries, reviewed=self.conditions_reviewed.isChecked())
        self.energy_comparison = energy
        energy_values = [(entry or {}).get("output", {}).get("step", {}).get("final_energy") for entry in entries]
        cells = [self.t("출력 에너지 / 표기 단위", "Output energy / printed units"),
                 *(f"{e['value']:.10g} {e['unit']} ({e['kind']})" if e else "—" for e in energy_values),
                 f"{energy['delta']:+.10g} eV" if energy["status"] == "available" else "—"]
        for column, cell in enumerate(cells):
            self.metrics.setItem(7, column, QTableWidgetItem(cell))
        self.coordinate_info.setText("\n".join([
            comparison.get("reference", comparison.get("reason", "")),
            (f"{self.t('가장 큰 변위: 원자', 'Largest displacement: atom')} {comparison['largest_atom_index']}"
             if comparison.get("status") == "available" else ""), energy["reason"],
        ]))

    def _comparison_conditions_changed(self, *_args):
        if self._updating:
            return
        self._update_metrics()
        self.changed.emit(self.portable_state())

    def select_output(self, identifier, *, side=1):
        self.refresh_entries(self.window.snapshot)
        index = self.panes[side]["file"].findData(identifier)
        if index >= 0:
            self.panes[side]["file"].setCurrentIndex(index)

    def _camera_changed(self, side):
        if self._updating or self._linking:
            return
        if self.link_cameras.isChecked():
            self._linking = True
            state = self.panes[side]["view"].view_state()
            self.panes[1 - side]["view"].restore_view_state({key: state[key] for key in ("yaw", "pitch", "roll", "zoom", "pan")})
            self._linking = False
        self.changed.emit(self.portable_state())

    def portable_state(self):
        return {"schema_version": 1, "linked": self.link_cameras.isChecked(), "shared_range": self.shared_range.isChecked(),
                "correspondence": self.correspondence.isChecked(), "conditions_reviewed": self.conditions_reviewed.isChecked(),
                "pair_identity": self._pair_identity(),
                "coordinate_mode": self.coordinate_mode.currentData(),
                "panes": [{"entry_id": pane["file"].currentData(), "charge_id": pane["charge"].currentData(),
                           "volume_id": pane["volume"].currentData(), "surface": pane["surface"].isChecked(),
                           "level": pane["level"].value(), "camera": pane["view"].view_state()} for pane in self.panes]}

    def closeEvent(self, event):
        self.changed.emit(self.portable_state())
        self._closed = True
        for pane in self.panes:
            self.window.cancel_job(f"comparison-surface-{id(pane['view'])}")
        event.accept()
