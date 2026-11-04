"""Build a native Windows x64 bundle and record its exact inputs.

Python and the locked dependencies are needed on the build machine only.
The resulting onefile executable includes its Python runtime.
"""

from __future__ import annotations

import argparse
import hashlib
import importlib.metadata
import json
import os
from pathlib import Path
import platform
import re
import struct
import subprocess
import sys
import tomllib


ROOT = Path(__file__).resolve().parents[1]


def build_info(language: str, mode: str, source_commit: str) -> dict:
    if not re.fullmatch(r"[0-9a-f]{40}|[0-9a-f]{64}", source_commit):
        raise ValueError("source_commit must be a full Git commit hash")
    project = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    # Installed versions make the build auditable, including the build tools.
    dependencies = {
        dist.metadata["Name"]: dist.version
        for dist in importlib.metadata.distributions() if dist.metadata["Name"]
    }
    return {
        "format": "calclens.windows-build", "version": project["project"]["version"],
        "language": language, "source_commit": source_commit,
        "architecture": "x86_64", "python_version": platform.python_version(),
        "pyinstaller_version": importlib.metadata.version("pyinstaller"),
        "build_mode": mode, "dependencies": dict(sorted(dependencies.items())),
        "app_sha256": hashlib.sha256((ROOT / "streamlit_app.py").read_bytes()).hexdigest(),
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--language", choices=("ko", "en"), required=True)
    parser.add_argument("--mode", choices=("onedir", "onefile"), default="onefile")
    parser.add_argument("--output", type=Path, default=ROOT / "dist" / "windows")
    parser.add_argument("--notices", type=Path, default=ROOT / "build" / "windows" / "notices")
    parser.add_argument("--source-commit")
    args = parser.parse_args(argv)
    if (sys.platform != "win32" or platform.machine().lower() not in ("amd64", "x86_64")
            or struct.calcsize("P") != 8):
        parser.error("Build this executable on Windows x64, using x64 Python.")
    commit = args.source_commit or subprocess.check_output(
        ["git", "rev-parse", "HEAD"], cwd=ROOT, text=True,
    ).strip()
    info = build_info(args.language, args.mode, commit)
    stage = ROOT / "build" / "windows" / args.language / "stage"
    stage.mkdir(parents=True, exist_ok=True)
    (stage / "DEFAULT_LANGUAGE.txt").write_text(args.language + "\n", encoding="utf-8")
    (stage / "WINDOWS_BUILD_INFO.json").write_text(
        json.dumps(info, indent=2, ensure_ascii=False) + "\n", encoding="utf-8",
    )
    notices = args.notices.resolve()
    if not notices.exists():
        subprocess.run(
            [sys.executable, str(ROOT / "scripts" / "collect_windows_licenses.py"),
             "--output", str(notices), "--source-commit", commit], check=True, cwd=ROOT,
        )
    manifest_path = notices / "DEPENDENCIES.json"
    if not manifest_path.is_file():
        parser.error("The third-party notice collection is incomplete.")
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    if manifest["source_commit"] != commit or manifest["version"] != info["version"]:
        parser.error("The third-party notices belong to a different build.")
    packages = manifest["runtime_dependencies"] + manifest["build_tools"]
    if (manifest["python"]["version"] != platform.python_version()
            or any(importlib.metadata.version(item["name"]) != item["version"] for item in packages)):
        parser.error("Dependencies changed; regenerate notices in a fresh --notices directory.")
    name = f"CalcLens-{info['version']}-windows-x64-{args.language}"
    output = args.output.resolve()
    environment = os.environ.copy()
    environment.update({
        "CALCLENS_BUILD_STAGE": str(stage), "CALCLENS_BUILD_NOTICES": str(notices),
        "CALCLENS_BUILD_MODE": args.mode, "CALCLENS_BUILD_NAME": name,
        "PYTHONHASHSEED": "0",
    })
    subprocess.run(
        [sys.executable, "-m", "PyInstaller", "--noconfirm", "--distpath", str(output),
         "--workpath", str(stage.parent / "pyinstaller"),
         str(ROOT / "packaging" / "windows" / "CalcLens.spec")],
        check=True, cwd=ROOT, env=environment,
    )
    executable = output / (name + ".exe") if args.mode == "onefile" else output / name / (name + ".exe")
    if not executable.is_file():
        raise RuntimeError(f"Build did not produce {executable}")
    with executable.open("rb") as stream:
        digest = hashlib.file_digest(stream, "sha256").hexdigest()
    metadata = {**info, "filename": executable.name, "size": executable.stat().st_size,
                "sha256": digest}
    (output / (name + ".build.json")).write_text(
        json.dumps(metadata, indent=2, ensure_ascii=False) + "\n", encoding="utf-8",
    )
    print(json.dumps({"executable": str(executable), "sha256": metadata["sha256"]}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
