"""Standard-library-only startup milestones and private failure diagnostics.

No project contents, command-line arguments, remote addresses or credentials are
written here. A loading indicator is never the application's ready milestone.
"""
from __future__ import annotations

from contextlib import contextmanager
from datetime import datetime, timezone
import faulthandler
import json
import os
from pathlib import Path
import re
import sys
import tempfile
import threading
import time
import traceback


_started_ns = time.perf_counter_ns()
_parent_ns = None
_output = None
_benchmark = False
_stages = {}
_lock = threading.RLock()
_log_stream = None
_log_path = None


def configure(path=None, *, benchmark=False, started_ns=None):
    """Enable a trace explicitly. The parent clock is same-host monotonic time."""
    global _output, _benchmark, _started_ns, _parent_ns
    with _lock:
        _stages.clear()
        _output = Path(path) if path is not None else None
        _benchmark = bool(benchmark)
        if started_ns is not None:
            _started_ns = int(started_ns)
        parent = os.environ.get("CALCLENS_STARTUP_PARENT_NS", "")
        _parent_ns = int(parent) if parent.isdecimal() else None
        if _parent_ns is not None and not 0 <= _started_ns - _parent_ns < 3_600_000_000_000:
            _parent_ns = None
        _stages["python_entry"] = _started_ns
        _write_trace()


def benchmark_requested():
    return _benchmark


def mark(name):
    """Record an actual event once; later calls cannot hide an earlier delay."""
    if not re.fullmatch(r"[a-z][a-z0-9_]{0,79}", name):
        raise ValueError("Invalid startup milestone name.")
    with _lock:
        _stages.setdefault(name, time.perf_counter_ns())
        _write_trace()


@contextmanager
def trace_span(name):
    mark(name + "_begin")
    try:
        yield
    finally:
        mark(name + "_complete")


def trace_record():
    with _lock:
        relative = {name: round((value - _started_ns) / 1e6, 3)
                    for name, value in _stages.items()}
        record = {
            "schema_version": 1,
            "platform": sys.platform,
            "python": sys.version.split()[0],
            "clock": "same-host perf_counter_ns",
            "mode": "benchmark" if _benchmark else "normal",
            "milestones_ms": relative,
            "ready": all(name in _stages for name in
                         ("first_window", "default_analysis_complete", "first_input_response")),
        }
        if _parent_ns is not None:
            record["parent_to_python_ms"] = round((_started_ns - _parent_ns) / 1e6, 3)
            record["launch_to_ms"] = {
                name: round((value - _parent_ns) / 1e6, 3)
                for name, value in _stages.items()
            }
        unpack = os.environ.get("CALCLENS_RUNTIME_UNPACK_MS", "")
        if unpack.isdecimal():
            record["runtime_unpack_ms"] = int(unpack)
        return record


def _write_trace():
    if _output is None:
        return
    _output.parent.mkdir(parents=True, exist_ok=True)
    temporary = _output.with_name(f".{_output.name}.{os.getpid()}.tmp")
    try:
        temporary.write_text(json.dumps(trace_record(), indent=2) + "\n", encoding="utf-8")
        os.replace(temporary, _output)
    finally:
        temporary.unlink(missing_ok=True)


def diagnostic_directory():
    if sys.platform == "win32":
        return Path(os.environ.get("LOCALAPPDATA", tempfile.gettempdir())) / "CalcLens" / "logs"
    if sys.platform == "darwin":
        return Path.home() / "Library" / "Logs" / "CalcLens"
    return Path(os.environ.get("XDG_STATE_HOME", Path.home() / ".local" / "state")) / "CalcLens" / "logs"


def install_diagnostics(*, directory=None, redirect=False):
    """Prepare a per-process log before Qt/ASE imports, including fatal crashes."""
    global _log_stream, _log_path
    if _log_stream is not None:
        return _log_path
    directory = Path(directory) if directory is not None else diagnostic_directory()
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    candidates = (directory, Path(tempfile.gettempdir()) / "CalcLens-logs")
    for candidate in candidates:
        try:
            candidate.mkdir(parents=True, exist_ok=True)
            path = candidate / f"startup-{stamp}-{os.getpid()}.log"
            stream = path.open("a", encoding="utf-8", buffering=1)
        except OSError:
            continue
        _log_path, _log_stream = path, stream
        break
    if _log_stream is None:
        raise OSError("CalcLens could not create a diagnostic log in either writable location.")
    _log_stream.write(f"CalcLens startup | Python {sys.version.split()[0]} | {sys.platform}\n")
    try:
        faulthandler.enable(file=_log_stream)
    except (OSError, RuntimeError):
        pass
    # pythonw provides no visible stderr. Unhandled exceptions use the safe hook
    # rather than printing exception arguments that could contain a remote token.
    if redirect and sys.stderr is None:
        sys.stderr = _log_stream
    sys.excepthook = _unhandled
    return _log_path


def log_failure(error):
    """Store frame locations and an error class, without input/exception values."""
    path = install_diagnostics()
    frames = traceback.extract_tb(error.__traceback__)
    record = {
        "event": "startup_failure",
        "exception": type(error).__name__,
        "last_milestone": next(reversed(_stages), "before_python_entry"),
        "frames": [{"file": Path(frame.filename).name, "line": frame.lineno,
                    "function": frame.name} for frame in frames],
    }
    if isinstance(error, ModuleNotFoundError) and re.fullmatch(r"[a-zA-Z0-9_.]+", error.name or ""):
        record["missing_module"] = error.name
    if isinstance(error, OSError):
        record["errno"] = error.errno
        record["winerror"] = getattr(error, "winerror", None)
    _log_stream.write(json.dumps(record, ensure_ascii=False) + "\n")
    _log_stream.flush()
    return path


def show_failure(error, *, language="ko", path=None):
    path = path or log_failure(error)
    reason = type(error).__name__
    if isinstance(error, ModuleNotFoundError):
        explanation = ("필요한 구성 요소를 불러오지 못했습니다. ZIP 전체를 새 폴더에 다시 풀어 주세요."
                       if language == "ko" else
                       "A required component could not be loaded. Extract the complete ZIP to a new folder.")
    else:
        explanation = ("앱을 시작하지 못했습니다. 아래 진단 파일을 확인해 주세요."
                       if language == "ko" else
                       "The application could not start. Please check the diagnostic file below.")
    message = f"{explanation}\n\n{reason}\n{path}"
    # This path deliberately does not import Qt: it must work if Qt itself fails.
    if sys.platform == "win32":
        import ctypes

        ctypes.windll.user32.MessageBoxW(None, message, "CalcLens", 0x10)
    elif sys.stderr is not None:
        print(message, file=sys.stderr)


def _unhandled(kind, error, tb):
    error = error.with_traceback(tb)
    path = log_failure(error)
    show_failure(error, path=path)


def guarded_main(function, *, language="ko"):
    install_diagnostics(redirect=True)
    try:
        return function()
    except Exception as error:
        path = log_failure(error)
        show_failure(error, language=language, path=path)
        return 1
