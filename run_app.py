"""Start CalcLens locally with the language selected by this source package."""

from __future__ import annotations

import argparse
import importlib.util
import os
from pathlib import Path
import subprocess
import sys


def _port(value: str) -> int:
    try:
        number = int(value)
    except ValueError:
        raise argparse.ArgumentTypeError("Port must be an integer from 1 to 65535.") from None
    if not 1 <= number <= 65535:
        raise argparse.ArgumentTypeError("Port must be an integer from 1 to 65535.")
    return number


def package_language(project_dir: Path) -> str:
    """Read a release's language marker; a source checkout defaults to Korean."""
    marker = project_dir / "DEFAULT_LANGUAGE.txt"
    if not marker.exists():
        return "ko"
    try:
        language = marker.read_text(encoding="utf-8").strip().lower()
    except (OSError, UnicodeError) as error:
        raise ValueError(f"Cannot read DEFAULT_LANGUAGE.txt: {error}") from None
    if language not in ("en", "ko"):
        raise ValueError("DEFAULT_LANGUAGE.txt must contain exactly 'en' or 'ko'.")
    return language


def main(argv: list[str] | None = None, *, project_dir: Path | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--language", choices=("en", "ko"), help="Override the package's default language.")
    parser.add_argument("--port", type=_port, help="TCP port for the explicitly selected browser workspace.")
    parser.add_argument("--legacy-ui", action="store_true", help="Use the previous Streamlit interface.")
    parser.add_argument("--no-browser", action="store_true", help="Do not open the browser.")
    parser.add_argument("--web-ui", action="store_true", help="Open the optional browser workspace.")
    parser.add_argument("files", nargs="*", help="CIF files or a saved desktop project.")
    args = parser.parse_args(argv)
    root = (project_dir or Path(__file__).resolve().parent).resolve()
    if not root.is_dir():
        parser.error("The CalcLens package directory is missing.")
    if args.legacy_ui:
        if not (root / "streamlit_app.py").is_file():
            parser.error("streamlit_app.py is missing from the optional legacy UI package.")
        if any(importlib.util.find_spec(name) is None for name in ("streamlit", "plotly")):
            parser.error('The legacy UI requires optional packages. Install them with '
                         'python -m pip install ".[legacy-ui]", or use a -legacy Windows bundle.')
    try:
        language = args.language or package_language(root)
    except ValueError as error:
        parser.error(str(error))
    if not (args.web_ui or args.legacy_ui or args.no_browser or args.port is not None):
        if (root / "src").is_dir():
            sys.path.insert(0, str(root / "src"))
        from slab_preflight.desktop import main as native_main
        return native_main(language=language, root=root, argv=["CalcLens", *args.files])
    if args.files:
        parser.error("Open file paths using the native desktop mode.")
    args.port = args.port or 8501
    environment = os.environ.copy()
    environment["CALCLENS_LANGUAGE"] = language
    command = [
        sys.executable, "-m", "streamlit", "run", str(root / "streamlit_app.py"),
        "--server.address=127.0.0.1", f"--server.port={args.port}",
        "--server.baseUrlPath=",
        "--browser.gatherUsageStats=false",
    ]
    if args.no_browser:
        command.append("--server.headless=true")
    if not args.legacy_ui:
        command = [sys.executable, "-m", "slab_preflight.web_api", "--root", str(root),
                   "--port", str(args.port), "--language", language]
        if args.no_browser:
            command.append("--no-browser")
    # A source checkout should run its current code, even beside an older wheel.
    if (root / "src").is_dir():
        environment["PYTHONPATH"] = str(root / "src") + (
            os.pathsep + environment["PYTHONPATH"] if environment.get("PYTHONPATH") else ""
        )
    try:
        return subprocess.run(command, cwd=root, env=environment, check=False).returncode
    except KeyboardInterrupt:
        return 130


if __name__ == "__main__":
    raise SystemExit(main())
