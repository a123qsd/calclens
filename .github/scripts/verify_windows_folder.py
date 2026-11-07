"""Validate a published CalcLens folder ZIP before safely extracting its launcher."""
from __future__ import annotations

import argparse
import ast
from hashlib import sha256
import json
from pathlib import Path
import re
import shutil
import stat
import tempfile
import zipfile


MAX_FILES = 20_000
MAX_UNPACKED_BYTES = 2 * 1024**3
MAX_MANIFEST_BYTES = 8 * 1024**2
HASH = re.compile(r"[0-9a-f]{64}")
RESERVED = {"CON", "PRN", "AUX", "NUL", "CONIN$", "CONOUT$"}
RESERVED.update(f"{prefix}{number}" for prefix in ("COM", "LPT") for number in range(1, 10))


def file_hash(path):
    with Path(path).open("rb") as stream:
        return sha256_stream(stream)


def sha256_stream(stream):
    digest = sha256()
    for block in iter(lambda: stream.read(1024 * 1024), b""):
        digest.update(block)
    return digest.hexdigest()


def checked_json(data):
    def unique(pairs):
        result = {}
        for key, value in pairs:
            if key in result:
                raise ValueError("Duplicate manifest field.")
            result[key] = value
        return result

    def reject_constant(value):
        raise ValueError("Manifest contains a non-finite number.")

    if len(data) > MAX_MANIFEST_BYTES:
        raise ValueError("Manifest is too large.")
    value = json.loads(data, object_pairs_hook=unique, parse_constant=reject_constant)
    if not isinstance(value, dict):
        raise ValueError("Manifest must be an object.")
    return value


def verify_checksum(path, checksums):
    matches = []
    for line in checksums.read_text(encoding="utf-8-sig").splitlines():
        if not line.strip():
            continue
        match = re.fullmatch(r"([0-9a-f]{64})  ([^\r\n]+)", line)
        if match is None:
            raise ValueError("Malformed SHA256SUMS line.")
        if match[2] == path.name:
            matches.append(match[1])
    if matches != [file_hash(path)]:
        raise ValueError(f"Missing, duplicate or incorrect checksum for {path.name}.")


def safe_member(info, top):
    name = info.orig_filename
    parts = name.rstrip("/").split("/")
    if (not parts or parts[0] != top or "\\" in name or "\0" in name
            or any(part in ("", ".", "..") or part[-1:] in (".", " ")
                   or any(character in part for character in ':<>"|?*')
                   or part.split(".", 1)[0].upper() in RESERVED for part in parts)
            or stat.S_ISLNK(info.external_attr >> 16) or info.external_attr & 0x400
            or info.flag_bits & 1):
        raise ValueError(f"Unsafe archive member: {name!r}")
    return "/".join(parts)


def verify_and_extract(archive_path, sidecar_path, checksums, version, destination):
    archive_path, sidecar_path = Path(archive_path), Path(sidecar_path)
    checksums, destination = Path(checksums), Path(destination)
    if not re.fullmatch(r"\d+\.\d+\.\d+", version):
        raise ValueError("Unexpected release version.")
    expected_name = f"CalcLens-{version}-Windows-x64-folder.zip"
    if archive_path.name != expected_name or sidecar_path.name != expected_name + ".manifest.json":
        raise ValueError("Release archive/manifest names do not match the version.")
    if destination.exists() or destination.is_symlink():
        raise ValueError("Extraction destination must be new; existing files are never merged.")
    verify_checksum(archive_path, checksums)
    verify_checksum(sidecar_path, checksums)
    sidecar = checked_json(sidecar_path.read_bytes())
    if (sidecar.get("schema_version") != 2 or sidecar.get("application_version") != version
            or sidecar.get("distribution") != "folder"
            or sidecar.get("executable") != expected_name
            or sidecar.get("sha256") != file_hash(archive_path)):
        raise ValueError("Archive identity/version differs from its sidecar.")
    top = f"CalcLens-{version}-Windows-x64"
    with zipfile.ZipFile(archive_path) as archive:
        infos = archive.infolist()
        if len(infos) > MAX_FILES or sum(info.file_size for info in infos) > MAX_UNPACKED_BYTES:
            raise ValueError("Archive exceeds the extraction size/file limit.")
        members = {}
        seen = set()
        for info in infos:
            name = safe_member(info, top)
            if name.casefold() in seen:
                raise ValueError("Archive contains duplicate or case-colliding paths.")
            seen.add(name.casefold())
            if not info.is_dir():
                members[name] = info
        manifest_name = f"{top}/runtime/DESKTOP-BUILD.json"
        if manifest_name not in members or members[manifest_name].file_size > MAX_MANIFEST_BYTES:
            raise ValueError("Missing or oversized payload manifest.")
        manifest_bytes = archive.read(members[manifest_name])
        if sha256(manifest_bytes).hexdigest() != sidecar.get("payload_manifest_sha256"):
            raise ValueError("Payload manifest does not match its sidecar.")
        manifest = checked_json(manifest_bytes)
        if (manifest.get("schema_version") != 2 or manifest.get("application_version") != version
                or manifest.get("distribution") != "folder"
                or manifest.get("runtime", {}).get("runtime_architecture") != "AMD64"
                or manifest.get("runtime") != sidecar.get("runtime")):
            raise ValueError("Payload runtime/version is inconsistent.")
        files = manifest.get("files")
        if (not isinstance(files, dict) or not files
                or any(not isinstance(key, str) or not isinstance(value, str)
                       or HASH.fullmatch(value) is None for key, value in files.items())):
            raise ValueError("Payload file hashes are invalid.")
        required = {"python.exe", "pythonw.exe", "python313.dll", "python313.zip",
                    "desktop_start.py", "src/slab_preflight/__init__.py"}
        if not required <= files.keys():
            raise ValueError("Payload is missing required runtime/application files.")
        expected = {f"{top}/runtime/{name}" for name in files}
        expected.update({manifest_name, f"{top}/CalcLens.exe", f"{top}/START-HERE.txt"})
        if set(members) != expected:
            raise ValueError("Archive files differ from the payload manifest/layout.")
        source_files = {name: value for name, value in files.items()
                        if name.startswith(("src/", "examples/", "docs/"))}
        source_hash = sha256(json.dumps(source_files, sort_keys=True).encode()).hexdigest()
        if source_hash != manifest.get("source_tree_sha256") or source_hash != sidecar.get("source_tree_sha256"):
            raise ValueError("Payload source-tree identity differs from its manifest.")
        code = archive.read(members[f"{top}/runtime/src/slab_preflight/__init__.py"])
        declared = [node.value.value for node in ast.parse(code).body
                    if isinstance(node, ast.Assign) and isinstance(node.value, ast.Constant)
                    and any(isinstance(target, ast.Name) and target.id == "__version__"
                            for target in node.targets)]
        if declared != [version]:
            raise ValueError("Bundled application version differs from the release tag.")
        destination.parent.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory(prefix=".verified-windows-", dir=destination.parent) as temporary:
            staged = Path(temporary) / "bundle"
            staged.mkdir()
            for name, info in members.items():
                target = staged.joinpath(*name.split("/"))
                target.parent.mkdir(parents=True, exist_ok=True)
                with archive.open(info) as source, target.open("wb") as output:
                    shutil.copyfileobj(source, output)
                relative = name.removeprefix(f"{top}/runtime/")
                expected_hash = files.get(relative)
                if name == f"{top}/CalcLens.exe":
                    expected_hash = sidecar.get("launcher_sha256")
                if expected_hash is not None and file_hash(target) != expected_hash:
                    raise ValueError(f"Extracted file hash mismatch: {name}")
            staged.rename(destination)
    executable = destination / top / "CalcLens.exe"
    return {"status": "passed", "application_version": version, "archive": expected_name,
            "archive_sha256": sidecar["sha256"], "payload_files_checked": len(files),
            "source_tree_sha256": source_hash, "executable": str(executable.resolve())}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("archive", "manifest", "checksums", "destination", "report"):
        parser.add_argument("--" + name, required=True, type=Path)
    parser.add_argument("--version", required=True)
    args = parser.parse_args(argv)
    result = verify_and_extract(args.archive, args.manifest, args.checksums,
                                args.version, args.destination)
    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.report.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(result))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
