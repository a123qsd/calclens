"""File identity must survive parsing, localization, and portable report delivery."""

from copy import deepcopy
import csv
import hashlib
import io
from pathlib import Path
import tomllib

import ase
import pytest

from slab_preflight import __version__, analyze_cif
from slab_preflight.provenance import with_provenance
from slab_preflight.reporting import KOREAN_FIELDS, localized_report, report_csv


ROOT = Path(__file__).resolve().parents[1]


def test_provenance_hashes_original_bytes_and_copies_the_report():
    original = (ROOT / "examples" / "graphene.cif").read_bytes().replace(b"\n", b"\r\n")
    report = analyze_cif(original)
    snapshot = deepcopy(report)
    result = with_provenance(report, original, "원본 구조.cif")
    expected = {
        "original_filename": "원본 구조.cif",
        "sha256": hashlib.sha256(original).hexdigest(),
        "calclens_version": __version__,
        "ase_version": ase.__version__,
    }
    assert result["provenance"] == expected
    assert expected["sha256"] != hashlib.sha256(original.replace(b"\r\n", b"\n")).hexdigest()
    assert report == snapshot and "provenance" not in report
    result["positions"][0][0] = 999
    assert report == snapshot
    assert localized_report(result, "ko")["provenance"] == expected


def test_reported_calclens_version_matches_package_metadata():
    project = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    assert __version__ == project["project"]["version"]


@pytest.mark.parametrize("data", ["normalized text", bytearray(b"bytes"), None])
def test_provenance_requires_original_bytes_instead_of_reencoding(data):
    with pytest.raises(TypeError, match="original input bytes"):
        with_provenance({}, data, "example.cif")


@pytest.mark.parametrize("language", ["en", "ko"])
def test_csv_preserves_provenance_and_escapes_formula_like_filenames(language):
    original = (ROOT / "examples" / "graphene.cif").read_bytes()
    report = with_provenance(analyze_cif(original), original, "=1+1.cif")
    rows = list(csv.DictReader(io.StringIO(report_csv(report, language))))
    if language == "ko":
        inverse = {value: key for key, value in KOREAN_FIELDS.items()}
        rows = [{inverse[key]: value for key, value in row.items()} for row in rows]
    provenance = {row["code"]: row for row in rows if row["record_type"] == "provenance"}
    assert provenance.keys() == report["provenance"].keys()
    assert provenance["original_filename"]["value"] == "'=1+1.cif"
    assert report["provenance"]["original_filename"] == "=1+1.cif"
    for key in ("sha256", "calclens_version", "ase_version"):
        assert provenance[key]["value"] == report["provenance"][key]
    assert all(row["note"] for row in provenance.values())
    if language == "ko":
        assert all(any("가" <= char <= "힣" for char in row["note"]) for row in provenance.values())
