"""Portable research sources shared by the native importer and project preview."""

from __future__ import annotations

import base64
from hashlib import sha256
import json
from pathlib import Path
import tempfile

from .density import MAX_CUBE_BYTES, parse_cube
from .native_fields import MAX_CHARGE_BYTES, bounded_read, match_cube, parse_charge
from .project import MAX_WORKSPACE_BYTES
from .research import compare_convergence_series, parse_log

MAX_SOURCE_BUNDLE = 64 * 1024 * 1024


def sources_for(auxiliary, signed, digest):
    aux = auxiliary.get(digest, {"schemaVersion": 1, "charges": [], "volumes": []})
    if (
        not isinstance(aux, dict)
        or aux.get("schemaVersion") != 1
        or not isinstance(aux.get("charges"), list)
        or not isinstance(aux.get("volumes"), list)
        or not isinstance(signed.get(digest, []), list)
    ):
        raise ValueError("Invalid saved electronic data collection.")
    pairs = [("charge", item) for item in aux["charges"]] + [
        ("volume", item) for item in aux["volumes"] + signed.get(digest, [])
    ]
    if len(pairs) > 16:
        raise ValueError("A CIF can hold up to 16 electronic datasets.")
    ids = set()
    total = 0
    for kind, item in pairs:
        if not isinstance(item, dict) or any(
            not isinstance(item.get(k), str) for k in ("id", "name", "filename", "rawText")
        ):
            raise ValueError("Missing electronic source or dataset identity.")
        if (
            not all(0 < len(item[k].strip()) <= 500 for k in ("id", "name", "filename"))
            or item["id"] in ids
        ):
            raise ValueError("Invalid or duplicate electronic dataset identity.")
        ids.add(item["id"])
        count = len(item["rawText"].encode("utf-8"))
        if not 0 < count <= (MAX_CHARGE_BYTES if kind == "charge" else MAX_CUBE_BYTES):
            raise ValueError("Electronic file exceeds its size limit.")
        total += count
    if total > MAX_SOURCE_BUNDLE:
        raise ValueError("Electronic sources for one CIF exceed 64 MiB.")
    return pairs


def evaluate_source(item, kind, report, digest):
    if kind == "charge":
        return parse_charge(item["rawText"].encode(), report, digest)
    if not isinstance(item.get("source"), str) or not 1 <= len(item["source"].strip()) <= 500:
        raise ValueError("A Cube source description is required.")
    if item.get("source_format") == "vasp-chgcar":
        from .chgcar import parse_chgcar

        raw = item["rawText"].encode()
        if (item.get("kind") != "density" or item.get("units") != "e/angstrom^3"
                or sha256(raw).hexdigest() != item.get("source_sha256")):
            raise ValueError("Saved CHGCAR properties or source checksum do not match.")
        return parse_chgcar(raw, report, item["filename"])
    grid = parse_cube(
        item["rawText"],
        kind=item.get("kind"),
        units=item.get("units"),
        source_name=item["filename"],
    )
    match_cube(grid, report)
    return grid


def pack_series(path: Path):
    path = Path(path).resolve()
    result = compare_convergence_series(path)
    manifest = bounded_read(path, 4 * 1024 * 1024)
    files = {"series.json": base64.b64encode(manifest).decode("ascii")}
    total = len(manifest)

    def gather(value):
        nonlocal total
        if isinstance(value, dict):
            if "path" in value and "sha256" in value:
                rel = value["path"]
                src = (path.parent / rel).resolve(strict=True)
                if not src.is_relative_to(path.parent) or rel == "series.json":
                    raise ValueError("Invalid relative series artifact.")
                if rel not in files:
                    data = bounded_read(src, MAX_SOURCE_BUNDLE - total)
                    if sha256(data).hexdigest() != value["sha256"]:
                        raise ValueError("Convergence artifact changed during import.")
                    total += len(data)
                    files[rel] = base64.b64encode(data).decode("ascii")
            else:
                for child in value.values():
                    gather(child)
        elif isinstance(value, list):
            for child in value:
                gather(child)

    gather(json.loads(manifest))
    return {"name": path.name, "files": files}, result


def read_saved_series(bundle):
    if not isinstance(bundle, dict) or not isinstance(bundle.get("files"), dict):
        raise ValueError("Invalid saved convergence series.")
    files = bundle["files"]
    if "series.json" not in files or len(files) > 256:
        raise ValueError("Missing or oversized saved convergence file list.")
    total = 0
    with tempfile.TemporaryDirectory(prefix="calclens-series-") as tmp:
        root = Path(tmp)
        for name, text in files.items():
            if not isinstance(name, str) or len(name) > 240:
                raise ValueError("Invalid convergence archive path.")
            parts = name.split("/")
            reserved = {
                "CON",
                "PRN",
                "AUX",
                "NUL",
                *(f"COM{i}" for i in range(1, 10)),
                *(f"LPT{i}" for i in range(1, 10)),
            }
            if any(
                not part
                or part.endswith((" ", "."))
                or part.split(".")[0].upper() in reserved
                or any(ord(char) < 32 or char in '"<>|?*' for char in part)
                for part in parts
            ):
                raise ValueError("Invalid or nonportable convergence file name.")
            path = Path(name)
            if (
                not path.parts
                or path.is_absolute()
                or ".." in path.parts
                or "\\" in name
                or ":" in name
                or not isinstance(text, str)
                or len(text) > MAX_WORKSPACE_BYTES
            ):
                raise ValueError("Invalid file embedded in convergence series.")
            data = base64.b64decode(text, validate=True)
            total += len(data)
            if total > MAX_SOURCE_BUNDLE:
                raise ValueError("Saved convergence sources exceed 64 MiB.")
            target = root / path
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(data)
        return compare_convergence_series(root / "series.json")


def read_saved_log(record):
    if (
        not isinstance(record, dict)
        or not isinstance(record.get("data"), str)
        or not isinstance(record.get("filename"), str)
        or len(record["filename"]) > 500
        or len(record["data"]) > MAX_WORKSPACE_BYTES
    ):
        raise ValueError("Invalid saved calculation log.")
    raw = base64.b64decode(record["data"], validate=True)
    if sha256(raw).hexdigest() != record.get("sha256"):
        raise ValueError("Saved calculation log checksum differs from the original.")
    return parse_log(raw, source_name=record["filename"])
