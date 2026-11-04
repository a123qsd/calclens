"""Collect installed Windows runtime notices and exact ASE source for redistribution."""

from __future__ import annotations

import argparse
import hashlib
import io
from importlib import metadata
import json
from pathlib import Path, PurePosixPath
import platform
import re
import sys
import sysconfig
import tarfile
import tomllib
from urllib.parse import quote, urlsplit
from urllib.request import urlopen
import zipfile

from packaging.markers import default_environment
from packaging.requirements import Requirement
from packaging.utils import canonicalize_name

ROOT = Path(__file__).resolve().parents[1]
RUNTIME_ROOTS = ("streamlit", "plotly", "ase", "numpy")
BUILD_TOOLS = ("pyinstaller", "pyinstaller-hooks-contrib")
NOTICE_WORDS = ("license", "licence", "copying", "notice", "copyright", "authors")
MAX_DOWNLOAD = 64 * 1024 * 1024


def is_notice(path: str) -> bool:
    return any(word in part.lower() for part in PurePosixPath(path).parts
               for word in NOTICE_WORDS)


def safe_record(path: str) -> str:
    """Keep RECORD paths recognizable without allowing directory traversal."""
    value = PurePosixPath(path)
    if value.is_absolute() or "\\" in path or ":" in path:
        raise ValueError("Expected a relative package file record")
    return "/".join("__parent__" if part == ".." else part for part in value.parts)


def save(output: Path, relative: str, data: bytes) -> dict:
    destination = output / safe_record(relative)
    destination.parent.mkdir(parents=True, exist_ok=True)
    if destination.exists() and destination.read_bytes() != data:
        raise ValueError(f"Conflicting notice files: {relative}")
    destination.write_bytes(data)
    return {"path": relative, "sha256": hashlib.sha256(data).hexdigest(), "bytes": len(data)}


def download(url: str) -> bytes:
    parsed = urlsplit(url)
    if parsed.scheme != "https" or parsed.hostname not in (
        "pypi.org", "files.pythonhosted.org", "raw.githubusercontent.com"
    ):
        raise ValueError("Source downloads must use approved upstream HTTPS endpoints")
    with urlopen(url, timeout=60) as response:
        data = response.read(MAX_DOWNLOAD + 1)
    if len(data) > MAX_DOWNLOAD:
        raise ValueError("Source download exceeds 64 MiB")
    return data


def source_archive(name: str, version: str) -> tuple[dict, bytes]:
    endpoint = f"https://pypi.org/pypi/{quote(name, safe='')}/{quote(version, safe='')}/json"
    release = json.loads(download(endpoint))
    candidates = [item for item in release["urls"] if item["packagetype"] == "sdist"]
    if len(candidates) != 1:
        raise ValueError(f"Expected one exact source distribution for {name} {version}")
    item = candidates[0]
    filename = item["filename"]
    if filename != PurePosixPath(filename).name or not filename:
        raise ValueError("Unsafe source archive filename")
    data = download(item["url"])
    digest = hashlib.sha256(data).hexdigest()
    if digest != item["digests"]["sha256"]:
        raise ValueError(f"PyPI source SHA-256 mismatch for {name} {version}")
    return {"filename": filename, "url": item["url"], "sha256": digest,
            "verification": "SHA-256 matches exact-version PyPI JSON; not a signature"}, data


def archive_notices(filename: str, data: bytes) -> list[tuple[str, bytes]]:
    if filename.endswith(".zip"):
        with zipfile.ZipFile(io.BytesIO(data)) as archive:
            return [(item.filename, archive.read(item)) for item in archive.infolist()
                    if not item.is_dir() and is_notice(item.filename)]
    with tarfile.open(fileobj=io.BytesIO(data), mode="r:*") as archive:
        return [(item.name, archive.extractfile(item).read()) for item in archive.getmembers()
                if item.isfile() and is_notice(item.name)]


def runtime_closure(environment: dict[str, str]) -> list[str]:
    pending = [(name, frozenset()) for name in RUNTIME_ROOTS]
    visited, packages = set(), set()
    while pending:
        name, extras = pending.pop()
        name = canonicalize_name(name)
        state = (name, extras)
        if state in visited:
            continue
        visited.add(state)
        distribution = metadata.distribution(name)
        packages.add(name)
        for text in distribution.requires or []:
            requirement = Requirement(text)
            if requirement.marker is None or any(
                requirement.marker.evaluate({**environment, "extra": extra})
                for extra in ("", *sorted(extras))
            ):
                dependency = metadata.distribution(requirement.name)
                if not requirement.specifier.contains(dependency.version, prereleases=True):
                    raise ValueError(f"Installed dependency does not satisfy {requirement}")
                pending.append((requirement.name, frozenset(requirement.extras)))
    return sorted(packages)


def collect_distribution(name: str, output: Path, category: str) -> dict:
    distribution = metadata.distribution(name)
    prefix = f"{category}/{canonicalize_name(name)}-{distribution.version}"
    notices = []
    for record in distribution.files or []:
        package_path = str(record)
        if is_notice(package_path):
            data = Path(distribution.locate_file(record)).read_bytes()
            notices.append({"package_path": package_path,
                            **save(output, f"{prefix}/{safe_record(package_path)}", data)})
    source = None
    if not notices and canonicalize_name(name) == "streamlit":
        # Streamlit 1.66.1 omits its root license from both wheel and sdist.
        url = f"https://raw.githubusercontent.com/streamlit/streamlit/{distribution.version}/LICENSE"
        notices.append({"upstream_url": url, **save(output, f"{prefix}/upstream/LICENSE", download(url))})
    if not notices:
        source, data = source_archive(name, distribution.version)
        for path, contents in archive_notices(source["filename"], data):
            notices.append({"source_archive_path": path,
                            **save(output, f"{prefix}/source-archive/{safe_record(path)}", contents)})
    if not notices:
        raise ValueError(f"No license or notice files found for {name} {distribution.version}")
    result = {"name": distribution.metadata["Name"], "version": distribution.version,
              "license": distribution.metadata.get("License-Expression")
              or distribution.metadata.get("License", "Unspecified"), "files": notices}
    if source:
        result["notice_source_archive"] = source
    return result


def collect(output: Path, source_commit: str) -> dict:
    if not re.fullmatch(r"[0-9a-fA-F]{40}|[0-9a-fA-F]{64}", source_commit):
        raise ValueError("--source-commit must be a full hexadecimal Git commit ID")
    if output.exists() and any(output.iterdir()):
        raise ValueError("--output must be an empty directory")
    environment = default_environment()
    environment.update(os_name="nt", sys_platform="win32", platform_system="Windows",
                       platform_machine="AMD64", extra="")
    runtime = runtime_closure(environment)
    candidates = [Path(sys.base_prefix) / "LICENSE.txt", Path(sys.base_prefix) / "LICENSE",
                  Path(sysconfig.get_path("stdlib")) / "LICENSE.txt",
                  Path(sys.base_prefix) / "Lib" / "LICENSE.txt"]
    python_license = next((path for path in candidates if path.is_file()), None)
    if python_license is None:
        raise ValueError("CPython LICENSE.txt is missing; supply a complete CPython installation")
    if platform.python_implementation() != "CPython":
        raise ValueError("This Windows build requires CPython")
    python_notice = save(output, "python/LICENSE.txt", python_license.read_bytes())
    runtime_notices = [collect_distribution(name, output, "runtime-notices") for name in runtime]
    tools = [collect_distribution(name, output, "build-tool-notices") for name in BUILD_TOOLS]
    ase_source, data = source_archive("ase", metadata.version("ase"))
    ase_source.update(save(output, f"sources/{ase_source['filename']}", data))
    for name in ("LICENSE", "THIRD_PARTY_NOTICES.md"):
        save(output, f"application/{name}", (ROOT / name).read_bytes())
    project = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))["project"]
    manifest = {
        "schema_version": 1, "application": project["name"], "version": project["version"],
        "source_commit": source_commit.lower(), "runtime_roots": list(RUNTIME_ROOTS),
        "marker_environment": environment,
        "python": {"implementation": "CPython", "version": platform.python_version(),
                   "license_file": python_notice},
        "runtime_dependencies": runtime_notices, "build_tools": tools, "ase_source": ase_source,
        "scope": "Declared Windows runtime dependency closure and supplied notice files; "
                 "build tools listed separately. This inventory is not a legal opinion or audit.",
    }
    save(output, "DEPENDENCIES.json", (json.dumps(manifest, ensure_ascii=False, indent=2) + "\n").encode())
    return manifest


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--source-commit", required=True)
    args = parser.parse_args()
    try:
        result = collect(args.output, args.source_commit)
    except (OSError, ValueError, KeyError, metadata.PackageNotFoundError) as error:
        parser.exit(1, f"Notice collection failed: {error}\n")
    print(f"Collected notices for {len(result['runtime_dependencies'])} runtime distributions, "
          f"CPython, {len(BUILD_TOOLS)} build tools, and exact ASE source.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
