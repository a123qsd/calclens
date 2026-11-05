"""Verify launch defaults and immutable, reproducible release assets offline."""

import hashlib
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import sys
from types import SimpleNamespace
import zipfile

import pytest


ROOT = Path(__file__).resolve().parents[1]


def load_module(name, path):
    specification = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(specification)
    specification.loader.exec_module(module)
    return module


launcher = load_module("calclens_launcher", ROOT / "run_app.py")
release = load_module("calclens_release_builder", ROOT / "scripts" / "build_release.py")


def git(repo, *arguments):
    return subprocess.run(
        ["git", "-C", str(repo), *arguments], check=True,
        stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
    ).stdout.strip()


def commit(repo, message="test source"):
    git(repo, "add", ".")
    git(repo, "-c", "user.name=Fixture", "-c", "user.email=fixture@example.invalid",
        "-c", "commit.gpgsign=false", "commit", "-m", message)
    return git(repo, "rev-parse", "HEAD")


@pytest.fixture
def source_repo(tmp_path):
    repo = tmp_path / "source"
    repo.mkdir()
    git(repo, "init", "-q")
    contents = {
        ".gitignore": "dist/\n.venv/\n.env\nuploads/\n",
        "pyproject.toml": """[project]
name = "calclens"
version = "0.1.1"
[project.urls]
Repository = "https://github.com/example/calclens"
""",
        "requirements.lock": "# synthetic locked dependency fixture\n",
        "uv.lock": "# synthetic uv lock fixture\n",
        "LICENSE": "fixture license\n",
        "THIRD_PARTY_NOTICES.md": "fixture notices\n",
        "README.md": "bilingual landing\n",
        "README.en.md": "# English\n[Methods](docs/METHODS.md#limits)\n[License](LICENSE)\n",
        "README.ko.md": "# 한국어\n[방법](docs/METHODS.md#limits)\n[라이선스](LICENSE)\n",
        "streamlit_app.py": "# identical application\n",
        "run_app.py": "# identical launcher\n",
        "src/slab_preflight/core.py": "# identical scientific engine\n",
        "docs/METHODS.md": "# Methods\n## limits\n",
        "examples/graphene.cif": "data_fixture\n",
        "tests/test_example.py": "# source tests are distributed\n",
    }
    for name, content in contents.items():
        path = repo / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")
    commit(repo)
    return repo


def archive_files(path):
    with zipfile.ZipFile(path) as archive:
        return {name.split("/", 1)[1]: archive.read(name) for name in archive.namelist()}


@pytest.mark.parametrize("marker,explicit,expected", [(None, None, "ko"), ("en", None, "en"), ("ko", "en", "en"), ("en", "ko", "ko")])
def test_launcher_resolves_locale_and_keeps_parent_environment(tmp_path, monkeypatch, marker, explicit, expected):
    (tmp_path / "streamlit_app.py").write_text("# fixture")
    if marker:
        (tmp_path / "DEFAULT_LANGUAGE.txt").write_text(marker + "\n")
    monkeypatch.setenv("CALCLENS_LANGUAGE", "parent-value")
    monkeypatch.setenv("STREAMLIT_SERVER_BASE_URL_PATH", "inherited-prefix")
    calls = []

    def fake_run(command, **options):
        calls.append((command, options))
        return SimpleNamespace(returncode=7)

    monkeypatch.setattr(launcher.subprocess, "run", fake_run)
    arguments = ["--legacy-ui"] + (["--language", explicit] if explicit else [])
    result = launcher.main(arguments, project_dir=tmp_path)
    assert result == 7
    assert len(calls) == 1
    command, options = calls[0]
    assert command[:4] == [sys.executable, "-m", "streamlit", "run"]
    assert "--server.address=127.0.0.1" in command
    assert "--server.port=8501" in command
    assert "--server.baseUrlPath=" in command
    assert "--browser.gatherUsageStats=false" in command
    assert options["cwd"] == tmp_path.resolve()
    assert options["env"]["CALCLENS_LANGUAGE"] == expected
    assert os.environ["CALCLENS_LANGUAGE"] == "parent-value"


def test_launcher_rejects_invalid_marker_without_launch(tmp_path, monkeypatch, capsys):
    (tmp_path / "streamlit_app.py").write_text("# fixture")
    (tmp_path / "DEFAULT_LANGUAGE.txt").write_text("unexpected")
    monkeypatch.setattr(launcher.subprocess, "run", lambda *args, **kwargs: pytest.fail("Must not launch"))
    with pytest.raises(SystemExit) as error:
        launcher.main([], project_dir=tmp_path)
    assert error.value.code == 2
    assert "DEFAULT_LANGUAGE.txt must contain" in capsys.readouterr().err


def test_default_launcher_uses_bundled_workspace_and_current_sources(tmp_path, monkeypatch):
    (tmp_path / "src").mkdir()
    monkeypatch.setenv("PYTHONPATH", "old-location")
    calls = []
    monkeypatch.setattr(launcher.subprocess, "run", lambda command, **kwargs:
                        calls.append((command, kwargs)) or SimpleNamespace(returncode=0))
    assert launcher.main(["--no-browser", "--language", "en", "--port", "8502"],
                         project_dir=tmp_path) == 0
    command, options = calls[0]
    assert command == [sys.executable, "-m", "slab_preflight.web_api", "--root", str(tmp_path),
                       "--port", "8502", "--language", "en", "--no-browser"]
    assert options["env"]["PYTHONPATH"] == str(tmp_path / "src") + os.pathsep + "old-location"
    assert os.environ["PYTHONPATH"] == "old-location"


def test_source_legacy_launcher_explains_the_optional_extra(tmp_path, monkeypatch, capsys):
    (tmp_path / "streamlit_app.py").write_text("# fixture")
    monkeypatch.setattr(launcher.importlib.util, "find_spec", lambda name: None)
    monkeypatch.setattr(launcher.subprocess, "run", lambda *args, **kwargs:
                        pytest.fail("Missing optional UI must not launch a child process"))
    with pytest.raises(SystemExit) as error:
        launcher.main(["--legacy-ui"], project_dir=tmp_path)
    assert error.value.code == 2
    assert '[legacy-ui]' in capsys.readouterr().err


def test_explicit_language_recovers_invalid_marker_and_supports_port(tmp_path, monkeypatch):
    (tmp_path / "streamlit_app.py").write_text("# fixture")
    (tmp_path / "DEFAULT_LANGUAGE.txt").write_text("invalid")
    calls = []
    monkeypatch.setattr(launcher.subprocess, "run", lambda command, **kwargs: calls.append((command, kwargs)) or SimpleNamespace(returncode=0))
    assert launcher.main(["--legacy-ui", "--language", "en", "--port", "8502"], project_dir=tmp_path) == 0
    assert "--server.port=8502" in calls[0][0]
    assert calls[0][1]["env"]["CALCLENS_LANGUAGE"] == "en"


@pytest.mark.parametrize("port", ["0", "65536", "text"])
def test_launcher_invalid_port_never_launches(tmp_path, monkeypatch, port):
    monkeypatch.setattr(launcher.subprocess, "run", lambda *args, **kwargs: pytest.fail("Must not launch"))
    with pytest.raises(SystemExit):
        launcher.main(["--port", port], project_dir=tmp_path)


def test_language_archives_share_engine_and_only_localized_metadata_differs(source_repo):
    paths = release.build_release(source_repo)
    assert {path.name for path in paths} == {
        "calclens-0.1.1-en.zip", "calclens-0.1.1-ko.zip",
        "CalcLens-Guide.en.md", "CalcLens-Guide.ko.md", "SHA256SUMS.txt",
    }
    archives = {language: archive_files(source_repo / "dist" / f"calclens-0.1.1-{language}.zip") for language in ("en", "ko")}
    assert archives["en"].keys() == archives["ko"].keys()
    differences = {path for path in archives["en"] if archives["en"][path] != archives["ko"][path]}
    assert differences == {"README.md", "DEFAULT_LANGUAGE.txt", "START_HERE.md", "BUILD_INFO.json"}
    for language, files in archives.items():
        assert files["DEFAULT_LANGUAGE.txt"] == f"{language}\n".encode()
        assert files["README.md"] == files[f"README.{language}.md"]
        info = json.loads(files["BUILD_INFO.json"])
        assert info == {"version": "0.1.1", "language": language, "source_commit": git(source_repo, "rev-parse", "HEAD")}
        for required in ("LICENSE", "THIRD_PARTY_NOTICES.md", "requirements.lock", "uv.lock", "docs/METHODS.md", "examples/graphene.cif", "tests/test_example.py", "src/slab_preflight/core.py"):
            assert required in files
        with zipfile.ZipFile(source_repo / "dist" / f"calclens-0.1.1-{language}.zip") as archive:
            assert all(name.startswith(f"calclens-0.1.1-{language}/") for name in archive.namelist())
            assert all(info.date_time == (1980, 1, 1, 0, 0, 0) for info in archive.infolist())
            assert all(not name.startswith("/") and ".." not in name.split("/") for name in archive.namelist())


def test_release_bytes_are_reproducible_and_checksums_match(source_repo):
    first = {path.name: path.read_bytes() for path in release.build_release(source_repo)}
    second = {path.name: path.read_bytes() for path in release.build_release(source_repo)}
    assert first == second
    for line in first["SHA256SUMS.txt"].decode().splitlines():
        checksum, name = line.split("  ", 1)
        assert checksum == hashlib.sha256(first[name]).hexdigest()
    assert git(source_repo, "status", "--porcelain") == ""


def test_standalone_guides_have_immutable_github_links(source_repo):
    release.build_release(source_repo)
    commit_id = git(source_repo, "rev-parse", "HEAD")
    for language in ("en", "ko"):
        guide = (source_repo / "dist" / f"CalcLens-Guide.{language}.md").read_text()
        assert f"https://github.com/example/calclens/blob/{commit_id}/docs/METHODS.md#limits" in guide
        assert f"https://github.com/example/calclens/blob/{commit_id}/LICENSE" in guide
        assert "](docs/" not in guide


def test_dirty_tracked_source_is_rejected_before_writing(source_repo):
    (source_repo / "src/slab_preflight/core.py").write_text("# uncommitted engine")
    with pytest.raises(release.ReleaseError, match="clean tracked tree"):
        release.build_release(source_repo)
    assert not (source_repo / "dist").exists()


def test_nonignored_untracked_source_is_rejected(source_repo):
    (source_repo / "new_source.py").write_text("# not committed")
    with pytest.raises(release.ReleaseError, match="nonignored untracked"):
        release.build_release(source_repo)


def test_ignored_local_data_never_enters_archive(source_repo):
    (source_repo / ".env").write_text("DUMMY_SECRET=do-not-package")
    (source_repo / ".venv").mkdir()
    (source_repo / ".venv" / "private.txt").write_text("local-only")
    (source_repo / "uploads").mkdir()
    (source_repo / "uploads" / "private.cif").write_text("local-only")
    release.build_release(source_repo)
    files = archive_files(source_repo / "dist" / "calclens-0.1.1-en.zip")
    assert not any(name.startswith((".env", ".venv", "uploads")) for name in files)
    assert all(b"do-not-package" not in content for content in files.values())


@pytest.mark.parametrize("path", [".env", "uploads/private.cif", ".venv/private.txt", ".streamlit/secrets.toml", "private.pem"])
def test_force_tracked_sensitive_paths_block_release(source_repo, path):
    target = source_repo / path
    target.parent.mkdir(exist_ok=True, parents=True)
    target.write_text("dummy private fixture, not a real credential")
    git(source_repo, "add", "-f", path)
    commit(source_repo, "intentionally forbidden fixture")
    with pytest.raises(release.ReleaseError, match="cannot be released"):
        release.build_release(source_repo)
    assert not (source_repo / "dist").exists()


def test_tracked_symlink_is_rejected(source_repo):
    (source_repo / "linked.py").symlink_to("src/slab_preflight/core.py")
    commit(source_repo, "intentionally symlinked fixture")
    with pytest.raises(release.ReleaseError, match="symlinks/submodules rejected"):
        release.build_release(source_repo)


@pytest.mark.parametrize("path", ["../escape", "/absolute", "a/../b", "a//b", "a\\b", "C:drive", "line\nbreak", "trailing.", "trailing ", "CON.txt"])
def test_unsafe_archive_paths_are_rejected(path):
    with pytest.raises(release.ReleaseError, match="Unsafe archive path"):
        release._safe_path(path)


def test_case_insensitive_paths_are_not_ambiguous():
    # macOS's filesystem cannot necessarily create this pair; the path guard
    # covers environmental names independently of casing.
    with pytest.raises(release.ReleaseError):
        release._safe_path(".VENV/private.txt")


def test_standalone_links_preserve_external_urls_and_reference_anchors():
    text = '[Web](https://example.com/x) [Here](#part) [A](docs/A.md#x "title")\n[ref]: LICENSE\n'
    converted = release.absolute_guide_links(text, "https://github.com/example/calclens", "abc123")
    assert "https://example.com/x" in converted
    assert "[Here](#part)" in converted
    assert '[A](https://github.com/example/calclens/blob/abc123/docs/A.md#x "title")' in converted
    assert "[ref]: https://github.com/example/calclens/blob/abc123/LICENSE" in converted


def test_guide_links_cannot_escape_repo():
    with pytest.raises(release.ReleaseError, match="escapes the repository"):
        release.absolute_guide_links("[X](../outside.md)", "https://github.com/example/calclens", "abc123")


def test_existing_symlink_output_is_rejected_before_any_asset_write(source_repo, tmp_path):
    target = tmp_path / "existing.txt"
    target.write_text("preserve me")
    destination = source_repo / "dist"
    destination.mkdir()
    (destination / "SHA256SUMS.txt").symlink_to(target)
    with pytest.raises(release.ReleaseError, match="symlink or non-file output"):
        release.build_release(source_repo)
    assert target.read_text() == "preserve me"
    assert list(destination.iterdir()) == [destination / "SHA256SUMS.txt"]
