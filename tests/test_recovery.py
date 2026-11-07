import os

import pytest

from slab_preflight.project import Project, ProjectEntry, dumps_project_archive, loads_project
from slab_preflight.recovery import RecoveryStore


def archive(note):
    return dumps_project_archive(
        Project([ProjectEntry("file", "research.cif", b"original CIF", note=note)])
    )


def test_restarted_session_recovers_last_intact_generation_without_stealing_live_work(tmp_path):
    first = RecoveryStore(tmp_path)
    observer = RecoveryStore(tmp_path)
    original = archive("draft before edits")
    first.save(original)
    first.save(archive("most recent draft"))
    assert not observer.candidates()
    first.close()
    (newest,) = observer.candidates()
    assert loads_project(observer.load(newest)).entries[0].note == "most recent draft"
    (tmp_path / f"{first.session_id}.zip").write_bytes(b"interrupted archive")
    (backup,) = observer.candidates()
    assert backup.previous and observer.load(backup) == original
    observer.discard(backup)
    assert not observer.candidates()
    observer.close()


def test_failed_write_leaves_last_saved_project_readable(tmp_path, monkeypatch):
    first = RecoveryStore(tmp_path)
    original = archive("before failed save")
    first.save(original)
    replace = os.replace

    def fail_current(src, dst):
        if dst.name == first.session_id + ".zip":
            raise OSError("disk full")
        return replace(src, dst)

    monkeypatch.setattr(os, "replace", fail_current)
    with pytest.raises(OSError, match="disk full"):
        first.save(archive("later draft"))
    first.close()
    second = RecoveryStore(tmp_path)
    (record,) = second.candidates()
    assert second.load(record) == original
    second.close()


def test_invalid_save_cannot_replace_recovery_and_explicit_discard_removes_both_generations(
    tmp_path,
):
    store = RecoveryStore(tmp_path)
    store.save(archive("one"))
    store.save(archive("two"))
    with pytest.raises(ValueError):
        store.save(b"damaged")
    store.close(keep=False)
    assert list(tmp_path.iterdir()) == []
