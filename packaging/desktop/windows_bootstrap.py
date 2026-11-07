"""First Python code in the folder distribution; keep imports stdlib-only."""
import os
from pathlib import Path
import sys
import tempfile
import time


started_ns = time.perf_counter_ns()
try:
    from slab_preflight import startup

    startup.configure(started_ns=started_ns)
    startup.install_diagnostics(redirect=True)

    def launch():
        from slab_preflight.desktop_entry import main

        return main()

    result = startup.guarded_main(launch)
except Exception as error:
    # Package/source damage must still be diagnosable before any Qt imports.
    directory = Path(os.environ.get("LOCALAPPDATA", tempfile.gettempdir())) / "CalcLens" / "logs"
    try:
        directory.mkdir(parents=True, exist_ok=True)
        path = directory / f"bootstrap-{os.getpid()}.log"
        path.write_text(f"CalcLens bootstrap failed: {type(error).__name__}\n", encoding="utf-8")
    except OSError:
        path = directory
    if sys.platform == "win32":
        import ctypes

        ctypes.windll.user32.MessageBoxW(
            None, f"CalcLens could not load its application files.\n"
            f"Extract the complete ZIP into a new folder.\n\n"
            f"CalcLens 앱 파일을 불러오지 못했습니다. ZIP 전체를 새 폴더에 다시 풀어 주세요.\n\n{path}",
            "CalcLens", 0x10,
        )
    result = 1

raise SystemExit(result)
