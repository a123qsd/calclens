"""Atomic desktop project saves and recoverable, process-owned drafts."""

from __future__ import annotations

from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
import os
import sys
import tempfile
import threading
from uuid import UUID, uuid4

from .project import MAX_ARCHIVE_BYTES, loads_project


def atomic_write(path: Path, data: bytes) -> None:
    path = Path(path)
    with tempfile.NamedTemporaryFile(
        dir=path.parent, prefix=f".{path.name}.", delete=False
    ) as stream:
        temp = Path(stream.name)
        try:
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())
        except BaseException:
            stream.close()
            temp.unlink(missing_ok=True)
            raise
    try:
        os.replace(temp, path)
    finally:
        temp.unlink(missing_ok=True)


def _directory() -> Path:
    if sys.platform == "darwin":
        return Path.home() / "Library" / "Application Support" / "CalcLens" / "Recovery"
    if os.name == "nt":
        return (
            Path(os.environ.get("LOCALAPPDATA") or Path.home() / "AppData" / "Local")
            / "CalcLens"
            / "Recovery"
        )
    return (
        Path(os.environ.get("XDG_STATE_HOME") or Path.home() / ".local" / "state")
        / "calclens"
        / "recovery"
    )


def _lock(stream) -> bool:
    try:
        if os.name == "nt":
            import msvcrt

            stream.seek(0)
            msvcrt.locking(stream.fileno(), msvcrt.LK_NBLCK, 1)
        else:
            import fcntl

            fcntl.flock(stream.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
    except (BlockingIOError, PermissionError):
        return False
    return True


@dataclass(frozen=True)
class RecoveryInfo:
    session_id: str
    modified: datetime
    previous: bool = False


class RecoveryStore:
    def __init__(self, directory: Path | None = None):
        self.directory = Path(directory) if directory is not None else _directory()
        self.directory.mkdir(mode=0o700, parents=True, exist_ok=True)
        self.session_id = uuid4().hex
        self._guard = threading.RLock()
        self._owner = self._lease(self.session_id)
        if not _lock(self._owner):
            self._owner.close()
            raise OSError("Could not acquire the new recovery session.")

    def _lease(self, session_id: str):
        stream = (self.directory / f"{session_id}.lock").open("a+b")
        if stream.tell() == 0:
            stream.write(b"0")
            stream.flush()
        return stream

    def _path(self, session_id: str, previous=False) -> Path:
        if UUID(session_id).hex != session_id:
            raise ValueError("Invalid recovery identifier.")
        return self.directory / (session_id + (".previous" if previous else "") + ".zip")

    @contextmanager
    def _inactive(self, session_id):
        self._path(session_id)
        with self._lease(session_id) as lease:
            yield _lock(lease)

    def _info(self, session_id, previous=False):
        modified = datetime.fromtimestamp(
            self._path(session_id, previous).stat().st_mtime, timezone.utc
        )
        return RecoveryInfo(session_id, modified, previous)

    def _read(self, info: RecoveryInfo) -> bytes:
        with self._path(info.session_id, info.previous).open("rb") as stream:
            data = stream.read(MAX_ARCHIVE_BYTES + 1)
        if len(data) > MAX_ARCHIVE_BYTES:
            raise ValueError("Recovery file exceeds the project size limit.")
        loads_project(data)
        return data

    def candidates(self) -> list[RecoveryInfo]:
        found = []
        sessions = {item.name.split(".")[0] for item in self.directory.glob("*.zip")}
        for session in sessions - {self.session_id}:
            try:
                with self._inactive(session) as available:
                    if not available:
                        continue
                    for previous in (False, True):
                        try:
                            info = self._info(session, previous)
                            self._read(info)
                        except (OSError, ValueError):
                            continue
                        found.append(info)
                        break
            except (ValueError, FileNotFoundError):
                continue
        return sorted(found, key=lambda item: item.modified, reverse=True)

    def load(self, info: RecoveryInfo) -> bytes:
        with self._inactive(info.session_id) as available:
            if not available:
                raise ValueError("This project is open in another CalcLens session.")
            return self._read(info)

    def save(self, archive: bytes) -> RecoveryInfo:
        with self._guard:
            if self._owner.closed:
                raise ValueError("Recovery session is closed.")
            loads_project(archive)
            current = self._path(self.session_id)
            prior = self._path(self.session_id, True)
            if current.exists():
                # Keep a complete previous generation even if replacement is interrupted.
                try:
                    previous = self._read(self._info(self.session_id))
                except (OSError, ValueError):
                    pass
                else:
                    atomic_write(prior, previous)
            atomic_write(current, archive)
            return self._info(self.session_id)

    def discard(self, info: RecoveryInfo | None = None) -> None:
        with self._guard:
            owner = self.session_id if info is None else info.session_id

            def remove():
                for previous in (False, True):
                    self._path(owner, previous).unlink(missing_ok=True)

            if owner == self.session_id:
                remove()
            else:
                with self._inactive(owner) as available:
                    if not available:
                        raise ValueError("Another CalcLens session owns this recovery file.")
                    remove()
                (self.directory / f"{owner}.lock").unlink(missing_ok=True)

    def close(self, keep: bool = True) -> None:
        with self._guard:
            if self._owner.closed:
                return
            if not keep:
                self.discard()
            self._owner.close()
            if (
                not self._path(self.session_id).exists()
                and not self._path(self.session_id, True).exists()
            ):
                (self.directory / f"{self.session_id}.lock").unlink(missing_ok=True)
