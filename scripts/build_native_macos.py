"""Build and verify a self-contained Apple Silicon .app from this checkout."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import platform
import subprocess
import sys
import tomllib
import tempfile

ROOT = Path(__file__).resolve().parents[1]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--build-dir", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args()
    if sys.platform != "darwin" or platform.machine() != "arm64":
        parser.error("Use an Apple Silicon macOS build host.")
    build = args.build_dir.resolve()
    output = args.output_dir.resolve()
    build.mkdir(parents=True, exist_ok=True)
    output.mkdir(parents=True, exist_ok=True)
    kernels = ROOT / "src/slab_preflight/kernels"
    subprocess.run(
        [
            sys.executable,
            str(ROOT / "scripts/build_compute_metal.py"),
            "--output",
            str(build / "calclens-metal-arm64"),
        ],
        check=True,
    )
    entry = build / "native_start.py"
    entry.write_text(
        'from multiprocessing import freeze_support\nfrom slab_preflight.desktop_entry import main\nif __name__ == "__main__":\n    freeze_support()\n    raise SystemExit(main())\n'
    )
    notices = build / "notices"
    notices.mkdir(exist_ok=True)
    from importlib import metadata

    names = ("PySide6-Essentials", "shiboken6", "ase", "numpy", "scipy", "pillow", "matplotlib")
    from shutil import copyfile

    for name in names:
        dist = metadata.distribution(name)
        for rec in dist.files or ():
            if not any(
                word in str(rec).lower() for word in ("license", "copying", "notice", "copyright")
            ):
                continue
            if ".." in rec.parts or "__pycache__" in rec.parts or rec.suffix == ".pyc":
                continue
            src = Path(dist.locate_file(rec))
            if src.is_file() and src.stat().st_size < 4_000_000:
                dest = notices / name / rec
                dest.parent.mkdir(parents=True, exist_ok=True)
                copyfile(src, dest)
    version = tomllib.loads((ROOT / "pyproject.toml").read_text())["project"]["version"]
    cmd = [
        sys.executable,
        "-m",
        "PyInstaller",
        "--noconfirm",
        "--windowed",
        "--onedir",
        "--target-arch",
        "arm64",
        "--name",
        "CalcLens",
        "--paths",
        str(ROOT / "src"),
        "--specpath",
        str(build),
        "--workpath",
        str(build / "analyze"),
        "--distpath",
        str(build / "dist"),
        "--osx-bundle-identifier",
        "org.calclens.desktop",
        "--icon",
        str(ROOT / "packaging/desktop/CalcLens.icns"),
        "--add-data",
        f"{ROOT}/examples:examples",
        "--add-data",
        f"{ROOT}/LICENSE:.",
        "--add-data",
        f"{ROOT}/THIRD_PARTY_NOTICES.md:.",
        "--add-data",
        f"{notices}:notices",
        "--add-data",
        f"{kernels}/compute_metal.swift:slab_preflight/kernels",
        "--add-data",
        f"{kernels}/density_cuda.ptx:slab_preflight/kernels",
        "--add-binary",
        f"{build}/calclens-metal-arm64:slab_preflight/kernels",
        "--collect-data",
        "ase",
        "--copy-metadata",
        "ase",
        "--copy-metadata",
        "numpy",
        "--copy-metadata",
        "PySide6-Essentials",
        "--exclude-module",
        "streamlit",
        "--exclude-module",
        "plotly",
        "--exclude-module",
        "PySide6.QtWebEngineWidgets",
        "--exclude-module",
        "PySide6.QtWebEngineCore",
        "--exclude-module",
        "IPython",
        "--exclude-module",
        "playwright",
        "--exclude-module",
        "pytest",
        "--exclude-module",
        "notebook",
        str(entry),
    ]
    # A synced Documents folder can add Finder resource attributes while a bundle
    # is being signed. Assemble/sign outside File Provider, then copy the result.
    stage = tempfile.TemporaryDirectory(prefix="calclens-native-dist-")
    staging = Path(stage.name)
    cmd[cmd.index("--distpath") + 1] = str(staging)
    icon_index = cmd.index("--collect-data")
    cmd[icon_index:icon_index] = ["--add-data", f"{ROOT}/packaging/desktop/CalcLens.ico:."]
    subprocess.run(cmd, cwd=ROOT, check=True)
    app = staging / "CalcLens.app"
    # Publish accurate app metadata after PyInstaller resolves real Qt/Python frameworks.
    import plistlib

    p = app / "Contents/Info.plist"
    with p.open("rb") as f:
        info = plistlib.load(f)
    info.update(
        {
            "CFBundleShortVersionString": version,
            "CFBundleVersion": version,
            "CFBundleDisplayName": "CalcLens",
            "CFBundleDocumentTypes": [
                {
                    "CFBundleTypeName": "Crystallographic Information File",
                    "CFBundleTypeExtensions": ["cif"],
                    "CFBundleTypeRole": "Viewer",
                    "LSHandlerRank": "Alternate",
                }
            ],
        }
    )
    with p.open("wb") as f:
        plistlib.dump(info, f)
    subprocess.run(["codesign", "--force", "--sign", "-", str(app)], check=True)
    subprocess.run(["codesign", "--verify", "--deep", "--strict", str(app)], check=True)
    evidence = build / "native-app-smoke.json"
    subprocess.run(
        [str(app / "Contents/MacOS/CalcLens"), "--native-smoke", str(evidence)],
        check=True,
        timeout=150,
    )
    if json.loads(evidence.read_text())["status"] != "passed":
        raise RuntimeError("Bundled native application smoke failed.")
    archive = output / f"CalcLens-{version}-macOS-Apple-Silicon.zip"
    subprocess.run(
        ["ditto", "-c", "-k", "--sequesterRsrc", "--keepParent", str(app), str(archive)], check=True
    )
    # A file-provider folder can attach FinderInfo to a loose .app and invalidate
    # a strict signing check. Transport the signed bundle in a read-only image.
    image_root = staging / "image"
    image_root.mkdir()
    app.rename(image_root / "CalcLens.app")
    subprocess.run(
        [
            "hdiutil",
            "create",
            "-fs",
            "HFS+",
            "-format",
            "UDZO",
            "-volname",
            "CalcLens",
            "-srcfolder",
            str(image_root),
            "-ov",
            str(output / f"CalcLens-{version}-macOS-Apple-Silicon.dmg"),
        ],
        check=True,
    )
    stage.cleanup()
    print(archive)


if __name__ == "__main__":
    main()
