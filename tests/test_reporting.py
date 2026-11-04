import csv
import io
from pathlib import Path
import runpy

import pytest

from slab_preflight.core import analyze_cif
from slab_preflight.reporting import KOREAN_FIELDS, report_csv


EXAMPLES = Path(__file__).resolve().parents[1] / "examples"
make_cif = runpy.run_path(str(EXAMPLES.parent / "scripts" / "generate_examples.py"))["cif"]


def test_csv_preserves_criteria_elements_and_periodic_image():
    report = analyze_cif((EXAMPLES / "graphene_boundary_duplicate.cif").read_bytes())
    rows = list(csv.DictReader(io.StringIO(report_csv(report))))
    contact = next(row for row in rows if row["record_type"] == "contact")
    assert contact["element_i"] == contact["element_j"] == "C"
    assert float(contact["value"]) < 1e-5
    assert int(contact["site_i"]) >= 1
    assert contact["short_distance_threshold_angstrom"] == "1.0"
    assert contact["normal_axis"] == "c"
    assert any(row["code"] == "short_distance_threshold_angstrom" for row in rows)
    assert any(row["code"] == "OVERLAPPING_SITES" for row in rows)
    assert any("convergence" in row["note"] for row in rows)


def test_csv_text_cannot_be_interpreted_as_a_spreadsheet_formula():
    report = analyze_cif((EXAMPLES / "graphene.cif").read_bytes())
    report["issues"].append({"code": "CUSTOM_NOTE", "severity": "info",
                            "message": '=HYPERLINK("https://example.invalid", "click")'})
    rows = list(csv.DictReader(io.StringIO(report_csv(report))))
    note = next(row["note"] for row in rows if row["code"] == "CUSTOM_NOTE")
    assert note.startswith("'=HYPERLINK")


def canonical_rows(report, language):
    rows = list(csv.DictReader(io.StringIO(report_csv(report, language))))
    if language == "ko":
        inverse = {value: key for key, value in KOREAN_FIELDS.items()}
        return [{inverse[key]: value for key, value in row.items()} for row in rows]
    return rows


def assert_csv_pair(row, contact):
    assert float(row["value"]) == contact["distance_angstrom"]
    assert row["unit"] == "angstrom"
    assert int(row["site_i"]) == contact["i"] + 1
    assert int(row["site_j"]) == contact["j"] + 1
    assert row["element_i"] == contact["element_i"]
    assert row["element_j"] == contact["element_j"]
    assert [int(row[f"image_shift_{axis}"]) for axis in "abc"] == contact["shift"]


@pytest.mark.parametrize("language", ["en", "ko"])
@pytest.mark.parametrize("example", ["graphene.cif", "tiny_self_image.cif"])
def test_csv_keeps_minimum_pair_above_short_contact_cutoff(language, example):
    report = analyze_cif((EXAMPLES / example).read_bytes(), short_distance=0.1)
    assert report["short_contacts"] == []
    rows = canonical_rows(report, language)
    minimum = next(row for row in rows if row["code"] == "minimum_pair")
    assert minimum["record_type"] == "metric"
    assert_csv_pair(minimum, report["metrics"]["minimum_pair"])
    assert minimum["note"]


@pytest.mark.parametrize("language", ["en", "ko"])
def test_csv_keeps_issue_counts_and_evidence_beyond_contact_table_limit(language):
    atoms = [("C", 0, 0, 0.5, 1)] * 30
    report = analyze_cif(make_cif("dense", (0.5, 10, 20, 90, 90, 90), atoms))
    assert report["short_contacts_truncated"] is True
    rows = canonical_rows(report, language)
    issues = {issue["code"]: issue for issue in report["issues"] if "contact_count" in issue}
    assert issues.keys() == {"OVERLAPPING_SITES", "SHORT_DISTANCE", "SELF_IMAGE_CONTACT"}
    for code, issue in issues.items():
        summary = next(row for row in rows if row["record_type"] == "issue" and row["code"] == code)
        assert int(summary["value"]) == issue["contact_count"]
        assert summary["unit"] == ("sites" if code == "SELF_IMAGE_CONTACT" else "pairs")
        evidence = next(row for row in rows if row["record_type"] == "issue_contact" and row["code"] == code)
        assert_csv_pair(evidence, issue["representative_contact"])
        assert evidence["severity"] == issue["severity"]
