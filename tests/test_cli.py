"""Exercise report delivery and failure semantics through the installed CLI."""

import json
import csv
import hashlib
from pathlib import Path
import subprocess
import sys

import ase
import pytest

from slab_preflight import __version__
from slab_preflight.reporting import KOREAN_FIELDS


ROOT = Path(__file__).resolve().parents[1]


def run_cli(*args):
    return subprocess.run(
        [sys.executable, "-m", "slab_preflight.cli", *map(str, args)],
        cwd=ROOT, text=True, capture_output=True, check=False,
    )


def test_cli_json_and_atomic_output_contract(tmp_path):
    path = tmp_path / "result.json"
    result = run_cli("examples/graphene.cif", "--json", path)
    assert result.returncode == 0, result.stderr
    data = json.loads(path.read_text())
    assert data["atom_count"] == 2
    assert data["units"]["length"] == "angstrom"
    original = path.read_bytes()
    result = run_cli("examples/mos2.cif", "--json", path)
    assert result.returncode == 2
    assert path.read_bytes() == original


def test_cli_overlap_still_delivers_report_and_nonzero_exit():
    result = run_cli("examples/graphene_duplicate.cif")
    assert result.returncode == 1
    data = json.loads(result.stdout)
    assert data["atom_count"] == 3
    assert any(issue["code"] == "OVERLAPPING_SITES" for issue in data["issues"])


def test_cli_unsupported_does_not_create_report(tmp_path):
    path = tmp_path / "unsupported.json"
    result = run_cli("examples/partial_occupancy.cif", "--json", path)
    assert result.returncode == 2
    assert not path.exists()
    assert "occup" in result.stderr.lower()


def test_cli_missing_file_and_invalid_threshold():
    assert run_cli("examples/does-not-exist.cif").returncode == 2
    assert run_cli("examples/graphene.cif", "--short-distance", "nan").returncode == 2


def test_cli_csv_reports_selected_direction_and_criteria(tmp_path):
    path = tmp_path / "report.csv"
    result = run_cli("examples/mos2.cif", "--normal-axis", "c", "--csv", path)
    assert result.returncode == 0, result.stderr
    with path.open(newline="") as source:
        rows = list(csv.DictReader(source))
    assert any(row["record_type"] == "criterion" for row in rows)
    assert all(row["normal_axis"] == "c" for row in rows)


def test_cli_rejects_unsupported_normal_without_output(tmp_path):
    path = tmp_path / "report.csv"
    result = run_cli("examples/graphene.cif", "--normal-axis", "a", "--csv", path)
    assert result.returncode == 2
    assert not path.exists()


@pytest.mark.parametrize("language", ["en", "ko"])
@pytest.mark.parametrize("format", ["json", "csv"])
def test_cli_delivers_original_file_identity_and_runtime_versions(tmp_path, language, format):
    original = (ROOT / "examples" / "graphene.cif").read_bytes().replace(b"\n", b"\r\n")
    source = tmp_path / "원본 구조.cif"
    source.write_bytes(original)
    target = tmp_path / f"report.{format}"
    result = run_cli(source, "--language", language, f"--{format}", target)
    assert result.returncode == 0, result.stderr
    expected = {
        "original_filename": source.name,
        "sha256": hashlib.sha256(original).hexdigest(),
        "calclens_version": __version__,
        "ase_version": ase.__version__,
    }
    if format == "json":
        assert json.loads(target.read_text(encoding="utf-8"))["provenance"] == expected
    else:
        with target.open(encoding="utf-8-sig", newline="") as stream:
            rows = list(csv.DictReader(stream))
        if language == "ko":
            inverse = {value: key for key, value in KOREAN_FIELDS.items()}
            rows = [{inverse[key]: value for key, value in row.items()} for row in rows]
        assert {row["code"]: row["value"] for row in rows if row["record_type"] == "provenance"} == expected
