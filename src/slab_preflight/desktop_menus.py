"""Native menus shared by the toolbar and the keyboard-accessible menu bar."""
from PySide6.QtGui import QActionGroup
from PySide6.QtWidgets import QMenu


def _choices(menu, title, options, selected, changed, t):
    submenu = menu.addMenu(title)
    group = QActionGroup(submenu)
    for key, ko, en in options:
        action = submenu.addAction(t(ko, en))
        action.setCheckable(True)
        action.setData(key)
        action.setChecked(key == selected)
        action.triggered.connect(lambda checked, value=key: changed(value) if checked else None)
        group.addAction(action)
    return submenu


def settings_menu(window):
    t = window.text
    menu = QMenu(t("설정", "Settings"), window)
    menu.setObjectName("settingsMenu")
    menu.addAction(t("계산 장치와 원격 워커…", "Compute devices and workers…"), window.open_compute_settings)
    menu.addSeparator()
    def preference(key):
        return lambda value: window.change_preference(key, value)
    _choices(menu, t("테마", "Theme"), [
        ("system", "시스템", "System"), ("light", "라이트", "Light"), ("dark", "다크", "Dark"),
    ], window.preferences.get("theme"), preference("theme"), t)
    _choices(menu, t("화면 그래픽 품질", "Interactive graphics quality"), [
        ("auto", "자동", "Auto"), ("light", "가벼움", "Light"), ("balanced", "균형", "Balanced"),
        ("high", "고품질", "High"),
    ], window.preferences.get("quality"), preference("quality"), t)
    _choices(menu, t("PNG 너비", "PNG width"),
             [(str(n), f"{n} px", f"{n} px") for n in (800, 1600, 2400, 3200)],
             window.preferences.get("export_width"), preference("export_width"), t)
    _choices(menu, t("PNG 배경", "PNG background"), [
        ("white", "흰색", "White"), ("transparent", "투명", "Transparent"), ("dark", "어두움", "Dark"),
        ("gradient", "그라데이션", "Gradient"),
    ], window.preferences.get("export_background"), preference("export_background"), t)
    return menu


def display_menu(window):
    t = window.text
    menu = QMenu(window)
    rep = _choices(menu, t("원자 표현", "Representation"), [
        ("ball-stick", "공과 막대", "Ball and stick"), ("spacefill", "공간 채움", "Space filling"),
        ("stick", "막대", "Sticks"),
    ], "ball-stick", lambda key: window.view.set_representation(key), t)
    bg = _choices(menu, t("화면 배경", "View background"), [
        ("gradient", "그라데이션", "Gradient"), ("white", "흰색", "White"), ("dark", "어두움", "Dark"),
    ], "gradient", lambda key: window.view.set_background(key), t)
    def sync():
        for submenu, value in [(rep, window.view.representation), (bg, window.view.background)]:
            for action in submenu.actions():
                action.setChecked(action.data() == value)
    menu.aboutToShow.connect(sync)
    return menu
