"""Keep desktop preference tests independent of one another and of the user's settings."""
import pytest


@pytest.fixture(autouse=True)
def isolated_desktop_preferences(tmp_path, monkeypatch):
    monkeypatch.setenv("CALCLENS_SETTINGS_FILE", str(tmp_path / "desktop.ini"))
