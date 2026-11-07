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


def build_info(
    language: str, mode: str, source_commit: str, *, include_legacy_ui: bool = False,
) -> dict:
    if not re.fullmatch(r"[0-9a-f]{40}|[0-9a-f]{64}", source_commit):
        raise ValueError("source_commit must be a full Git commit hash")
    project = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    # Installed versions make the build auditable, including the build tools.
    environment_dependencies = {
        dist.metadata["Name"]: dist.version
        for dist in importlib.metadata.distributions() if dist.metadata["Name"]
    }
    roots = ("ase", "numpy", "PySide6-Essentials", "shiboken6") + (("streamlit", "plotly") if include_legacy_ui else ())
    dependencies = {name: importlib.metadata.version(name) for name in roots}
    assets = ROOT / "src" / "slab_preflight" / "web_assets"
    if not (assets / "index.html").is_file():
        raise ValueError("Build the frontend assets with npm ci and npm run build first.")
    asset_hashes = {
        path.relative_to(assets).as_posix(): hashlib.sha256(path.read_bytes()).hexdigest()
        for path in sorted(assets.rglob("*")) if path.is_file()
    }
    return {
        "format": "calclens.windows-build", "version": project["project"]["version"],
        "language": language, "source_commit": source_commit,
        "architecture": "x86_64", "python_version": platform.python_version(),
        "pyinstaller_version": importlib.metadata.version("pyinstaller"),
        "build_mode": mode, "dependencies": dict(sorted(dependencies.items())),
        "build_environment_dependencies": dict(sorted(environment_dependencies.items())),
        "includes_legacy_ui": include_legacy_ui,
        "variant": "legacy" if include_legacy_ui else "workspace",
        "app_sha256": hashlib.sha256((ROOT / "streamlit_app.py").read_bytes()).hexdigest()
        if include_legacy_ui else None,
        "workspace_asset_sha256": asset_hashes,
        "frontend_lock_sha256": hashlib.sha256((ROOT / "frontend" / "package-lock.json").read_bytes()).hexdigest(),
    }


def bundle_name(version: str, language: str, *, include_legacy_ui: bool = False) -> str:
    suffix = "-legacy" if include_legacy_ui else ""
    return f"CalcLens-{version}-windows-x64-{language}{suffix}"


def validate_notices(manifest: dict, info: dict, source_commit: str) -> None:
    if manifest.get("source_commit") != source_commit or manifest.get("version") != info["version"]:
        raise ValueError("The third-party notices belong to a different build.")
    if manifest.get("includes_legacy_ui") is not info["includes_legacy_ui"]:
        raise ValueError("The third-party notices belong to a different UI variant.")
    packages = manifest["runtime_dependencies"] + manifest["build_tools"]
    if (manifest["python"]["version"] != platform.python_version()
            or any(importlib.metadata.version(item["name"]) != item["version"] for item in packages)):
        raise ValueError("Dependencies changed; regenerate notices in a fresh --notices directory.")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--language", choices=("ko", "en"), required=True)
    parser.add_argument("--mode", choices=("onedir", "onefile"), default="onefile")
    parser.add_argument("--output", type=Path, default=ROOT / "dist" / "windows")
    parser.add_argument("--notices", type=Path)
    parser.add_argument("--source-commit")
    parser.add_argument("--include-legacy-ui", action="store_true",
                        help="Include optional Streamlit/Plotly UI in a separate -legacy bundle.")
    args = parser.parse_args(argv)
    if (sys.platform != "win32" or platform.machine().lower() not in ("amd64", "x86_64")
            or struct.calcsize("P") != 8):
        parser.error("Build this executable on Windows x64, using x64 Python.")
    commit = args.source_commit or subprocess.check_output(
        ["git", "rev-parse", "HEAD"], cwd=ROOT, text=True,
    ).strip()
    info = build_info(args.language, args.mode, commit, include_legacy_ui=args.include_legacy_ui)
    suffix = "-legacy" if args.include_legacy_ui else ""
    stage = ROOT / "build" / "windows" / (args.language + suffix) / "stage"
    stage.mkdir(parents=True, exist_ok=True)
    (stage / "DEFAULT_LANGUAGE.txt").write_text(args.language + "\n", encoding="utf-8")
    notices = (args.notices or ROOT / "build" / "windows" / ("notices" + suffix)).resolve()
    if not notices.exists():
        subprocess.run(
            [sys.executable, str(ROOT / "scripts" / "collect_windows_licenses.py"),
             "--output", str(notices), "--source-commit", commit,
             *(["--include-legacy-ui"] if args.include_legacy_ui else [])], check=True, cwd=ROOT,
        )
    manifest_path = notices / "DEPENDENCIES.json"
    if not manifest_path.is_file():
        parser.error("The third-party notice collection is incomplete.")
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    try:
        validate_notices(manifest, info, commit)
    except ValueError as error:
        parser.error(str(error))
    info["dependencies"] = {item["name"]: item["version"] for item in manifest["runtime_dependencies"]}
    (stage / "WINDOWS_BUILD_INFO.json").write_text(
        json.dumps(info, indent=2, ensure_ascii=False) + "\n", encoding="utf-8",
    )
    name = bundle_name(info["version"], args.language, include_legacy_ui=args.include_legacy_ui)
    output = args.output.resolve()
    environment = os.environ.copy()
    environment.update({
        "CALCLENS_BUILD_STAGE": str(stage), "CALCLENS_BUILD_NOTICES": str(notices),
        "CALCLENS_BUILD_MODE": args.mode, "CALCLENS_BUILD_NAME": name,
        "CALCLENS_BUILD_INCLUDE_LEGACY_UI": "1" if args.include_legacy_ui else "0",
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
