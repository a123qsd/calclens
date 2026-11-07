"""Non-scientific preferences kept outside the portable project."""
from __future__ import annotations

import os
from PySide6.QtCore import QSettings


CHOICES = {
    "language": ("ko", "en"),
    "theme": ("system", "light", "dark"),
    "quality": ("auto", "light", "balanced", "high"),
    "local_device": ("auto", "cpu", "metal", "cuda"),
    "worker_device": ("auto", "cpu", "metal", "cuda"),
    "export_width": ("1600", "800", "2400", "3200"),
    "export_background": ("white", "transparent", "dark", "gradient"),
}


class DesktopPreferences:
    def __init__(self):
        path = os.environ.get("CALCLENS_SETTINGS_FILE")
        self.store = QSettings(path, QSettings.Format.IniFormat) if path else QSettings("CalcLens", "Desktop")

    def get(self, key):
        options = CHOICES[key]
        value = self.store.value(key, options[0])
        return value if value in options else options[0]

    def set(self, key, value):
        if value not in CHOICES[key]:
            raise ValueError(f"Unknown {key} preference: {value!r}")
        self.store.setValue(key, value)
        self.store.sync()
