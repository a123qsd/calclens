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
from PySide6.QtCore import QEvent, QObject, QRunnable, QThreadPool, QTimer, Qt, Signal, Slot
from PySide6.QtGui import QAction, QFont, QIcon, QKeySequence
from PySide6.QtWidgets import (
    QApplication, QCheckBox, QComboBox, QDialog, QDialogButtonBox, QDoubleSpinBox,
    QFileDialog, QFormLayout, QFrame, QHBoxLayout, QLabel, QLineEdit, QListWidget,
    QListWidgetItem, QMainWindow, QMessageBox, QPlainTextEdit, QProgressBar,
    QPushButton, QScrollArea, QSpinBox, QSplitter, QTabWidget,
    QTextBrowser, QToolBar, QVBoxLayout, QWidget,
)

from . import __version__
from .core import analyze_cif
from .desktop_compat import legacy_camera_state, legacy_draft
from .desktop_view import StructureView
from .project import ANALYSIS_REVISION, MAX_ARCHIVE_BYTES, MAX_FILE_BYTES, dumps_project_archive
from .reporting import localized_error_message, localized_report, report_csv
from .recovery import atomic_write
from .web_api import APIError, Workspace


THEME = """
QMainWindow, QDialog { background: #f1f5f7; color: #244050; }
QWidget { font-family: 'Arial', 'Apple SD Gothic Neo', 'Malgun Gothic'; font-size: 12px; }
QToolBar { background: #ffffff; border: 0; border-bottom: 1px solid #dce5ea; spacing: 8px; padding: 12px; }
QPushButton { border: 1px solid #d4dfe6; border-radius: 7px; padding: 8px 12px; background: #fff; color: #294959; }
QPushButton:hover { background: #ecf4f5; border-color: #95b6bb; }
QPushButton:pressed { background: #deebed; }
QPushButton:disabled { color: #a7b2b8; background: #eef2f4; border-color: #e2e8ed; }
QPushButton#primary { color: white; background: #286f74; border: 1px solid #286f74; font-weight: 600; }
QPushButton#primary:hover { background: #205d62; }
QPushButton#primary:disabled { background: #90acaf; border-color: #90acaf; }
QFrame#sidebar { background: #203b4a; border-radius: 10px; }
QFrame#sidebar QLabel { color: #d5e2e8; }
QFrame#sidebar QLineEdit { background: #2c4857; color: white; border-color: #486171; }
QListWidget#fileList { background: transparent; color: #d8e5ec; border: 0; outline: 0; padding: 4px; }
QListWidget#fileList::item { padding: 14px 8px; border-radius: 6px; margin-bottom: 5px; }
QListWidget#fileList::item:selected { background: #40636d; color: #ffffff; }
QListWidget#fileList::item:hover { background: #2d4b5c; }
QFrame#card { background: #ffffff; border: 1px solid #dce5ea; border-radius: 10px; }
QLabel#eyebrow { color: #5c8a8d; font-size: 10px; font-weight: 700; letter-spacing: 1px; }
QLabel#heading { color: #233e4e; font-size: 24px; font-weight: 600; }
QLabel#muted { color: #738894; font-size: 11px; }
QLabel#metricValue { color: #2d5966; font-size: 21px; font-weight: 600; }
QLabel#errorBanner { background: #fff0e9; color: #984a32; border-radius: 6px; padding: 10px; }
QLabel#recoveryBanner { background: #e4f0ec; color: #35685a; border-radius: 6px; padding: 9px; }
QTabWidget::pane { border: 1px solid #dce5ea; border-radius: 8px; background: white; }
QTabBar::tab { background: #e7eef1; color: #6b818e; padding: 10px 14px; border: 0; }
QTabBar::tab:selected { background: white; color: #286f74; font-weight: 600; }
QLineEdit, QPlainTextEdit, QComboBox, QSpinBox, QDoubleSpinBox { background: #fff; border: 1px solid #d8e2e8; border-radius: 6px; padding: 7px; color: #244050; }
QPlainTextEdit:focus, QLineEdit:focus { border: 1px solid #6ca0a3; }
QCheckBox { color: #486574; spacing: 7px; padding: 3px; }
QTableWidget { background: #ffffff; alternate-background-color: #f6f9fa; border: 1px solid #e1e9ed; gridline-color: #edf1f4; }
QHeaderView::section { background: #edf3f5; color: #476472; border: 0; padding: 7px; }
QTextBrowser { border: 0; background: #fff; padding: 5px; }
QStatusBar { color: #718591; background: #f8fafb; }
QProgressBar { max-height: 3px; border: 0; background: #dbe7e9; }
QProgressBar::chunk { background: #5d9998; }
QSplitter::handle { background: transparent; }
QWidget#inspectorPage { background: white; }
QScrollArea { border: 0; background: white; }
"""


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

    def __init__(self, language="ko", *, workspace=None, recovery=None,
                 research_factory=None, root=None, parent=None):
        super().__init__(parent)
        self.language = language if language in ("ko", "en") else "ko"
        self.root = Path(root) if root else Path(__file__).resolve().parents[2]
        for icon in (self.root / "CalcLens.ico", self.root / "packaging/desktop/CalcLens.ico"):
            if icon.is_file():
                self.setWindowIcon(QIcon(str(icon)))
                break
        self.workspace = workspace or Workspace(self.root, self.language)
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
        self.setMinimumSize(1080, 720)
        self.resize(1480, 950)
        self.setAcceptDrops(True)
        self.setStyleSheet(THEME)
        self._build_ui(research_factory)
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
        brand.setFont(QFont("Arial", 21, QFont.Weight.DemiBold))
        brand.setStyleSheet("color:#264553; font-size:23px; font-weight:600; padding:0 16px 0 3px;")
        self.toolbar.addWidget(brand)
        self.open_button = self._button("CIF 열기", "Open CIF", self.choose_cifs, primary=True)
        self.project_open_button = self._button("작업 열기", "Open project", self.choose_project)
        self.save_button = self._button("작업 저장", "Save project", self.save_project)
        self.compare_button = self._button("구조 비교", "Compare", self.compare_structures)
        for button in (self.open_button, self.project_open_button, self.save_button, self.compare_button):
            self.toolbar.addWidget(button)
        self.examples = QComboBox()
        self.examples.setObjectName("examplesCombo")
        self.examples.setMinimumWidth(210)
        self.toolbar.addSeparator()
        self.toolbar.addWidget(self.examples)
        self.example_button = self._button("예제 열기", "Load example", self._load_selected_example)
        self.toolbar.addWidget(self.example_button)
        spacer = QWidget()
        spacer.setSizePolicy(spacer.sizePolicy().horizontalPolicy().Expanding,
                             spacer.sizePolicy().verticalPolicy().Preferred)
        self.toolbar.addWidget(spacer)
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
        ):
            action = QAction(title, self)
            action.setShortcut(shortcut)
            action.triggered.connect(function)
            file_menu.addAction(action)
        quit_action = QAction(self.text("종료", "Quit"), self)
        quit_action.setShortcut(QKeySequence.StandardKey.Quit)
        quit_action.setMenuRole(QAction.MenuRole.QuitRole)
        quit_action.triggered.connect(self.close)
        file_menu.addAction(quit_action)
        compare_action = QAction(self.text("구조 비교…", "Compare structures…"), self)
        compare_action.setShortcut(f"{modifier}+Shift+C")
        compare_action.triggered.connect(self.compare_structures)
        self.menuBar().addAction(compare_action)
        self.body = QWidget()
        outer = QVBoxLayout(self.body)
        outer.setContentsMargins(18, 14, 18, 10)
        outer.setSpacing(10)
        self.error_label = QLabel()
        self.error_label.setObjectName("errorBanner")
        self.error_label.setWordWrap(True)
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
        self.splitter.setHandleWidth(12)
        outer.addWidget(self.splitter, 1)
        self.setCentralWidget(self.body)
        self._build_sidebar()
        self._build_scene()
        self._build_inspector(research_factory)
        self.splitter.setSizes([220, 720, 390])
        self.status_label = QLabel()
        self.statusBar().addWidget(self.status_label, 1)
        self.time_label = QLabel()
        self.statusBar().addPermanentWidget(self.time_label)
        self._refresh_status()

    def _build_sidebar(self):
        self.sidebar = QFrame()
        self.sidebar.setObjectName("sidebar")
        self.sidebar.setMinimumWidth(190)
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
        hint = QLabel(self.text("CIF 파일을 이 창으로 끌어 놓을 수 있습니다.",
                                "Drop CIF files into this window to add them."))
        hint.setWordWrap(True)
        hint.setStyleSheet("color:#94aebc; font-size:11px; padding-top:12px;")
        layout.addWidget(hint)
        self.splitter.addWidget(self.sidebar)

    def _build_scene(self):
        center = QWidget()
        layout = QVBoxLayout(center)
        layout.setContentsMargins(2, 0, 2, 0)
        header = QHBoxLayout()
        heading = QVBoxLayout()
        eyebrow = QLabel(self.text("구조를 이해하는 작업 공간", "A CLOSER LOOK AT STRUCTURE"))
        eyebrow.setObjectName("eyebrow")
        heading.addWidget(eyebrow)
        self.structure_title = QLabel()
        self.structure_title.setObjectName("heading")
        self.structure_subtitle = QLabel()
        self.structure_subtitle.setObjectName("muted")
        heading.addWidget(self.structure_title)
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
        self.view_toggles = {}
        for key, ko, en, attribute in (
            ("cell", "셀", "Cell", "show_cell"), ("bonds", "연결선", "Guides", "show_bonds"),
            ("gap", "간격", "Gap", "show_gap"), ("labels", "원소", "Labels", "show_labels"),
        ):
            checkbox = QCheckBox(self.text(ko, en))
            checkbox.setChecked(getattr(self.view, attribute))
            checkbox.toggled.connect(lambda checked, attr=attribute: self._toggle_view(attr, checked))
            self.view_toggles[key] = checkbox
            tools.addWidget(checkbox)
        tools.addStretch()
        tools.addWidget(self._button("초기화", "Reset", self.view.reset_view))
        card_layout.addLayout(tools)
        layout.addWidget(card, 1)
        metrics = QHBoxLayout()
        self.metric_labels = []
        for ko, en in (("최소 주기 거리", "Minimum periodic distance"),
                       ("원자핵 두께", "Nuclei thickness"), ("원자핵 간격", "Nuclei gap")):
            metric = QFrame()
            metric.setObjectName("card")
            metric_layout = QVBoxLayout(metric)
            name = QLabel(self.text(ko, en))
            name.setObjectName("muted")
            number = QLabel("—")
            number.setObjectName("metricValue")
            metric_layout.addWidget(name)
            metric_layout.addWidget(number)
            self.metric_labels.append(number)
            metrics.addWidget(metric)
        layout.addLayout(metrics)
        footnote = QLabel(self.text(
            "입력 기하를 확인합니다. 안정성·화학 결합·계산 수렴을 판정하지 않습니다.",
            "Supplied geometry only. Stability, chemical bonds and convergence require separate evidence."))
        footnote.setObjectName("muted")
        footnote.setWordWrap(True)
        layout.addWidget(footnote)
        self.splitter.addWidget(center)

    def _build_inspector(self, research_factory):
        self.tabs = QTabWidget()
        self.tabs.setMinimumWidth(310)
        self.tabs.setMaximumWidth(600)
        settings = QWidget()
        settings.setObjectName("inspectorPage")
        layout = QVBoxLayout(settings)
        layout.setContentsMargins(15, 18, 15, 15)
        form = QFormLayout()
        form.setVerticalSpacing(12)
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
        divider.setStyleSheet("color:#e4eaee; margin:9px 0;")
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
            spin.valueChanged.connect(self._pair_changed)
        self.second_atom.setValue(2)
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
        layout.addStretch()
        layout.addWidget(self.hash_label)
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
        if research_factory is not False:
            if research_factory is None:
                try:
                    from .desktop_research import ResearchPanel
                    research_factory = ResearchPanel
                except ImportError:
                    research_factory = None
            if research_factory is not None:
                self.research_panel = research_factory(self)
                self.research_panel.changed.connect(self.mark_dirty)
                self.tabs.addTab(self.research_panel, self.text("연구 도구", "Research"))
        self.splitter.addWidget(self.tabs)
        self.axis_combo.currentIndexChanged.connect(self._draft_changed)
        self.cutoff_spin.valueChanged.connect(self._draft_changed)
        self.note_edit.textChanged.connect(self._draft_changed)

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
                else self._io_pool if key == "recovery" else self._pool)
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
            if key != "recovery":
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
            self.view.set_structure(None)
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
        self.hash_label.setText("SHA256\n" + entry["sha256"])
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
        if self.research_panel:
            self.research_panel.validate_state(preview["project"]["workspace_state"], preview["entries"])
        return self.workspace.import_project(revision, data)

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
        self._updating = True
        if selection:
            self.first_atom.setValue(selection[0] + 1)
        if len(selection) == 2:
            self.second_atom.setValue(selection[1] + 1)
        self._updating = False
        if len(selection) == 2:
            self.measure_pair()

    def _pair_changed(self):
        if not self._updating:
            self.view.set_selection([self.first_atom.value() - 1, self.second_atom.value() - 1])

    def _measurement_mode_changed(self):
        self.shift_widget.setVisible(self.measurement_mode.currentData() == "displayed")

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
            if not self.selected_entry or self.selected_entry["id"] != entry_id or self.workspace.revision != revision:
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
            self.view.export_png(path)
            self.status_label.setText(self.text("출처가 포함된 PNG를 저장했습니다.", "PNG exported with source annotations."))
            return True
        except (OSError, ValueError) as error:
            self.show_error(error)
            return False

    def _change_language(self):
        if self._updating or self.language_combo.currentData() == self.language:
            return
        new_language = self.language_combo.currentData()
        if self.is_busy:
            return
        if self._comparison_dialog is not None:
            self._comparison_dialog.close()
        # Rebuild native controls while retaining workspace, drafts and view state.
        self._remember_view()
        self.workspace.language = new_language
        self.language = new_language
        state = self.portable_state()
        self.workspace.project = replace(self.workspace.project, workspace_state=state)
        old = self.takeCentralWidget()
        self.removeToolBar(self.toolbar)
        self.toolbar.deleteLater()
        self.menuBar().clear()
        self.statusBar().removeWidget(self.status_label)
        self.statusBar().removeWidget(self.time_label)
        factory = type(self.research_panel) if self.research_panel else False
        self._structure_key = None
        self._build_ui(factory)
        self._apply_snapshot(self.workspace.snapshot(include_workspace=True), restore=True)
        old.deleteLater()
        self.mark_dirty()

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
        self.error_label.setText(message)
        self.error_label.show()
        self.status_label.setText(message)
        self.errorOccurred.emit(message)

    def _update_title(self):
        title = self.project_path.name if self.project_path else self.text("새 작업", "Untitled workspace")
        self.setWindowTitle(f"{'● ' if self.dirty else ''}{title} — CalcLens")

    def _refresh_status(self):
        self.status_label.setText(self.text("저장하지 않은 변경 사항", "Unsaved changes") if self.dirty else
                                 self.text("준비됨 · 파일은 이 컴퓨터에서 처리됩니다", "Ready · files stay on this computer"))
        timestamps = []
        if self._last_saved:
            timestamps.append(self.text("저장 ", "Saved ") + self._last_saved.strftime("%Y-%m-%d %H:%M:%S"))
        if self._last_recovery:
            timestamps.append(self.text("복구본 ", "Recovery ") + self._last_recovery.strftime("%Y-%m-%d %H:%M:%S"))
        self.time_label.setText("  ·  ".join(timestamps))

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


def main(language="ko", root=None, argv=None) -> int:
    """Launch the actual native application and enter Qt's desktop event loop."""
    arguments = list(sys.argv if argv is None else argv)
    app = QApplication.instance()
    owns_app = app is None
    if owns_app:
        app = QApplication(arguments)
    app.setApplicationName("CalcLens")
    app.setOrganizationName("CalcLens")
    app.setApplicationVersion(__version__)
    window = MainWindow(language=language, root=root)
    window.show()
    # Retain the window when embedding in an existing Qt test/application.
    app._calclens_window = window
    app._calclens_file_filter = _FileOpenFilter(window, app)
    app.installEventFilter(app._calclens_file_filter)
    paths = [Path(value) for value in arguments[1:]
             if not value.startswith("-") and Path(value).suffix.lower() in (".cif", ".zip", ".json")]
    if paths:
        if len(paths) == 1 and paths[0].suffix.lower() in (".zip", ".json"):
            QTimer.singleShot(0, lambda: window.open_project(paths[0], confirm=False))
        elif all(path.suffix.lower() == ".cif" for path in paths):
            QTimer.singleShot(0, lambda: window.open_cifs(paths, mode="replace"))
        else:
            QTimer.singleShot(0, lambda: window.show_error("Open CIF files together, or one project archive."))
    return app.exec() if owns_app else 0


if __name__ == "__main__":
    raise SystemExit(main())
