"""Verify the actual release ZIP verifier without executing native binaries."""
from hashlib import sha256
import importlib.util
import json
from pathlib import Path
import zipfile

import pytest

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location("verify_windows_folder", ROOT / ".github/scripts/verify_windows_folder.py")
VERIFY = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(VERIFY)
VERSION = "0.9.1"
TOP = f"CalcLens-{VERSION}-Windows-x64"


def bundle(tmp_path, *, code_version=VERSION, extras=None):
    files = {
        "python.exe": b"interpreter", "pythonw.exe": b"GUI interpreter",
        "python313.dll": b"DLL", "python313.zip": b"stdlib", "desktop_start.py": b"bootstrap",
        "src/slab_preflight/__init__.py": f'__version__ = "{code_version}"\n'.encode(),
        "examples/graphene.cif": b"example original", "docs/README.md": b"guide",
    }
    hashes = {name: sha256(data).hexdigest() for name, data in files.items()}
    sources = {name: value for name, value in hashes.items()
               if name.startswith(("src/", "examples/", "docs/"))}
    source_hash = sha256(json.dumps(sources, sort_keys=True).encode()).hexdigest()
    runtime = {"runtime_architecture": "AMD64"}
    payload = json.dumps({"schema_version": 2, "application_version": VERSION,
                          "distribution": "folder", "runtime": runtime,
                          "source_tree_sha256": source_hash, "files": hashes}).encode()
    archive = tmp_path / f"CalcLens-{VERSION}-Windows-x64-folder.zip"
    launcher = b"native launcher fixture"
    with zipfile.ZipFile(archive, "w") as stream:
        stream.writestr(TOP + "/CalcLens.exe", launcher)
        stream.writestr(TOP + "/START-HERE.txt", "Extract the complete ZIP.")
        stream.writestr(TOP + "/runtime/DESKTOP-BUILD.json", payload)
        for name, data in files.items():
            stream.writestr(TOP + "/runtime/" + name, data)
        for name, data in (extras or {}).items():
            stream.writestr(name, data)
    sidecar = archive.with_suffix(".zip.manifest.json")
    sidecar.write_text(json.dumps({
        "schema_version": 2, "application_version": VERSION, "distribution": "folder",
        "executable": archive.name, "sha256": VERIFY.file_hash(archive), "runtime": runtime,
        "payload_manifest_sha256": sha256(payload).hexdigest(), "source_tree_sha256": source_hash,
        "launcher_sha256": sha256(launcher).hexdigest(),
    }))
    checksums = tmp_path / "SHA256SUMS.txt"
    checksums.write_text("\n".join(f"{VERIFY.file_hash(path)}  {path.name}" for path in (archive, sidecar)) + "\n")
    return archive, sidecar, checksums


def test_exact_release_zip_verifies_hashes_version_and_layout_before_publishing_destination(tmp_path):
    archive, sidecar, checksums = bundle(tmp_path)
    destination = tmp_path / "extracted"
    result = VERIFY.verify_and_extract(archive, sidecar, checksums, VERSION, destination)
    assert result["status"] == "passed" and result["application_version"] == VERSION
    assert result["payload_files_checked"] == 8
    assert Path(result["executable"]).read_bytes() == b"native launcher fixture"
    assert (destination / TOP / "runtime/src/slab_preflight/__init__.py").read_text() == '__version__ = "0.9.1"\n'


@pytest.mark.parametrize("part", ["archive", "sidecar", "duplicate-checksum", "missing-checksum"])
def test_changed_or_ambiguous_release_files_are_rejected_without_extracting(tmp_path, part):
    archive, sidecar, checksums = bundle(tmp_path)
    if part == "archive":
        archive.write_bytes(archive.read_bytes() + b"changed")
    elif part == "sidecar":
        sidecar.write_text(sidecar.read_text() + " ")
    elif part == "duplicate-checksum":
        checksums.write_text(checksums.read_text() + checksums.read_text())
    else:
        checksums.write_text("")
    destination = tmp_path / "extracted"
    with pytest.raises(ValueError, match="checksum"):
        VERIFY.verify_and_extract(archive, sidecar, checksums, VERSION, destination)
    assert not destination.exists()


@pytest.mark.parametrize("member", [
    TOP + "/../outside", TOP + "/runtime/../../outside", "/absolute", "C:/absolute",
    TOP + "/runtime\\outside", TOP + "/runtime/CON.txt", TOP + "/runtime/trailing.",
    TOP + "/runtime/alternate:stream", TOP + "/runtime/PYTHON.EXE",
])
def test_unsafe_windows_archive_paths_cannot_escape_or_alias_existing_files(tmp_path, member):
    archive, sidecar, checksums = bundle(tmp_path, extras={member: b"not safe"})
    destination = tmp_path / "extracted"
    with pytest.raises(ValueError, match="Unsafe|colliding"):
        VERIFY.verify_and_extract(archive, sidecar, checksums, VERSION, destination)
    assert not destination.exists() and not (tmp_path / "outside").exists()


def test_link_entries_and_surplus_executables_are_rejected(tmp_path):
    link = zipfile.ZipInfo(TOP + "/runtime/link")
    link.external_attr = 0o120777 << 16
    archive, sidecar, checksums = bundle(tmp_path, extras={link: b"outside"})
    with pytest.raises(ValueError, match="Unsafe"):
        VERIFY.verify_and_extract(archive, sidecar, checksums, VERSION, tmp_path / "first")
    archive, sidecar, checksums = bundle(tmp_path, extras={TOP + "/surplus.exe": b"extra"})
    with pytest.raises(ValueError, match="layout"):
        VERIFY.verify_and_extract(archive, sidecar, checksums, VERSION, tmp_path / "second")


def test_correct_checksums_cannot_hide_wrong_bundled_application_version(tmp_path):
    archive, sidecar, checksums = bundle(tmp_path, code_version="0.9.0")
    with pytest.raises(ValueError, match="Bundled application version"):
        VERIFY.verify_and_extract(archive, sidecar, checksums, VERSION, tmp_path / "extracted")


def test_existing_extraction_is_not_merged_or_replaced(tmp_path):
    archive, sidecar, checksums = bundle(tmp_path)
    destination = tmp_path / "extracted"
    destination.mkdir()
    (destination / "keep.txt").write_text("existing data")
    with pytest.raises(ValueError, match="must be new"):
        VERIFY.verify_and_extract(archive, sidecar, checksums, VERSION, destination)
    assert (destination / "keep.txt").read_text() == "existing data"
