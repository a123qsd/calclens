"""CalcLens native Qt Widgets desktop application.

The scientific workspace is called in process. This module never starts an HTTP
server, embeds HTML, or opens a browser.
"""
from __future__ import annotations

import base64
from copy import deepcopy
from dataclasses import replace
from datetime import datetime
import json
import math
from pathlib import Path
import sys
import threading
from typing import Callable

import ase
from PySide6.QtCore import QEvent, QObject, QRunnable, QThreadPool, QTimer, Qt, Signal, Slot, QSize, QSignalBlocker
from PySide6.QtGui import QAction, QIcon, QKeySequence, QTextOption, QKeyEvent
from PySide6.QtWidgets import (
    QApplication, QCheckBox, QComboBox, QDialog, QDialogButtonBox, QDoubleSpinBox,
    QFileDialog, QFormLayout, QFrame, QHBoxLayout, QLabel, QLayout, QLineEdit, QListWidget,
    QListWidgetItem, QMainWindow, QMessageBox, QPlainTextEdit, QProgressBar,
    QPushButton, QScrollArea, QSpinBox, QSplitter, QTabWidget,
    QTextBrowser, QToolBar, QToolButton, QVBoxLayout, QWidget, QSizePolicy,
)

from . import __version__
from .core import analyze_cif
from .desktop_compat import legacy_camera_state, legacy_draft
from .desktop_view import StructureView
from .desktop_preferences import DesktopPreferences
from .desktop_theme import apply_theme, system_scheme_changed
from .desktop_menus import display_menu, settings_menu
from .project import ANALYSIS_REVISION, MAX_ARCHIVE_BYTES, MAX_FILE_BYTES, dumps_project_archive
from .reporting import localized_error_message, localized_report, report_csv
from .recovery import atomic_write
from .startup import set_language
from .web_api import APIError, Workspace


class _JobSignals(QObject):
    finished = Signal(object)


class _Job(QRunnable):
    def __init__(self, token, key, function):
        super().__init__()
        self.token, self.key, self.function = token, key, function
        self.signals = _JobSignals()
        self.started = threading.Event()
        self.cancelled = threading.Event()

    def run(self):
        self.started.set()
        try:
            payload = (self.token, self.key, True, None if self.cancelled.is_set() else self.function())
        except Exception as error:
            payload = (self.token, self.key, False, error)
        self.signals.finished.emit(payload)


class _FileOpenFilter(QObject):
    """Receive macOS Finder document-open events as native local file paths."""

    def __init__(self, window, parent):
        super().__init__(parent)
        self.window = window

    def eventFilter(self, watched, event):
        if event.type() == QEvent.Type.FileOpen:
            path = Path(event.file())
            if path.suffix.lower() == ".cif":
                QTimer.singleShot(0, lambda: self.window.open_cifs([path]))
            elif path.suffix.lower() in (".zip", ".json"):
                QTimer.singleShot(0, lambda: self.window.open_project(path))
            else:
                self.window.show_error(self.window.text("지원하는 CIF 또는 작업 파일을 선택하세요.",
                                                       "Choose a CIF file or a CalcLens project."))
            event.accept()
            return True
        return False


class MainWindow(QMainWindow):
    """Native workspace with injectable storage and scientific tools.

    Public integration: workspace, snapshot, selected_entry, view, submit(),
    apply_action(), refresh(), mark_dirty(), save_project(), open_project().
    Pass recovery=False and research_factory=False for isolated Qt tests.
    """

    workspaceChanged = Signal(object)
    selectedEntryChanged = Signal(object)
    errorOccurred = Signal(str)
    busyChanged = Signal(bool)

    def __init__(self, language=None, *, workspace=None, recovery=None,
                 research_factory=None, root=None, parent=None, defer_startup=False):
        super().__init__(parent)
        QApplication.setAttribute(Qt.ApplicationAttribute.AA_DontUseNativeDialogs, True)
        self.preferences = DesktopPreferences()
        self.language = language if language in ("ko", "en") else self.preferences.get("language")
        set_language(self.language)
        self.local_devices = []
        self._defer_startup = defer_startup
        self._sidebar_requested = True
        self._inspector_requested = True
        self._compact_panel = "scene"
        self._narrow = None
        self._bench_input = False
        self.root = Path(root) if root else Path(__file__).resolve().parents[2]
        for icon in (self.root / "CalcLens.ico", self.root / "packaging/desktop/CalcLens.ico"):
            if icon.is_file():
                self.setWindowIcon(QIcon(str(icon)))
                break
        self.workspace = workspace or Workspace(self.root, self.language, load_default=not defer_startup)
        self.snapshot = {}
        self.selected_entry = None
        self.project_path = None
        self.dirty = False
        self._closing = False
        self._updating = False
        self._drafts = {}
        self._view_states = {}
        self.comparison_state = {}
        self._comparison_dialog = None
        self._structure_key = None
        self._jobs = {}
        self._job_counter = 0
        self._latest = {}
        self._pool = QThreadPool(self)
        self._pool.setMaxThreadCount(1)
        self._workspace_pool = QThreadPool(self)
        self._workspace_pool.setMaxThreadCount(1)
        self._probe_pool = QThreadPool(self)
        self._probe_pool.setMaxThreadCount(1)
        self._io_pool = QThreadPool(self)
        self._io_pool.setMaxThreadCount(1)
        self.recovery = None
        self._recovery_candidate = None
        self._last_saved = None
        self._last_recovery = None
        self._change_counter = 0
        startup_recovery_error = None
        if recovery is not False:
            if recovery is None:
                try:
                    from .recovery import RecoveryStore
                    recovery = RecoveryStore()
                except (ImportError, OSError, ValueError) as error:
                    startup_recovery_error = error
                    recovery = None
            self.recovery = recovery
        self._backup_timer = QTimer(self)
        self._backup_timer.setSingleShot(True)
        self._backup_timer.setInterval(1400)
        self._backup_timer.timeout.connect(self._save_recovery)
        self.setObjectName("calcLensMainWindow")
        # Let resizeEvent select a compact panel before a wide layout can clamp the window.
        self.layout().setSizeConstraint(QLayout.SizeConstraint.SetNoConstraint)
        self.setMinimumSize(360, 260)
        area = QApplication.primaryScreen().availableGeometry()
        self.resize(min(1440, area.width()), min(900, area.height()))
        self.setAcceptDrops(True)
        apply_theme(self.preferences.get("theme"))
        QApplication.styleHints().colorSchemeChanged.connect(self._platform_theme)
        self._build_ui(research_factory)
        if not defer_startup:
            self._apply_snapshot(self.workspace.snapshot(include_workspace=True), restore=True)
        self._update_title()
        QTimer.singleShot(0, self._offer_recovery)
        if startup_recovery_error is not None:
            QTimer.singleShot(0, lambda: self.show_error(startup_recovery_error))

    def text(self, ko, en):
        return ko if self.language == "ko" else en

    def _button(self, ko, en, function, *, primary=False, name=None):
        button = QPushButton(self.text(ko, en))
        if primary:
            button.setObjectName("primary")
        if name:
            button.setObjectName(name)
        button.clicked.connect(function)
        return button

    def _build_ui(self, research_factory):
        self.toolbar = QToolBar(self)
        self.toolbar.setMovable(False)
        self.addToolBar(self.toolbar)
        brand = QLabel("CalcLens")
        brand.setObjectName("brand")
        self.toolbar.addWidget(brand)
        self.open_button = self._button("CIF 열기", "Open CIF", self.choose_cifs, primary=True)
        self.project_open_button = self._button("작업 열기", "Open project", self.choose_project)
        self.save_button = self._button("작업 저장", "Save project", self.save_project)
        self.compare_button = self._button("구조 비교", "Compare", self.compare_structures)
        for button in (self.open_button, self.project_open_button, self.save_button, self.compare_button):
            self.toolbar.addWidget(button)
        self.examples = QComboBox()
        self.examples.setObjectName("examplesCombo")
        self.examples.setSizeAdjustPolicy(QComboBox.SizeAdjustPolicy.AdjustToMinimumContentsLengthWithIcon)
        self.example_button = self._button("예제 열기", "Load example", self._load_selected_example)
        self.settings_button = QToolButton()
        self.settings_button.setText(self.text("설정", "Settings"))
        self.settings_button.setPopupMode(QToolButton.ToolButtonPopupMode.InstantPopup)
        self.settings_menu = settings_menu(self)
        self.settings_button.setMenu(self.settings_menu)
        self.toolbar.addWidget(self.settings_button)
        spacer = QWidget()
        spacer.setSizePolicy(spacer.sizePolicy().horizontalPolicy().Expanding,
                             spacer.sizePolicy().verticalPolicy().Preferred)
        self.toolbar.addWidget(spacer)
        self.files_toggle = self._button("파일 목록", "Files", self._toggle_sidebar)
        self.inspector_toggle = self._button("검사 패널", "Inspector", self._toggle_inspector)
        self.toolbar.addWidget(self.files_toggle)
        self.toolbar.addWidget(self.inspector_toggle)
        self.language_combo = QComboBox()
        self.language_combo.addItem("한국어", "ko")
        self.language_combo.addItem("English", "en")
        self.language_combo.setCurrentIndex(0 if self.language == "ko" else 1)
        self.language_combo.currentIndexChanged.connect(self._change_language)
        self.toolbar.addWidget(self.language_combo)
        file_menu = self.menuBar().addMenu(self.text("파일", "File"))
        modifier = "Meta" if sys.platform == "darwin" else "Ctrl"
        for title, shortcut, function in (
            (self.text("CIF 열기…", "Open CIF…"), QKeySequence.StandardKey.Open, self.choose_cifs),
            (self.text("작업 열기…", "Open project…"), f"{modifier}+Shift+O", self.choose_project),
            (self.text("작업 저장", "Save project"), QKeySequence.StandardKey.Save, self.save_project),
            (self.text("다른 이름으로 저장…", "Save project as…"), QKeySequence.StandardKey.SaveAs, lambda: self.save_project(save_as=True)),
            (self.text("PNG 내보내기…", "Export PNG…"), f"{modifier}+E", self.export_png),
            (self.text("논문용 그림 내보내기…", "Export publication figure…"), f"{modifier}+Alt+E", self.export_publication),
        ):
            action = QAction(title, file_menu)
            action.setShortcut(shortcut)
            action.triggered.connect(function)
            file_menu.addAction(action)
        quit_action = QAction(self.text("종료", "Quit"), file_menu)
        quit_action.setShortcut(QKeySequence.StandardKey.Quit)
        quit_action.setMenuRole(QAction.MenuRole.QuitRole)
        quit_action.triggered.connect(self.close)
        file_menu.addAction(quit_action)
        compare_action = QAction(self.text("구조 비교…", "Compare structures…"), self)
        compare_action.setShortcut(f"{modifier}+Shift+C")
        compare_action.triggered.connect(self.compare_structures)
        self.menuBar().addAction(compare_action)
        self.menuBar().addMenu(self.settings_menu)
        self.body = QWidget()
        outer = QVBoxLayout(self.body)
        outer.setContentsMargins(8, 6, 8, 4)
        outer.setSpacing(10)
        self.error_label = QLabel()
        self.error_label.setObjectName("errorBanner")
        self.error_label.setWordWrap(True)
        self.error_label.setTextFormat(Qt.TextFormat.PlainText)
        self.error_label.hide()
        outer.addWidget(self.error_label)
        self.recovery_frame = QFrame()
        recovery_layout = QHBoxLayout(self.recovery_frame)
        recovery_layout.setContentsMargins(0, 0, 0, 0)
        self.recovery_label = QLabel()
        self.recovery_label.setObjectName("recoveryBanner")
        self.recovery_label.setWordWrap(True)
        recovery_layout.addWidget(self.recovery_label, 1)
        recovery_layout.addWidget(self._button("복구", "Restore", self.restore_recovery))
        recovery_layout.addWidget(self._button("나중에", "Later", self.recovery_frame.hide))
        self.recovery_frame.hide()
        outer.addWidget(self.recovery_frame)
        self.progress = QProgressBar()
        self.progress.setRange(0, 0)
        self.progress.hide()
        outer.addWidget(self.progress)
        self.splitter = QSplitter(Qt.Orientation.Horizontal)
        self.splitter.setHandleWidth(6)
        outer.addWidget(self.splitter, 1)
        self.setCentralWidget(self.body)
        self._build_sidebar()
        self._build_scene()
        self._build_inspector(research_factory)
        self.splitter.setStretchFactor(0, 0)
        self.splitter.setStretchFactor(1, 1)
        self.splitter.setStretchFactor(2, 0)
        self.splitter.setSizes([195, 750, 335])
        self._update_panels()
        self.status_label = QLabel()
        self.statusBar().addWidget(self.status_label, 1)
        self.time_label = QLabel()
        self.statusBar().addPermanentWidget(self.time_label)
        self._refresh_status()

    def _build_sidebar(self):
        self.sidebar = QFrame()
        self.sidebar.setObjectName("sidebar")
        self.sidebar.setMinimumWidth(155)
        self.sidebar.setMaximumWidth(330)
        layout = QVBoxLayout(self.sidebar)
        layout.setContentsMargins(15, 20, 15, 15)
        eyebrow = QLabel(self.text("작업 공간", "WORKSPACE"))
        eyebrow.setStyleSheet("font-size:10px; letter-spacing:2px; color:#93b4be;")
        layout.addWidget(eyebrow)
        self.file_count = QLabel()
        self.file_count.setStyleSheet("font-size:19px; font-weight:600; padding:5px 0 10px;")
        layout.addWidget(self.file_count)
        self.file_search = QLineEdit()
        self.file_search.setPlaceholderText(self.text("파일 이름 검색", "Find a file"))
        self.file_search.textChanged.connect(self._filter_files)
        layout.addWidget(self.file_search)
        self.file_list = QListWidget()
        self.file_list.setObjectName("fileList")
        self.file_list.currentItemChanged.connect(self._select_item)
        layout.addWidget(self.file_list, 1)
        self.remove_button = self._button("선택 파일 제거", "Remove selected", self.remove_selected)
        layout.addWidget(self.remove_button)
        layout.addWidget(self.examples)
        layout.addWidget(self.example_button)
        hint = QLabel(self.text("CIF 파일을 이 창으로 끌어 놓을 수 있습니다.",
                                "Drop CIF files into this window to add them."))
        hint.setWordWrap(True)
        hint.setStyleSheet("color:#94aebc; font-size:11px; padding-top:12px;")
        layout.addWidget(hint)
        self.splitter.addWidget(self.sidebar)

    def _build_scene(self):
        center = self.center = QWidget()
        layout = QVBoxLayout(center)
        layout.setContentsMargins(2, 0, 2, 0)
        header = QHBoxLayout()
        heading = QVBoxLayout()
        self.structure_title = QLabel()
        self.structure_title.setObjectName("heading")
        self.structure_subtitle = QLabel()
        self.structure_subtitle.setObjectName("muted")
        heading.addWidget(self.structure_title)
        self.structure_subtitle.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
        self.structure_title.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
        heading.addWidget(self.structure_subtitle)
        header.addLayout(heading, 1)
        self.png_button = self._button("이미지 저장", "Export PNG", self.export_png)
        header.addWidget(self.png_button)
        layout.addLayout(header)
        card = QFrame()
        card.setObjectName("card")
        card_layout = QVBoxLayout(card)
        card_layout.setContentsMargins(1, 1, 1, 1)
        self.view = StructureView(language=self.language)
        self.view.set_graphics_quality(self.preferences.get("quality"))
        self.view.atomPicked.connect(self._atom_picked)
        self.view.viewChanged.connect(self._view_changed)
        card_layout.addWidget(self.view, 1)
        tools = QHBoxLayout()
        tools.setContentsMargins(11, 5, 11, 9)
        self.preset_combo = QComboBox()
        for ko, en, value in (("입체 보기", "3D view", "perspective"), ("위에서", "Top", "top"),
                              ("정면", "Front", "front"), ("옆면", "Side", "side")):
            self.preset_combo.addItem(self.text(ko, en), value)
        self.preset_combo.currentIndexChanged.connect(lambda: self.view.reset_view(self.preset_combo.currentData()))
        tools.addWidget(self.preset_combo)
        display = QToolButton()
        display.setText(self.text("표시", "Display"))
        display.setPopupMode(QToolButton.ToolButtonPopupMode.InstantPopup)
        display.setMenu(display_menu(self))
        tools.addWidget(display)
        tools.addStretch()
        tools.addWidget(self._button("초기화", "Reset", self.view.reset_view))
        card_layout.addLayout(tools)
        toggles = QHBoxLayout()
        toggles.setContentsMargins(8, 0, 8, 4)
        self.view_toggles = {}
        for key, ko, en, attribute in (
            ("cell", "셀", "Cell", "show_cell"), ("bonds", "연결선", "Guides", "show_bonds"),
            ("gap", "간격", "Gap", "show_gap"), ("labels", "원소", "Labels", "show_labels"),
        ):
            checkbox = QCheckBox(self.text(ko, en))
            checkbox.setChecked(getattr(self.view, attribute))
            checkbox.toggled.connect(lambda checked, attr=attribute: self._toggle_view(attr, checked))
            self.view_toggles[key] = checkbox
            toggles.addWidget(checkbox)
        toggles.addStretch()
        card_layout.addLayout(toggles)
        layout.addWidget(card, 1)
        self.metrics_widget = QWidget()
        metrics = QHBoxLayout(self.metrics_widget)
        metrics.setContentsMargins(0, 0, 0, 0)
        self.metric_labels = []
        for ko, en in (("최소 주기 거리", "Minimum periodic distance"),
                       ("원자핵 두께", "Nuclei thickness"), ("원자핵 간격", "Nuclei gap")):
            metric = QFrame()
            metric.setObjectName("card")
            metric_layout = QVBoxLayout(metric)
            name = QLabel(self.text(ko, en))
            name.setObjectName("muted")
            name.setWordWrap(True)
            number = QLabel("—")
            number.setObjectName("metricValue")
            metric_layout.addWidget(name)
            metric_layout.addWidget(number)
            self.metric_labels.append(number)
            metrics.addWidget(metric)
        layout.addWidget(self.metrics_widget)
        footnote = QLabel(self.text(
            "입력 기하를 확인합니다. 안정성·화학 결합·계산 수렴을 판정하지 않습니다.",
            "Supplied geometry only. Stability, chemical bonds and convergence require separate evidence."))
        self.scene_note = footnote
        footnote.setObjectName("muted")
        footnote.setWordWrap(True)
        layout.addWidget(footnote)
        self.splitter.addWidget(center)

    def _build_inspector(self, research_factory):
        self.tabs = QTabWidget()
        self.tabs.setMinimumWidth(230)
        settings = QWidget()
        settings.setObjectName("inspectorPage")
        layout = QVBoxLayout(settings)
        layout.setContentsMargins(15, 18, 15, 15)
        self.entry_status = QLabel()
        self.entry_status.setWordWrap(True)
        self.entry_status.setTextFormat(Qt.TextFormat.PlainText)
        self.entry_status.setMinimumHeight(27)
        self.entry_status.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Minimum)
        layout.addWidget(self.entry_status)
        form = QFormLayout()
        form.setRowWrapPolicy(QFormLayout.RowWrapPolicy.WrapLongRows)
        form.setVerticalSpacing(6)
        self.axis_combo = QComboBox()
        self.axis_combo.setObjectName("normalAxis")
        self.axis_combo.addItems(["a", "b", "c"])
        self.cutoff_spin = QDoubleSpinBox()
        self.cutoff_spin.setObjectName("shortDistance")
        self.cutoff_spin.setRange(0.1, 3.0)
        self.cutoff_spin.setDecimals(2)
        self.cutoff_spin.setSingleStep(0.1)
        self.cutoff_spin.setSuffix(" Å")
        form.addRow(self.text("수직 방향 축", "Normal axis"), self.axis_combo)
        form.addRow(self.text("짧은 거리 기준", "Short-contact cutoff"), self.cutoff_spin)
        layout.addLayout(form)
        self.note_edit = QPlainTextEdit()
        self.note_edit.setObjectName("entryNote")
        self.note_edit.setPlaceholderText(self.text("이 구조에 대한 메모…", "Notes for this structure…"))
        self.note_edit.setMaximumHeight(110)
        layout.addWidget(self.note_edit)
        self.draft_label = QLabel()
        self.draft_label.setObjectName("muted")
        layout.addWidget(self.draft_label)
        self.apply_button = self._button("변경 적용", "Apply changes", self.apply_settings, primary=True)
        layout.addWidget(self.apply_button)
        self.review_check = QCheckBox(self.text("이 구조 검토 완료", "Mark this structure reviewed"))
        self.review_check.setObjectName("reviewedCheck")
        self.review_check.toggled.connect(self._set_reviewed)
        layout.addWidget(self.review_check)
        self.prepare_button = self._button("P1 구조 준비…", "Prepare P1…", self.preview_preparation)
        layout.addWidget(self.prepare_button)
        divider = QFrame()
        divider.setFrameShape(QFrame.Shape.HLine)
        divider.setFrameShadow(QFrame.Shadow.Plain)
        layout.addWidget(divider)
        label = QLabel(self.text("원자 사이 거리", "PAIR MEASUREMENT"))
        label.setObjectName("eyebrow")
        layout.addWidget(label)
        pair_row = QHBoxLayout()
        self.first_atom = QSpinBox()
        self.second_atom = QSpinBox()
        for spin in (self.first_atom, self.second_atom):
            spin.setRange(1, 400)
            spin.setPrefix("# ")
        self.second_atom.setValue(2)
        for spin in (self.first_atom, self.second_atom):
            spin.valueChanged.connect(self._pair_changed)
        pair_row.addWidget(self.first_atom)
        pair_row.addWidget(QLabel("↔"))
        pair_row.addWidget(self.second_atom)
        layout.addLayout(pair_row)
        self.measurement_mode = QComboBox()
        self.measurement_mode.addItem(self.text("최단 주기 이미지", "Minimum periodic image"), "minimum_image")
        self.measurement_mode.addItem(self.text("표시 이미지 지정", "Specified images"), "displayed")
        self.measurement_mode.currentIndexChanged.connect(self._measurement_mode_changed)
        layout.addWidget(self.measurement_mode)
        self.shift_widget = QWidget()
        shifts = QFormLayout(self.shift_widget)
        shifts.setContentsMargins(0, 0, 0, 0)
        self.shift_spins = []
        for ko, en in (("첫 원자 이동", "First shift"), ("둘째 원자 이동", "Second shift")):
            row = QHBoxLayout()
            spins = []
            for _ in range(3):
                spin = QSpinBox()
                spin.setRange(-9, 9)
                spin.valueChanged.connect(self._pair_changed)
                spins.append(spin)
                row.addWidget(spin)
            self.shift_spins.append(spins)
            shifts.addRow(self.text(ko, en), row)
        self.shift_widget.hide()
        layout.addWidget(self.shift_widget)
        self.measure_button = self._button("거리 계산", "Measure distance", self.measure_pair)
        layout.addWidget(self.measure_button)
        self.measurement_label = QLabel(self.text("화면에서 원자 두 개를 선택할 수도 있습니다.",
                                                "You can also pick two atoms in the view."))
        self.measurement_label.setWordWrap(True)
        self.measurement_label.setObjectName("muted")
        layout.addWidget(self.measurement_label)
        self.save_measure_button = self._button("측정 선택 저장", "Save pair selection", self.save_measurement)
        layout.addWidget(self.save_measure_button)
        self.saved_measurements = QListWidget()
        self.saved_measurements.setMaximumHeight(100)
        self.saved_measurements.itemClicked.connect(self._restore_measurement)
        layout.addWidget(self.saved_measurements)
        self.hash_label = QLabel()
        self.hash_label.setObjectName("muted")
        self.hash_label.setWordWrap(True)
        self.hash_label.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        layout.addWidget(self.hash_label)
        detail_button = self.details_button = self._button("출처 상세", "Source details", self._toggle_source_details)
        detail_button.setCheckable(True)
        detail_row = QHBoxLayout()
        detail_row.addWidget(detail_button)
        detail_row.addWidget(self._button("해시 복사", "Copy SHA256", self.copy_hash))
        layout.addLayout(detail_row)
        self.source_details = QPlainTextEdit()
        self.source_details.setReadOnly(True)
        self.source_details.setWordWrapMode(QTextOption.WrapMode.WrapAnywhere)
        self.source_details.setMaximumHeight(150)
        self.source_details.hide()
        layout.addWidget(self.source_details)
        self.original_button = self._button("원본 CIF 저장…", "Save original CIF…", self.save_original_cif)
        self.original_button.hide()
        layout.addWidget(self.original_button)
        layout.addStretch()
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setWidget(settings)
        self.tabs.addTab(scroll, self.text("구조", "Structure"))
        result_panel = QWidget()
        result_panel.setObjectName("inspectorPage")
        result_layout = QVBoxLayout(result_panel)
        self.report_text = QTextBrowser()
        self.report_text.setOpenExternalLinks(False)
        result_layout.addWidget(self.report_text, 1)
        exports = QHBoxLayout()
        exports.addWidget(self._button("CSV 저장", "Export CSV", lambda: self.export_report("csv")))
        exports.addWidget(self._button("JSON 저장", "Export JSON", lambda: self.export_report("json")))
        result_layout.addLayout(exports)
        self.tabs.addTab(result_panel, self.text("분석 결과", "Report"))
        self.research_panel = None
        self._research_factory = research_factory
        if research_factory is not False:
            self._research_placeholder = QWidget()
            self.tabs.addTab(self._research_placeholder, self.text("연구 도구", "Research"))
            if not self._defer_startup:
                self._ensure_research()
            self.tabs.currentChanged.connect(self._tab_changed)
        self.splitter.addWidget(self.tabs)
        self.axis_combo.currentIndexChanged.connect(self._draft_changed)
        self.cutoff_spin.valueChanged.connect(self._draft_changed)
        self.note_edit.textChanged.connect(self._draft_changed)

    def _ensure_research(self):
        if self.research_panel is not None or self._research_factory is False:
            return self.research_panel
        factory = self._research_factory
        if factory is None:
            from .desktop_research import ResearchPanel
            factory = ResearchPanel
        panel = factory(self)
        with QSignalBlocker(self.tabs):
            index = self.tabs.indexOf(self._research_placeholder)
            active = self.tabs.currentIndex()
            self.tabs.removeTab(index)
            self.tabs.insertTab(index, panel, self.text("연구 도구", "Research"))
            self.tabs.setCurrentIndex(active)
        self._research_placeholder.deleteLater()
        self.research_panel = panel
        panel.changed.connect(self.mark_dirty)
        if self.snapshot and self._structure_key is not None:
            panel.restore_state(self.workspace.project.workspace_state)
            panel.set_entry(self.selected_entry, self.language)
        from .startup import mark
        mark("research_ready")
        return panel

    def _tab_changed(self, index):
        if self.research_panel is None and index == 2:
            self._ensure_research()

    def open_compute_settings(self):
        panel = self._ensure_research()
        if panel:
            self._inspector_requested = True
            self._compact_panel = "inspector"
            self._update_panels()
            self.tabs.setCurrentWidget(panel)
            panel.mode.setCurrentIndex(1)
            panel.devices.ensure_local_probe()

    def _platform_theme(self, scheme):
        system_scheme_changed(self.preferences.get("theme"), scheme)

    def change_preference(self, key, value):
        self.preferences.set(key, value)
        if key == "theme":
            apply_theme(value)
        if key == "quality":
            for view in self.findChildren(StructureView):
                view.set_graphics_quality(value)

    def _toggle_sidebar(self):
        if self.width() < 900:
            self._compact_panel = "scene" if self._compact_panel == "files" else "files"
        else:
            self._sidebar_requested = not self.sidebar.isVisible()
        self._update_panels()

    def _toggle_inspector(self):
        if self.width() < 900:
            self._compact_panel = "scene" if self._compact_panel == "inspector" else "inspector"
        else:
            self._inspector_requested = not self.tabs.isVisible()
        self._update_panels()

    def _update_panels(self):
        if not hasattr(self, "tabs") or not hasattr(self, "center"):
            return
        w, h = self.width(), self.height()
        compact = w < 900
        if not compact and self._narrow is not None and (w < 1160) != self._narrow:
            self._sidebar_requested = w >= 1160
        if self._narrow is None:
            self._sidebar_requested = w >= 1160
        self._narrow = w < 1160
        self.sidebar.setVisible(self._compact_panel == "files" if compact else self._sidebar_requested)
        self.center.setVisible(not compact or self._compact_panel == "scene")
        self.tabs.setVisible(self._compact_panel == "inspector" if compact else self._inspector_requested)
        self.tabs.setMaximumWidth(16777215 if compact else 560)
        self.sidebar.setMaximumWidth(16777215 if compact else 290)
        self.metrics_widget.setVisible(h >= 570)
        self.scene_note.setVisible(h >= 470)
        if hasattr(self, "time_label"):
            self.time_label.setVisible(w >= 850)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._update_panels()

    def _original_cif(self):
        with self.workspace.lock:
            entry = next((e for e in self.workspace.project.entries if self.selected_entry and
                          e.id == self.selected_entry["id"]), None)
            if entry is None:
                return None
            if entry.preparation:
                raw = entry.preparation["source"]
                return raw["filename"], base64.b64decode(raw["cif_base64"], validate=True)
            return entry.filename, entry.data

    def _toggle_source_details(self, checked):
        self.source_details.setVisible(checked)
        self.original_button.setVisible(checked)
        if checked:
            self._fill_source_details()

    def _fill_source_details(self):
        entry = self.selected_entry
        if not entry:
            self.source_details.clear()
            return
        details = [entry["filename"], f"SHA256 {entry['sha256']}"]
        if entry.get("preparation"):
            details.append(json.dumps(entry["preparation"], indent=2, ensure_ascii=False))
        if self.details_button.isChecked():
            original = self._original_cif()
            if original:
                name, content = original
                try:
                    cif = content.decode("utf-8-sig")
                except UnicodeDecodeError:
                    cif = content.decode("latin-1")
                details.extend(["", name, cif])
        self.source_details.setPlainText("\n".join(details))

    def save_original_cif(self, checked=False, *, path=None):
        original = self._original_cif()
        if original is None:
            return False
        filename, content = original
        if path is None:
            path, _ = QFileDialog.getSaveFileName(self, self.text("원본 CIF 저장", "Save original CIF"),
                                                  Path(filename).name, "CIF (*.cif)")
        if not path:
            return False
        try:
            atomic_write(Path(path), content)
        except OSError as error:
            self.show_error(error)
            return False
        return True

    def copy_hash(self):
        if self.selected_entry:
            QApplication.clipboard().setText(self.selected_entry["sha256"])

    @property
    def is_busy(self):
        return bool(self._jobs)

    @property
    def workspace_busy(self):
        return any(job.key in ("workspace_action", "refresh", "preparation")
                   for job, _, _ in self._jobs.values())

    def submit(self, function: Callable, on_success=None, *, key="operation", on_error=None):
        """Run a bounded job; replaced-key callbacks cannot overwrite a newer result."""
        if self._closing:
            return None
        if key not in ("workspace_action", "recovery"):
            for previous, _, _ in self._jobs.values():
                if previous.key == key and not previous.started.is_set():
                    previous.cancelled.set()
        self._job_counter += 1
        token = self._job_counter
        self._latest[key] = token
        job = _Job(token, key, function)
        self._jobs[token] = (job, on_success, on_error)
        job.signals.finished.connect(self._job_finished, Qt.ConnectionType.QueuedConnection)
        self._set_busy(True)
        pool = (self._workspace_pool if key in ("workspace_action", "refresh", "preparation")
                else self._io_pool if key == "recovery" else self._probe_pool if key == "device-probe" else self._pool)
        pool.start(job)
        return token

    def cancel_job(self, key):
        """Cancel result application, not execution on a local or remote device.

        Running numeric calls finish. Pending calls skip their computation.
        Workspace commits and durable recovery writes cannot be canceled here.
        """
        status = {"invalidated": 0, "running": 0, "pending": 0}
        if key in ("workspace_action", "recovery"):
            return status
        jobs = [job for job, _, _ in self._jobs.values() if job.key == key and not job.cancelled.is_set()]
        if not jobs:
            return status
        self._job_counter += 1
        self._latest[key] = self._job_counter
        for job in jobs:
            job.cancelled.set()
            status["invalidated"] += 1
            status["running" if job.started.is_set() else "pending"] += 1
        return status

    @Slot(object)
    def _job_finished(self, payload):
        token, key, success, value = payload
        pending = self._jobs.pop(token, None)
        self._set_busy(self.is_busy)
        if pending is None or self._closing or self._latest.get(key) != token:
            return
        _, callback, failure = pending
        if success:
            if key == "workspace_action":
                self.error_label.hide()
            if callback is not None:
                try:
                    callback(value)
                except Exception as error:
                    self.show_error(error)
        elif failure is not None:
            failure(value)
        else:
            self.show_error(value)

    def _set_busy(self, busy):
        self.progress.setVisible(busy)
        self.language_combo.setEnabled(not busy)
        mutation_busy = self.workspace_busy
        for widget in (self.file_list, self.open_button, self.project_open_button, self.save_button,
                       self.compare_button,
                       self.example_button, self.remove_button, self.apply_button, self.review_check,
                       self.prepare_button, self.measure_button, self.save_measure_button):
            widget.setEnabled(not mutation_busy)
        self.busyChanged.emit(busy)
        if not mutation_busy and self.selected_entry:
            valid = self.selected_entry["analysis"].get("report") is not None
            pair_supported = valid and self.selected_entry["analysis"]["report"]["atom_count"] >= 2
            self.measure_button.setEnabled(pair_supported)
            self.save_measure_button.setEnabled(pair_supported)
            self.png_button.setEnabled(valid)
            self.prepare_button.setEnabled(not self.selected_entry.get("preparation"))
            self.remove_button.setEnabled(len(self.snapshot.get("entries", [])) > 1)
        if not mutation_busy and self.dirty and self.recovery:
            self._backup_timer.start()

    def apply_action(self, action, callback=None):
        def completed(snapshot):
            self._apply_snapshot(snapshot)
            self.mark_dirty()
            if callback:
                callback(snapshot)
        return self.submit(lambda: self.workspace.apply(self.workspace.revision, action), completed,
                           key="workspace_action")

    def refresh(self):
        return self.submit(lambda: self.workspace.snapshot(include_workspace=True), self._apply_snapshot,
                           key="refresh")

    def _apply_snapshot(self, snapshot, *, restore=False):
        if snapshot.get("revision", -1) < self.workspace.revision:
            return
        self._remember_view()
        self.snapshot = snapshot
        self.language = snapshot.get("language", self.language)
        self._updating = True
        self.file_list.clear()
        selected_id = snapshot["project"]["selected_id"]
        for entry in snapshot["entries"]:
            report = entry["analysis"].get("report")
            status = (self.text("입력 확인 필요", "Unsupported input") if report is None else
                      self.text("검토 완료", "Reviewed") if entry["review_current"] else
                      self.text("검토 필요", "Needs review") if report["review_required"] else
                      self.text("기하 분석", "Geometry available"))
            item = QListWidgetItem(f"{entry['filename']}\n{status}")
            item.setSizeHint(QSize(0, self.file_list.fontMetrics().lineSpacing() * 2 + 24))
            item.setData(Qt.ItemDataRole.UserRole, entry["id"])
            item.setToolTip(entry["filename"] + "\nSHA256 " + entry["sha256"])
            self.file_list.addItem(item)
            if entry["id"] == selected_id:
                self.file_list.setCurrentItem(item)
        count = len(snapshot["entries"])
        self.file_count.setText(self.text(f"{count}개 구조", f"{count} structure" + ("s" if count != 1 else "")))
        self.selected_entry = next((entry for entry in snapshot["entries"] if entry["id"] == selected_id), None)
        self._updating = False
        self._filter_files(self.file_search.text())
        if self.examples.count() == 0:
            for example in snapshot["examples"]:
                self.examples.addItem(example[f"label_{self.language}"], example["name"])
        if self.selected_entry:
            example_index = self.examples.findData(self.selected_entry["filename"])
            if example_index >= 0:
                self.examples.setCurrentIndex(example_index)
        state = snapshot["project"].get("workspace_state", self.workspace.project.workspace_state)
        if restore:
            native = state.get("native_desktop", {}) if isinstance(state, dict) else {}
            if isinstance(native, dict):
                self._drafts = {}
                candidates = native.get("drafts", {})
                for entry in snapshot["entries"]:
                    draft = candidates.get(entry["id"]) if isinstance(candidates, dict) else None
                    if not isinstance(draft, dict) or draft.get("sha256") != entry["sha256"]:
                        continue
                    axis, cutoff, note = (draft.get(key) for key in ("normal_axis", "short_distance", "note"))
                    if (isinstance(axis, str) and axis in ("a", "b", "c")
                            and type(cutoff) in (int, float) and math.isfinite(cutoff) and 0.1 <= cutoff <= 3
                            and isinstance(note, str) and len(note) <= 10000):
                        self._drafts[entry["id"]] = draft
                views = native.get("views", {})
                self._view_states = {key: value for key, value in views.items() if isinstance(value, dict)} if isinstance(views, dict) else {}
            old_drafts = state.get("drafts", {})
            old_viewers = state.get("viewers", {})
            for entry in snapshot["entries"]:
                if entry["id"] not in self._drafts and isinstance(old_drafts, dict):
                    migrated = legacy_draft(old_drafts.get(entry["id"]), entry)
                    if migrated:
                        self._drafts[entry["id"]] = migrated
                key = self._view_key(entry)
                if key not in self._view_states and isinstance(old_viewers, dict):
                    migrated = legacy_camera_state(old_viewers.get(f"overview:{key}"))
                    if migrated:
                        self._view_states[key] = migrated
            comparison = state.get("native_comparison", {})
            self.comparison_state = deepcopy(comparison) if isinstance(comparison, dict) else {}
            if self.research_panel:
                self.research_panel.restore_state(state)
        self._show_entry()
        self.workspaceChanged.emit(snapshot)
        self._set_busy(self.is_busy)

    def _show_entry(self):
        entry = self.selected_entry
        self._updating = True
        if entry is None:
            self._structure_key = None
            self.view.set_structure(None)
            if self.research_panel is not None:
                self.research_panel.set_entry(None, self.language)
            self.structure_title.setText(self.text("구조 없음", "No structure"))
            self.structure_subtitle.clear()
            self.entry_status.clear()
            self.source_details.clear()
            self.hash_label.clear()
            self.report_text.clear()
            self.note_edit.clear()
            self.saved_measurements.clear()
            for number in self.metric_labels:
                number.setText("—")
            self._updating = False
            return
        report = entry["analysis"].get("report")
        self.structure_title.setText(report["formula"] if report else self.text("입력 구조 확인", "Review input structure"))
        self.structure_subtitle.setText(entry["filename"] + (f"  ·  {report['atom_count']} "
            + self.text("원자", "atoms") + self.text(f"  ·  {entry['normal_axis']}축 선택", f"  ·  {entry['normal_axis']}-normal") if report else ""))
        signature = (entry["id"], entry["sha256"], entry["normal_axis"], entry["short_distance"])
        if signature != self._structure_key:
            self.view.set_structure(report, {"filename": entry["filename"], "sha256": entry["sha256"]})
            self._structure_key = signature
            self.view.restore_view_state(self._view_states.get(self._view_key(entry), {}))
            for key, checkbox in self.view_toggles.items():
                checkbox.setChecked(self.view.view_state()[key])
        draft = self._drafts.get(entry["id"], {})
        if not isinstance(draft, dict) or draft.get("sha256") != entry["sha256"]:
            draft = {}
        self.axis_combo.setCurrentText(draft.get("normal_axis", entry["normal_axis"]))
        self.cutoff_spin.setValue(draft.get("short_distance", entry["short_distance"]))
        self.note_edit.setPlainText(str(draft.get("note", entry["note"]))[:10000])
        self.review_check.setChecked(entry["review_current"])
        self.prepare_button.setEnabled(not entry.get("preparation") and not self.workspace_busy)
        digest = entry["sha256"]
        self.hash_label.setText(f"SHA256  {digest[:12]}…{digest[-8:]}")
        self.hash_label.setToolTip(digest)
        self._fill_source_details()
        if report is None:
            message = entry["analysis"].get("error_ko" if self.language == "ko" else "error")
            severity = "error"
            label = self.text("지원하지 않는 구조", "Unsupported geometry")
            if message:
                label += " · " + str(message)
        elif report.get("review_required") and not entry["review_current"]:
            severity = "warning"
            label = self.text("검토 필요", "Needs review")
            warnings = localized_report(report, self.language)["issues"]
            if warnings:
                label += " · " + warnings[0]["message"]
        else:
            severity = "ok"
            label = self.text("검토 완료", "Reviewed") if entry["review_current"] else self.text("기하 검사 정상", "Geometry checked")
        self.entry_status.setText(label)
        self.entry_status.setProperty("severity", severity)
        self.entry_status.style().unpolish(self.entry_status)
        self.entry_status.style().polish(self.entry_status)
        self.saved_measurements.clear()
        for selection in entry["measurements"]:
            mode = self.text("최단 주기", "Minimum image") if selection["mode"] == "minimum_image" else self.text("지정 이미지", "Specified images")
            item = QListWidgetItem(f"#{selection['i'] + 1} ↔ #{selection['j'] + 1} · {mode}")
            item.setData(Qt.ItemDataRole.UserRole, selection)
            self.saved_measurements.addItem(item)
        count = report["atom_count"] if report else 1
        self.first_atom.setMaximum(count)
        self.second_atom.setMaximum(count)
        if count >= 2 and self.first_atom.value() == self.second_atom.value():
            self.first_atom.setValue(1)
            self.second_atom.setValue(2)
        self.measurement_label.setText(self.text("화면에서 원자 두 개를 선택할 수도 있습니다.",
                                                "You can also pick two atoms in the view."))
        for label, metric in zip(self.metric_labels, (
            "minimum_distance_angstrom", "nuclei_thickness_angstrom", "nuclei_gap_angstrom",
        )):
            label.setText(f"{report['metrics'][metric]:.3f} Å" if report else "—")
        self._render_report(entry)
        if self.research_panel:
            self.research_panel.set_entry(entry, self.language)
        self._updating = False
        self._update_draft_label()
        self.selectedEntryChanged.emit(entry)

    def _render_report(self, entry):
        report = entry["analysis"].get("report")
        if report is None:
            error = entry["analysis"].get("error_ko") if self.language == "ko" else entry["analysis"].get("error")
            self.report_text.setPlainText(self.text("입력 조건을 확인하세요.\n\n", "Review the input contract.\n\n")
                                          + str(error or "") + "\n\n" + self.text(
                "비 P1 질서 구조는 P1 구조 준비에서 지원 여부를 확인할 수 있습니다.",
                "Use Prepare P1 to preview supported ordered structures with symmetry."))
            return
        localized = localized_report(report, self.language)
        lines = [self.text("기하 분석 결과", "GEOMETRY REPORT"), ""]
        for issue in localized["issues"]:
            lines.append(f"{issue['severity'].upper()} · {issue['code']}")
            lines.append(issue["message"])
            lines.append("")
        lines.append(self.text("가정과 한계", "ASSUMPTIONS & LIMITS"))
        lines.extend("• " + value for value in localized["assumptions"])
        lines.extend("• " + value for value in localized["limitations"])
        self.report_text.setPlainText("\n".join(lines))

    def _select_item(self, current, previous):
        if self._updating or current is None:
            return
        entry_id = current.data(Qt.ItemDataRole.UserRole)
        if self.selected_entry and self.selected_entry["id"] == entry_id:
            return
        self._remember_view()
        self.apply_action({"type": "patch_workspace", "selected_id": entry_id})

    def select_entry(self, entry_id):
        for index in range(self.file_list.count()):
            item = self.file_list.item(index)
            if item.data(Qt.ItemDataRole.UserRole) == entry_id:
                self.file_list.setCurrentItem(item)
                return

    def _filter_files(self, text):
        for index in range(self.file_list.count()):
            item = self.file_list.item(index)
            item.setHidden(text.casefold() not in item.text().casefold())

    def _view_key(self, entry):
        return f"{entry['id']}:{entry['sha256']}"

    def _remember_view(self):
        if self.selected_entry and self.view.report is not None:
            self._view_states[self._view_key(self.selected_entry)] = self.view.view_state()

    def _view_changed(self):
        if not self._updating:
            self._remember_view()
            self.mark_dirty()

    def _toggle_view(self, attribute, checked):
        setattr(self.view, attribute, checked)
        self.view.update()
        self._view_changed()

    def _draft_changed(self):
        if self._updating or not self.selected_entry:
            return
        entry = self.selected_entry
        self._drafts[entry["id"]] = {
            "sha256": entry["sha256"], "normal_axis": self.axis_combo.currentText(),
            "short_distance": self.cutoff_spin.value(), "note": self.note_edit.toPlainText()[:10000],
        }
        self._update_draft_label()
        self.mark_dirty()

    def _has_draft(self):
        entry = self.selected_entry
        return bool(entry and (
            self.axis_combo.currentText() != entry["normal_axis"]
            or self.cutoff_spin.value() != entry["short_distance"]
            or self.note_edit.toPlainText() != entry["note"]
        ))

    def _update_draft_label(self):
        self.draft_label.setText(self.text("적용하지 않은 변경 사항", "Unapplied changes") if self._has_draft()
                                 else self.text("현재 분석에 적용된 조건", "Settings used in this analysis"))

    def apply_settings(self, checked=False, callback=None):
        if self.selected_entry is None:
            return
        entry_id = self.selected_entry["id"]
        action = {"type": "patch_entry", "id": entry_id,
                  "normal_axis": self.axis_combo.currentText(), "short_distance": self.cutoff_spin.value(),
                  "note": self.note_edit.toPlainText()[:10000]}

        def applied(snapshot):
            current = self._drafts.get(entry_id)
            if isinstance(current, dict) and all(current.get(key) == action[key] for key in
                                                 ("normal_axis", "short_distance", "note")):
                self._drafts.pop(entry_id, None)
            self._update_draft_label()
            if callback:
                callback(snapshot)
        self.apply_action(action, applied)

    def _set_reviewed(self, checked):
        if self._updating or self.selected_entry is None:
            return
        entry_id = self.selected_entry["id"]
        action = {"type": "set_reviewed", "id": entry_id, "value": checked}
        if self._has_draft():
            self.apply_settings(callback=lambda _: self.apply_action(action))
        else:
            self.apply_action(action)

    def choose_cifs(self):
        paths, _ = QFileDialog.getOpenFileNames(self, self.text("CIF 열기", "Open CIF files"), "", "CIF (*.cif);;All files (*)")
        if paths:
            self.open_cifs(paths)

    def open_cifs(self, paths, *, mode="append"):
        paths = [Path(path) for path in paths]
        if not paths:
            return

        def import_files():
            files = []
            for path in paths:
                if path.stat().st_size > MAX_FILE_BYTES:
                    raise ValueError(self.text("CIF 파일은 2 MiB 이하여야 합니다.", "Each CIF must be at most 2 MiB."))
                files.append({"filename": path.name, "data_base64": base64.b64encode(path.read_bytes()).decode()})
            snapshot = self.workspace.apply(self.workspace.revision, {"type": "import_cifs", "files": files, "mode": mode})
            first_new = self.workspace.project.entries[-len(files)].id
            if snapshot["project"]["selected_id"] != first_new:
                snapshot = self.workspace.apply(self.workspace.revision,
                                                {"type": "patch_workspace", "selected_id": first_new})
            return snapshot

        def imported(snapshot):
            if mode == "replace":
                self.project_path = None
                self._structure_key = None
            self._apply_snapshot(snapshot, restore=mode == "replace")
            self.mark_dirty()
        return self.submit(import_files, imported, key="workspace_action")

    def remove_selected(self):
        if self.selected_entry and len(self.snapshot["entries"]) > 1:
            self.apply_action({"type": "remove_entry", "id": self.selected_entry["id"]})

    def _load_selected_example(self):
        self.load_example(self.examples.currentData())

    def load_example(self, name, *, confirm=True):
        if confirm and not self._confirm_unsaved():
            return
        def loaded(snapshot):
            self.project_path = None
            self._structure_key = None
            self._apply_snapshot(snapshot, restore=True)
            self.mark_dirty()
        self.submit(lambda: self.workspace.apply(self.workspace.revision, {"type": "load_example", "name": name}),
                    loaded, key="workspace_action")

    def choose_project(self):
        if not self._confirm_unsaved():
            return
        path, _ = QFileDialog.getOpenFileName(self, self.text("작업 열기", "Open project"), "",
                                             "CalcLens (*.calclens.zip *.calclens.json *.zip *.json)")
        if path:
            self.open_project(path, confirm=False)

    def open_project(self, path, *, confirm=True):
        if confirm and not self._confirm_unsaved():
            return
        path = Path(path)

        def read_project():
            if path.stat().st_size > MAX_ARCHIVE_BYTES:
                raise ValueError("Project archive exceeds the supported size limit.")
            return self._validated_import(path.read_bytes())

        def opened(snapshot):
            self.project_path = path
            self._drafts.clear()
            self._view_states.clear()
            self._structure_key = None
            self._apply_snapshot(snapshot, restore=True)
            self.dirty = False
            self._update_title()
        return self.submit(read_project, opened, key="workspace_action")

    def _validated_import(self, data):
        """Validate original scientific sources before replacing the live project."""
        revision = self.workspace.revision
        preview = self.workspace.import_project(revision, data, preview=True)
        self._validate_sources(preview)
        return self.workspace.import_project(revision, data)

    def _validate_sources(self, preview):
        # Validation is a property of a document, even before its research tab opens.
        if self.research_panel is not None:
            validator = self.research_panel.validate_state
        else:
            from .desktop_research import ResearchPanel
            validator = ResearchPanel.validate_state
        validator(preview["project"]["workspace_state"], preview["entries"])

    def portable_state(self):
        self._remember_view()
        state = deepcopy(self.workspace.project.workspace_state)
        ids = {entry["id"]: entry["sha256"] for entry in self.snapshot.get("entries", [])}
        previous_native = state.get("native_desktop", {})
        state["native_desktop"] = {
            **(previous_native if isinstance(previous_native, dict) else {}),
            "schema_version": 1,
            "views": {key: value for key, value in self._view_states.items()
                      if any(key == f"{entry_id}:{digest}" for entry_id, digest in ids.items())},
            "drafts": {key: value for key, value in self._drafts.items()
                       if key in ids and isinstance(value, dict) and value.get("sha256") == ids[key]},
        }
        if self.comparison_state:
            state["native_comparison"] = deepcopy(self.comparison_state)
        if self.research_panel:
            state = self.research_panel.portable_state(state)
        return state

    def create_comparison_dialog(self):
        from .desktop_compare import ComparisonDialog
        self._ensure_research()
        dialog = ComparisonDialog(self)
        dialog.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose, True)
        dialog.changed.connect(self._comparison_changed)
        def removed():
            if self._comparison_dialog is dialog:
                self._comparison_dialog = None
        dialog.destroyed.connect(removed)
        return dialog

    def compare_structures(self):
        if self._comparison_dialog is not None and self._comparison_dialog.isVisible():
            self._comparison_dialog.raise_()
            self._comparison_dialog.activateWindow()
            return self._comparison_dialog
        self._comparison_dialog = self.create_comparison_dialog()
        self._comparison_dialog.show()
        return self._comparison_dialog

    def _comparison_changed(self, state):
        self.comparison_state = deepcopy(state)
        self.mark_dirty()

    def _portable_project(self):
        state = self.portable_state()
        with self.workspace.lock:
            return replace(self.workspace.project, workspace_state=state,
                           calclens_version=__version__, ase_version=ase.__version__,
                           analysis_revision=ANALYSIS_REVISION)

    def save_project(self, checked=False, *, path=None, save_as=False):
        # A positional path is convenient for desktop integrations and tests.
        if isinstance(checked, (str, Path)) and path is None:
            path = checked
        if self.workspace_busy:
            self.show_error(self.text("작업이 끝난 뒤 저장할 수 있습니다.", "Wait for the current operation before saving."))
            return False
        target = Path(path) if path else self.project_path
        if target is None or save_as:
            filename, _ = QFileDialog.getSaveFileName(self, self.text("작업 저장", "Save project"),
                                                      str(target or "Untitled.calclens.zip"), "CalcLens (*.calclens.zip)")
            if not filename:
                return False
            target = Path(filename)
            if not str(target).lower().endswith(".zip"):
                target = target.with_name(target.name + ".calclens.zip")
        try:
            project = self._portable_project()
            data = dumps_project_archive(project)
            # Exercise the normal reopen checks on the exact bytes before replacing a prior file.
            preview = self.workspace.import_project(self.workspace.revision, data, preview=True)
            self._validate_sources(preview)
            atomic_write(target, data)
        except Exception as error:
            self.show_error(error)
            return False
        # Commit the save identity only after the replacement succeeded.
        with self.workspace.lock:
            self.workspace.project = project
        self.project_path = target
        self.dirty = False
        self._last_saved = datetime.now().astimezone()
        self._backup_timer.stop()
        if self.recovery:
            try:
                self.recovery.discard()
            except (OSError, ValueError) as error:
                self.show_error(error)
        self._update_title()
        self._refresh_status()
        return True

    def mark_dirty(self, *args):
        if self._updating or self._closing:
            return
        self.dirty = True
        self._change_counter += 1
        self._update_title()
        self._refresh_status()
        if self.recovery:
            self._backup_timer.start()

    def _save_recovery(self):
        if not self.dirty or not self.recovery or self._closing:
            return
        if self.workspace_busy or any(job.key == "recovery" for job, _, _ in self._jobs.values()):
            self._backup_timer.start()
            return
        try:
            project = self._portable_project()
        except Exception as error:
            self.show_error(error)
            return
        change_counter = self._change_counter

        def save():
            return self.recovery.save(dumps_project_archive(project))

        def saved(info):
            self._last_recovery = getattr(info, "modified", datetime.now().astimezone())
            self._last_recovery = self._last_recovery.astimezone()
            self._refresh_status()
            if self._change_counter == change_counter:
                self._backup_timer.stop()
            else:
                self._backup_timer.start()
        self.submit(save, saved, key="recovery")

    def _offer_recovery(self):
        if not self.recovery:
            return
        try:
            candidates = self.recovery.candidates()
        except (OSError, ValueError) as error:
            self.show_error(error)
            return
        if candidates:
            self._recovery_candidate = candidates[0]
            modified = getattr(candidates[0], "modified", None)
            timestamp = modified.astimezone().strftime("%Y-%m-%d %H:%M") if hasattr(modified, "strftime") else ""
            self.recovery_label.setText(self.text(
                f"저장하지 않은 작업 복구본이 있습니다. {timestamp}",
                f"An unsaved workspace can be restored. {timestamp}"))
            self.recovery_frame.show()

    def restore_recovery(self):
        if not self.recovery or self._recovery_candidate is None:
            return
        if not self._confirm_unsaved():
            return
        candidate = self._recovery_candidate

        def restore():
            return self._validated_import(self.recovery.load(candidate))

        def restored(snapshot):
            self.project_path = None
            self._structure_key = None
            self._apply_snapshot(snapshot, restore=True)
            self.recovery_frame.hide()
            self.mark_dirty()
        self.submit(restore, restored, key="workspace_action")

    def preview_preparation(self):
        if self.selected_entry is None:
            return
        entry = dict(self.selected_entry)
        expected = self.workspace.revision

        def preview():
            result = self.workspace.preview_p1({"expected_revision": expected, "entry_id": entry["id"]})
            return result, analyze_cif(result["prepared_cif"], normal_axis=entry["normal_axis"])

        def show(value):
            result, report = value
            if not self.selected_entry or self.selected_entry["id"] != entry["id"] or self.workspace.revision != expected:
                return
            dialog = QDialog(self)
            dialog.setWindowTitle(self.text("P1 구조 준비 · 미리 보기", "Prepare P1 · preview"))
            dialog.resize(850, 710)
            layout = QVBoxLayout(dialog)
            summary = QLabel(self.text(
                f"원본 {result['source_site_count']}개 자리 → P1 {result['prepared_site_count']}개 자리",
                f"{result['source_site_count']} original sites → {result['prepared_site_count']} explicit P1 sites"))
            summary.setObjectName("heading")
            layout.addWidget(summary)
            preview_view = StructureView(language=self.language)
            preview_view.set_structure(report, {"filename": entry["filename"] + " · P1 preview", "sha256": result["prepared_sha256"]})
            layout.addWidget(preview_view, 1)
            warnings_ko = {
                "The original cell is retained. This is symmetry expansion, not slab construction or relaxation.":
                    "원본 셀을 유지하며 대칭만 전개합니다. 슬래브 생성이나 구조 최적화는 수행하지 않습니다.",
                "Equivalent symmetry images are identified within at most 0.001 angstrom; deposited representative coordinates are retained.":
                    "최대 0.001 Å 범위에서 같은 대칭 위치를 판별하며, 원본의 대표 좌표를 유지합니다.",
                "Occupancy was omitted; the coreCIF default 1.0 is made explicit for every resulting site.":
                    "점유율 항목이 없어 coreCIF 기본값 1.0을 전개한 모든 자리에 명시합니다.",
                "Symmetry operations are generated from the explicit ASE standard-setting space group.":
                    "명시된 공간군의 ASE 표준 설정에서 대칭 연산을 생성합니다.",
            }
            warning = QLabel("\n".join(warnings_ko.get(value, value) if self.language == "ko" else value
                                       for value in result["warnings"]))
            warning.setWordWrap(True)
            layout.addWidget(warning)
            buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Apply | QDialogButtonBox.StandardButton.Cancel)
            buttons.button(QDialogButtonBox.StandardButton.Apply).setText(self.text("준비된 P1 적용", "Apply prepared P1"))
            buttons.button(QDialogButtonBox.StandardButton.Cancel).setText(self.text("취소", "Cancel"))
            buttons.button(QDialogButtonBox.StandardButton.Apply).clicked.connect(dialog.accept)
            buttons.rejected.connect(dialog.reject)
            layout.addWidget(buttons)
            if dialog.exec() == QDialog.DialogCode.Accepted:
                self.apply_action({"type": "prepare_p1", "id": entry["id"], "source_sha256": entry["sha256"]})
        return self.submit(preview, show, key="preparation")

    def _atom_picked(self, index):
        if not self.selected_entry:
            return
        selection = list(self.view.selected_atoms)
        selection = [] if len(selection) >= 2 else selection
        if index not in selection:
            selection.append(index)
        self.view.set_selection(selection)
        self._clear_measurement()
        self._updating = True
        if selection:
            self.first_atom.setValue(selection[0] + 1)
        if len(selection) == 2:
            self.second_atom.setValue(selection[1] + 1)
        self._updating = False
        if len(selection) == 2:
            self.measure_pair()

    def _pair_changed(self):
        if not self._updating and self.selected_entry:
            self.view.set_selection([self.first_atom.value() - 1, self.second_atom.value() - 1])
            self._clear_measurement()

    def _clear_measurement(self):
        self.view.set_contact(None)
        self.measurement_label.setText(self.text("새 선택의 거리를 계산하세요.", "Measure the distance for this selection."))

    def _measurement_mode_changed(self):
        self.shift_widget.setVisible(self.measurement_mode.currentData() == "displayed")
        if not self._updating:
            self._clear_measurement()

    def _pair_selection(self):
        shifts = [[spin.value() for spin in row] for row in self.shift_spins]
        if self.measurement_mode.currentData() == "minimum_image":
            shifts = [[0, 0, 0], [0, 0, 0]]
        return {"i": self.first_atom.value() - 1, "j": self.second_atom.value() - 1,
                "first_shift": shifts[0], "second_shift": shifts[1],
                "mode": self.measurement_mode.currentData()}

    def measure_pair(self):
        if not self.selected_entry:
            return
        entry_id, revision = self.selected_entry["id"], self.workspace.revision
        selection = self._pair_selection()
        body = {"expected_revision": revision, "entry_id": entry_id,
                **{key: value for key, value in selection.items() if key != "mode"}}

        def measured(result):
            if (not self.selected_entry or self.selected_entry["id"] != entry_id
                    or self.workspace.revision != revision or self._pair_selection() != selection):
                return
            displayed, minimum = result["displayed"], result["minimum_image"]
            self.measurement_label.setText(self.text(
                f"최단 주기 거리 {minimum['distance_angstrom']:.6f} Å\n표시 이미지 거리 {displayed['distance_angstrom']:.6f} Å",
                f"Minimum periodic {minimum['distance_angstrom']:.6f} Å\nSpecified images {displayed['distance_angstrom']:.6f} Å"))
            self.view.set_selection([result["i"], result["j"]])
            self.view.set_contact(result[selection["mode"]])
        return self.submit(lambda: self.workspace.measure(body), measured, key="measurement")

    def save_measurement(self):
        if self.selected_entry:
            self.apply_action({"type": "save_measurement", "id": self.selected_entry["id"],
                               "selection": self._pair_selection()})

    def _restore_measurement(self, item):
        selection = item.data(Qt.ItemDataRole.UserRole)
        self.first_atom.setValue(selection["i"] + 1)
        self.second_atom.setValue(selection["j"] + 1)
        self.measurement_mode.setCurrentIndex(0 if selection["mode"] == "minimum_image" else 1)
        for row, values in zip(self.shift_spins, (selection["first_shift"], selection["second_shift"])):
            for spin, value in zip(row, values):
                spin.setValue(value)
        self.measure_pair()

    def export_report(self, kind="csv", *, path=None):
        if not self.selected_entry or self.selected_entry["analysis"].get("report") is None:
            self.show_error(self.text("지원되는 구조의 분석 결과가 필요합니다.", "A supported structure report is required."))
            return False
        entry = self.selected_entry
        if path is None:
            filename, _ = QFileDialog.getSaveFileName(self, self.text("분석 결과 저장", "Export report"),
                                                     Path(entry["filename"]).stem + f".report.{kind}", f"{kind.upper()} (*.{kind})")
            if not filename:
                return False
            path = filename
        report = entry["analysis"]["report"]
        data = (report_csv(report, self.language).encode("utf-8-sig") if kind == "csv" else
                json.dumps(localized_report(report, self.language), ensure_ascii=False, indent=2).encode())
        try:
            atomic_write(path, data)
            self.status_label.setText(self.text("분석 결과를 저장했습니다.", "Report exported."))
            return True
        except OSError as error:
            self.show_error(error)
            return False

    def export_png(self, checked=False, *, path=None):
        if self.view.report is None:
            return False
        if path is None:
            filename, _ = QFileDialog.getSaveFileName(self, self.text("구조 이미지 저장", "Export structure image"),
                                                     Path(self.selected_entry["filename"]).stem + ".png", "PNG (*.png)")
            if not filename:
                return False
            path = filename
        try:
            self.view.export_png(path, width=int(self.preferences.get("export_width")),
                                 background=self.preferences.get("export_background"))
            self.status_label.setText(self.text("출처가 포함된 PNG를 저장했습니다.", "PNG exported with source annotations."))
            return True
        except (OSError, ValueError) as error:
            self.show_error(error)
            return False

    def export_publication(self, checked=False, *, view=None, path=None, width_mm=85, dpi=300,
                           transparent=False, scale_bar=True):
        from .publication import FigureDialog, export_figure

        view = self.view if view is None else view
        if not view.report:
            self.show_error(self.text("먼저 지원되는 구조를 여세요.", "Open a supported structure first."))
            return False
        if path is None:
            dialog = FigureDialog(self)
            if dialog.exec() != QDialog.DialogCode.Accepted:
                return False
            fmt = dialog.format_choice.currentText()
            source = view.metadata.get("source_filename") or view.metadata.get("filename") or "CalcLens"
            path, _ = QFileDialog.getSaveFileName(self, dialog.windowTitle(),
                Path(source).stem + ".figure." + fmt.lower(), f"{fmt} (*.{fmt.lower()})")
            if not path:
                return False
            if not Path(path).suffix:
                path += "." + fmt.lower()
            width_mm, dpi = dialog.width_choice.currentData(), dialog.dpi_choice.currentData()
            transparent = fmt == "PNG" and dialog.transparent.isChecked()
            scale_bar = dialog.scale_bar.isChecked()
        try:
            export_figure(view, path, width_mm=width_mm, dpi=dpi, transparent=transparent, scale_bar=scale_bar)
        except (OSError, ValueError, MemoryError) as error:
            self.show_error(error)
            return False
        self.status_label.setText(self.text(f"논문용 그림을 저장했습니다 ({width_mm} mm, {dpi} dpi).",
                                            f"Figure saved ({width_mm} mm, {dpi} dpi)."))
        return True

    def _change_language(self):
        if self._updating or self.language_combo.currentData() == self.language:
            return
        new_language = self.language_combo.currentData()
        if self.is_busy:
            with QSignalBlocker(self.language_combo):
                self.language_combo.setCurrentIndex(self.language_combo.findData(self.language))
            return
        tab = self.tabs.currentIndex()
        panel = self.research_panel
        mode = panel.mode.currentIndex() if panel else 0
        device_session = panel.devices.session_state() if panel else None
        live_results = panel.transient_results() if panel else None
        research_scroll = panel.stack.currentWidget().verticalScrollBar().value() if panel else 0
        filters = self.file_search.text()
        inspector_scroll = self.tabs.widget(0).verticalScrollBar().value()
        details_open = self.source_details.isVisible()
        comparison_open = self._comparison_dialog and self._comparison_dialog.isVisible()
        if comparison_open:
            self._comparison_dialog.close()
            self._comparison_dialog = None
        self._remember_view()
        state = self.portable_state()
        factory = self._research_factory
        self.language = new_language
        set_language(new_language)
        self.preferences.set("language", new_language)
        with self.workspace.lock:
            self.workspace.project = replace(self.workspace.project, workspace_state=state)
            self.workspace.language = new_language
        old = self.takeCentralWidget()
        old.hide()
        self.removeToolBar(self.toolbar)
        self.toolbar.deleteLater()
        # QMenuBar.clear removes actions, but menus shared with a toolbar or
        # parented to this window otherwise survive every language rebuild.
        for action in self.menuBar().actions():
            (action.menu() or action).deleteLater()
        self.menuBar().clear()
        for label in (self.status_label, self.time_label):
            self.statusBar().removeWidget(label)
            label.deleteLater()
        self._structure_key = None
        self._build_ui(factory)
        if panel:
            self._ensure_research()
        self._apply_snapshot(self.workspace.snapshot(include_workspace=True), restore=True)
        self.file_search.setText(filters)
        self.tabs.setCurrentIndex(tab)
        self.tabs.widget(0).verticalScrollBar().setValue(inspector_scroll)
        if details_open:
            self.details_button.setChecked(True)
            self._toggle_source_details(True)
        if panel:
            self.research_panel.devices.restore_session(device_session)
            self.research_panel.mode.setCurrentIndex(mode)
            self.research_panel.restore_transient_results(live_results)
            self.research_panel.stack.currentWidget().verticalScrollBar().setValue(research_scroll)
        old.deleteLater()
        if comparison_open:
            self.compare_structures()
        self._update_title()
        self._refresh_status()

    def _confirm_unsaved(self):
        if self.is_busy:
            self.show_error(self.text("현재 작업이 끝난 뒤 다시 시도하세요.", "Wait for the current operation to finish."))
            return False
        if not self.dirty:
            return True
        choice = QMessageBox.warning(self, self.text("저장하지 않은 작업", "Unsaved workspace"),
                                     self.text("변경 사항을 저장할까요?", "Save your changes?"),
                                     QMessageBox.StandardButton.Save | QMessageBox.StandardButton.Discard | QMessageBox.StandardButton.Cancel,
                                     QMessageBox.StandardButton.Save)
        if choice == QMessageBox.StandardButton.Cancel:
            return False
        if choice == QMessageBox.StandardButton.Save:
            return self.save_project()
        return True

    def closeEvent(self, event):
        if not self._confirm_unsaved():
            event.ignore()
            return
        self._closing = True
        if self._comparison_dialog is not None:
            self._comparison_dialog.close()
        self._backup_timer.stop()
        if self.recovery:
            try:
                # Explicit Discard or successful manual save clears this session.
                self.recovery.discard()
                self.recovery.close(keep=False)
            except (OSError, ValueError) as error:
                self.show_error(error)
        event.accept()

    def show_error(self, error):
        message = str(error)
        if isinstance(error, APIError):
            message = error.message
        message = localized_error_message(message, self.language)
        self.error_label.setText(self.text("오류 · ", "Error · ") + message)
        self.error_label.show()
        self.status_label.setText(message)
        self.errorOccurred.emit(message)

    def _update_title(self):
        title = self.project_path.name if self.project_path else self.text("새 작업", "Untitled workspace")
        self.setWindowTitle(f"{'● ' if self.dirty else ''}{title} — CalcLens")

    def _refresh_status(self):
        self.status_label.setText(self.text("저장하지 않은 변경 사항", "Unsaved changes") if self.dirty else
                                 self.text("준비됨", "Ready"))
        timestamps = []
        if self._last_saved:
            timestamps.append(self.text("저장 ", "Saved ") + self._last_saved.strftime("%Y-%m-%d %H:%M:%S"))
        if self._last_recovery:
            timestamps.append(self.text("복구본 ", "Recovery ") + self._last_recovery.strftime("%Y-%m-%d %H:%M:%S"))
        self.time_label.setText("  ·  ".join(timestamps))

    def keyPressEvent(self, event):
        if self._bench_input and event.key() == Qt.Key.Key_F24:
            from .startup import benchmark_requested, mark
            self._bench_input = False
            mark("first_input_response")
            event.accept()
            if benchmark_requested():
                QTimer.singleShot(0, QApplication.instance().quit)
            return
        super().keyPressEvent(event)

    def dragEnterEvent(self, event):
        if event.mimeData().hasUrls() and all(url.isLocalFile() for url in event.mimeData().urls()):
            event.acceptProposedAction()

    def dropEvent(self, event):
        paths = [Path(url.toLocalFile()) for url in event.mimeData().urls() if url.isLocalFile()]
        if self.is_busy or not paths:
            return
        if len(paths) == 1 and paths[0].suffix.lower() in (".zip", ".json"):
            self.open_project(paths[0])
        elif all(path.suffix.lower() == ".cif" for path in paths):
            self.open_cifs(paths)
        else:
            self.show_error(self.text("CIF 파일 여러 개 또는 작업 파일 하나를 선택하세요.",
                                      "Drop CIF files together, or one project archive."))
            return
        event.acceptProposedAction()


def main(language=None, root=None, argv=None) -> int:
    """Launch the actual native application and enter Qt's desktop event loop."""
    from .startup import log_failure, mark
    arguments = list(sys.argv if argv is None else argv)
    mark("qt_initialization_begin")
    app = QApplication.instance()
    owns_app = app is None
    if owns_app:
        app = QApplication(arguments)
    app.setApplicationName("CalcLens")
    app.setOrganizationName("CalcLens")
    app.setApplicationVersion(__version__)
    mark("qt_initialization_complete")
    window = MainWindow(language=language, root=root, defer_startup=True)
    window.status_label.setText(window.text("기본 구조를 불러오는 중…", "Loading the initial structure…"))
    window.show()
    app.processEvents()
    mark("first_window")
    # Retain the window when embedding in an existing Qt test/application.
    app._calclens_window = window
    app._calclens_file_filter = _FileOpenFilter(window, app)
    app.installEventFilter(app._calclens_file_filter)
    paths = [Path(value) for value in arguments[1:]
             if not value.startswith("-") and Path(value).suffix.lower() in (".cif", ".zip", ".json")]
    def initialized(snapshot):
        window._apply_snapshot(snapshot, restore=True)
        mark("default_analysis_complete")
        window._refresh_status()
        window._bench_input = True
        app.postEvent(window, QKeyEvent(QEvent.Type.KeyPress, Qt.Key.Key_F24, Qt.KeyboardModifier.NoModifier))
        if paths:
            if len(paths) == 1 and paths[0].suffix.lower() in (".zip", ".json"):
                window.open_project(paths[0], confirm=False)
            elif all(path.suffix.lower() == ".cif" for path in paths):
                window.open_cifs(paths, mode="replace")
            else:
                window.show_error(window.text("CIF 파일 여러 개 또는 작업 파일 하나를 선택하세요.",
                                              "Open CIF files together, or one project archive."))
    def failed(error):
        path = log_failure(error)
        window.show_error(f"{error}\n{path}")
    window.submit(window.workspace.load_initial_example, initialized, key="workspace_action", on_error=failed)
    return app.exec() if owns_app else 0


if __name__ == "__main__":
    raise SystemExit(main())
