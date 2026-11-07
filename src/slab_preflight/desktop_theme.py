"""Palette and widget styling for the native research workspace and its dialogs."""
from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor, QPalette
from PySide6.QtWidgets import QApplication


LIGHT = {
    "page": "#f2f5f6", "panel": "#ffffff", "raised": "#e7eff0", "ink": "#20333c",
    "muted": "#485e68", "edge": "#bdcccf", "accent": "#196663", "accent_ink": "#ffffff",
    "hover": "#dbeae9", "disabled_bg": "#edf1f2", "disabled_text": "#56666d",
    "warning": "#754b0a", "warning_bg": "#fff2cc", "error": "#893e2f", "error_bg": "#ffebe6",
    "ok": "#235f4a", "ok_bg": "#e3f2e9",
}
DARK = {
    "page": "#192329", "panel": "#222f36", "raised": "#303f47", "ink": "#eef4f5",
    "muted": "#b8c9cd", "edge": "#52646b", "accent": "#8bdacf", "accent_ink": "#102e2c",
    "hover": "#324e50", "disabled_bg": "#28353b", "disabled_text": "#abbcc0",
    "warning": "#ffe29a", "warning_bg": "#483c25", "error": "#ffc2ad", "error_bg": "#48332e",
    "ok": "#aee4c8", "ok_bg": "#264437",
}


def widget_palette(colors):
    roles = {
        "Window": "page", "WindowText": "ink", "Base": "panel", "AlternateBase": "raised",
        "Text": "ink", "Button": "panel", "ButtonText": "ink", "ToolTipBase": "ink",
        "ToolTipText": "panel", "PlaceholderText": "muted", "Highlight": "accent",
        "HighlightedText": "accent_ink", "Link": "accent", "BrightText": "ink",
        "LinkVisited": "accent", "Accent": "accent",
    }
    palette = QPalette()
    for group in (QPalette.ColorGroup.Active, QPalette.ColorGroup.Inactive, QPalette.ColorGroup.Disabled):
        for name, token in roles.items():
            if group == QPalette.ColorGroup.Disabled:
                if name in {"Text", "WindowText", "ButtonText", "PlaceholderText"}:
                    token = "disabled_text"
                elif name in {"Base", "Button"}:
                    token = "disabled_bg"
            palette.setColor(group, QPalette.ColorRole[name], QColor(colors[token]))
    return palette


def stylesheet(c):
    return """
QMainWindow, QDialog, QMenuBar { background: %(page)s; color: %(ink)s; }
QWidget { font-size: 12px; }
QToolBar { background: %(panel)s; border: 0; border-bottom: 1px solid %(edge)s; spacing: 5px; padding: 6px; }
QPushButton, QToolButton { background: %(panel)s; color: %(ink)s; border: 1px solid %(edge)s; border-radius: 5px; padding: 5px 8px; }
QPushButton:hover, QToolButton:hover { background: %(hover)s; }
QPushButton:pressed, QToolButton:pressed { background: %(raised)s; }
QPushButton#primary { background: %(accent)s; color: %(accent_ink)s; font-weight: 600; }
QPushButton:disabled, QToolButton:disabled, QComboBox:disabled, QLineEdit:disabled, QSpinBox:disabled, QDoubleSpinBox:disabled { color: %(disabled_text)s; background: %(disabled_bg)s; }
QPushButton#primary:disabled { color: %(disabled_text)s; background: %(disabled_bg)s; }
QFrame#sidebar { background: #203b4a; border-radius: 7px; }
QFrame#sidebar QLabel { color: #dae8ec; }
QFrame#sidebar QLineEdit { background: #2c4857; color: #ffffff; placeholder-text-color: #cedee3; border-color: #91a8ae; }
QListWidget#fileList { background: #203b4a; color: #e0eef0; border: 0; padding: 2px; }
QListWidget#fileList::item { padding: 10px 7px; border-radius: 4px; margin-bottom: 3px; }
QListWidget#fileList::item:hover { background: #2d4b5c; }
QListWidget#fileList::item:selected { background: #40636d; color: white; }
QFrame#card { background: %(panel)s; border: 1px solid %(edge)s; border-radius: 7px; }
QLabel#brand { color: %(ink)s; font-size: 20px; font-weight: 600; padding: 0 8px 0 2px; }
QLabel#eyebrow { color: %(accent)s; font-weight: 600; }
QLabel#heading { color: %(ink)s; font-size: 21px; font-weight: 600; }
QLabel#muted { color: %(muted)s; }
QLabel#metricValue { color: %(ink)s; font-size: 17px; font-weight: 600; }
QLabel#errorBanner, QLabel[severity="error"] { background: %(error_bg)s; color: %(error)s; padding: 6px; border-radius: 4px; }
QLabel[severity="warning"] { background: %(warning_bg)s; color: %(warning)s; padding: 6px; border-radius: 4px; }
QLabel#recoveryBanner, QLabel[severity="ok"] { background: %(ok_bg)s; color: %(ok)s; padding: 6px; border-radius: 4px; }
QTabWidget::pane { border: 1px solid %(edge)s; border-radius: 5px; background: %(panel)s; }
QTabBar::tab { background: %(raised)s; color: %(muted)s; padding: 7px 9px; }
QTabBar::tab:selected { background: %(panel)s; color: %(accent)s; font-weight: 600; }
QLineEdit, QPlainTextEdit, QTextBrowser, QComboBox, QSpinBox, QDoubleSpinBox, QTableWidget, QAbstractItemView {
    background: %(panel)s; color: %(ink)s; selection-background-color: %(accent)s; selection-color: %(accent_ink)s;
    border: 1px solid %(edge)s; border-radius: 4px; padding: 3px;
}
QTextBrowser { border: 0; padding: 5px; }
QCheckBox { color: %(ink)s; spacing: 5px; }
QCheckBox:disabled, QLabel:disabled { color: %(disabled_text)s; }
QTableWidget { alternate-background-color: %(raised)s; gridline-color: %(edge)s; }
QHeaderView::section { background: %(raised)s; color: %(ink)s; border: 0; padding: 4px; }
QMenu, QComboBox QAbstractItemView { background: %(panel)s; color: %(ink)s; border: 1px solid %(edge)s; }
QMenu::item:selected, QMenuBar::item:selected { background: %(accent)s; color: %(accent_ink)s; }
QToolTip { background: %(ink)s; color: %(panel)s; padding: 3px; border: 1px solid %(edge)s; }
QStatusBar { color: %(muted)s; background: %(page)s; }
QProgressBar { max-height: 3px; border: 0; background: %(raised)s; }
QProgressBar::chunk { background: %(accent)s; }
QWidget#inspectorPage, QScrollArea { border: 0; background: %(panel)s; }
QSplitter::handle { background: %(page)s; }
QLineEdit:focus, QPlainTextEdit:focus, QComboBox:focus, QSpinBox:focus, QDoubleSpinBox:focus,
QPushButton:focus, QToolButton:focus, QListWidget:focus { border: 2px solid %(accent)s; }
""" % c


def apply_theme(mode, *, system_dark=None):
    app = QApplication.instance()
    # Save the platform/user-supplied palette before installing our matched roles.
    current_base = app.palette().color(QPalette.ColorRole.Base)
    if current_base.name() != app.property("calcLensAppliedBase"):
        app.setProperty("calcLensSystemDark", current_base.lightnessF() < 0.5)
    if system_dark is not None:
        app.setProperty("calcLensSystemDark", system_dark)
    dark = mode == "dark" or (mode == "system" and bool(app.property("calcLensSystemDark")))
    colors = DARK if dark else LIGHT
    app.setProperty("calcLensAppliedBase", colors["panel"])
    app.setPalette(widget_palette(colors))
    app.setStyleSheet(stylesheet(colors))


def system_scheme_changed(mode, scheme):
    if scheme in (Qt.ColorScheme.Light, Qt.ColorScheme.Dark):
        apply_theme(mode, system_dark=scheme == Qt.ColorScheme.Dark)
