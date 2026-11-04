import csv
import io
from pathlib import Path

from slab_preflight.core import analyze_cif
from slab_preflight.reporting import report_csv


EXAMPLES = Path(__file__).resolve().parents[1] / "examples"


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
