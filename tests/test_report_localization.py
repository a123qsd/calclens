"""Result-language choices preserve the scientific report and its dynamic evidence."""

from copy import deepcopy
import csv
import io
import json
from pathlib import Path
import runpy
import subprocess
import sys

import pytest

from slab_preflight import UnsupportedStructure, analyze_cif
from slab_preflight.reporting import (
    FIELDS, KOREAN_FIELDS, localized_error_message, localized_issue_message,
    localized_report, report_csv,
)


ROOT = Path(__file__).resolve().parents[1]
make_cif = runpy.run_path(str(ROOT / "scripts" / "generate_examples.py"))["cif"]


def load(name):
    return (ROOT / "examples" / name).read_text(encoding="utf-8")


def cli(*args):
    return subprocess.run([sys.executable, "-m", "slab_preflight.cli", *map(str, args)],
                          cwd=ROOT, capture_output=True, text=True, check=False)


def has_korean(text):
    return any("가" <= char <= "힣" for char in text)


@pytest.mark.parametrize("message", [
    "Repeated CIF tag aliases are ambiguous and unsupported.",
    "Occupancy, disorder, and multiplicity must be site-loop columns matching the site count.",
    "Declared site multiplicity disagrees with symmetry expansion.",
    "Unsupported occupancy, disorder, or multiplicity CIF tag: _atom_site.occupancy_value.",
])
def test_cif_alias_failures_have_specific_korean_explanations(message):
    translated = localized_error_message(message, "ko")
    assert has_korean(translated)
    assert "원문:" not in translated
    assert localized_error_message(message, "en") == message
    if "_atom_site" in message:
        assert "_atom_site.occupancy_value" in translated


def missing_occupancy():
    return "\n".join(
        line.rsplit(" ", 1)[0] if line.startswith(("C1 ", "C2 ")) else line
        for line in load("graphene.cif").splitlines() if line != "_atom_site_occupancy"
    ) + "\n"


def test_all_core_diagnoses_translate_without_losing_source_or_evidence():
    texts = [load(name) for name in (
        "graphene_duplicate.cif", "tiny_self_image.cif", "no_unique_gap.cif", "bilayer_graphene.cif",
    )] + [missing_occupancy()]
    seen = set()
    for text in texts:
        original = analyze_cif(text)
        localized = localized_report(original, "ko")
        assert localized["report_language"] == "ko"
        for key in original.keys() - {"issues", "assumptions", "limitations"}:
            assert localized[key] == original[key]
        for source, translated in zip(original["issues"], localized["issues"]):
            seen.add(source["code"])
            assert translated["message_en"] == source["message"]
            assert has_korean(translated["message"])
            assert not translated["message"].startswith("추가 진단")
            assert {k: v for k, v in translated.items() if k not in ("message", "message_en")} == {
                k: v for k, v in source.items() if k != "message"
            }
        for kind in ("assumptions", "limitations"):
            assert localized[f"{kind}_en"] == original[kind]
            assert all(has_korean(note) and not note.startswith("추가 설명") for note in localized[kind])
    assert seen == {"OVERLAPPING_SITES", "SHORT_DISTANCE", "SELF_IMAGE_CONTACT", "AMBIGUOUS_SLAB",
                    "MULTIPLE_LARGE_GAPS", "ASSUMED_FULL_OCCUPANCY", "GEOMETRY_ONLY", "VACUUM_CONVERGENCE"}


def test_translation_retains_full_pair_counts_and_custom_cutoff_after_table_truncation():
    text = make_cif("many", (10, 10, 20, 90, 90, 90), [("C", 0, 0, 0.5, 1)] * 30)
    original = analyze_cif(text, short_distance=0.37)
    assert len(original["short_contacts"]) == 200
    assert original["short_contact_count"] == 435
    translated = localized_report(original, "ko")
    issues = {item["code"]: item for item in translated["issues"]}
    assert "435쌍" in issues["SHORT_DISTANCE"]["message"]
    assert "0.37 Å" in issues["SHORT_DISTANCE"]["message"]
    assert "435쌍" in issues["OVERLAPPING_SITES"]["message"]
    assert "1e-05 Å" in issues["OVERLAPPING_SITES"]["message"]
    assert issues["OVERLAPPING_SITES"]["atom_indices"] == list(range(30))


def test_dynamic_self_image_distance_and_missing_occupancy_count():
    report = analyze_cif(load("tiny_self_image.cif"))
    issue = next(item for item in report["issues"] if item["code"] == "SELF_IMAGE_CONTACT")
    translated = localized_issue_message(issue, report, "ko")
    assert "1개" in translated and "0.5 Å" in translated
    report = localized_report(analyze_cif(missing_occupancy()), "ko")
    issue = next(item for item in report["issues"] if item["code"] == "ASSUMED_FULL_OCCUPANCY")
    assert "2개" in issue["message"] and "점유율 1" in issue["message"]


def test_selected_axis_and_measured_gap_values_survive_translation():
    text = make_cif("bilayer_b", (3, 20, 3, 90, 90, 90), [("C", 0, 0.3, 0, 1), ("C", 0, 0.7, 0, 1)])
    report = localized_report(analyze_cif(text, normal_axis="b"), "ko")
    issue = next(item for item in report["issues"] if item["code"] == "MULTIPLE_LARGE_GAPS")
    assert all(token in issue["message"] for token in ("b축", "12 Å", "8 Å", "3 Å", "50%"))
    assert "b축은 a-c 평면에 수직" in report["assumptions"][1]
    assert "선택한 수직축과 관계없이" in report["field_descriptions"]["metrics"]["c_height_angstrom"]


def test_reports_are_deep_copied_and_can_return_to_english():
    original = analyze_cif(load("graphene_duplicate.cif"))
    snapshot = deepcopy(original)
    korean = localized_report(original, "ko")
    assert original == snapshot
    assert localized_report(korean, "ko") == korean
    english = localized_report(korean, "en")
    for key in original:
        assert english[key] == original[key]
    assert english["report_language"] == "en"
    assert "assumptions_en" not in english
    assert all("message_en" not in item for item in english["issues"])
    korean["positions"][0][0] = 999
    korean["issues"][0]["atom_indices"].append(999)
    assert original == snapshot


def test_korean_csv_preserves_machine_codes_values_units_and_has_human_definitions():
    report = analyze_cif(load("graphene_boundary_duplicate.cif"), short_distance=0.8)
    english_text, korean_text = report_csv(report), report_csv(report, "ko")
    assert not korean_text.startswith("\ufeff")  # Encoders at delivery boundaries add the BOM.
    english = list(csv.DictReader(io.StringIO(english_text)))
    korean = list(csv.DictReader(io.StringIO(korean_text)))
    assert list(english[0]) == FIELDS
    assert list(korean[0]) == [KOREAN_FIELDS[field] for field in FIELDS]
    inverse_headers = {value: key for key, value in KOREAN_FIELDS.items()}
    korean = [{inverse_headers[key]: value for key, value in row.items()} for row in korean]
    assert len(english) == len(korean)
    for en, ko in zip(english, korean):
        ignored = {"note", "value"} if en["code"] == "report_language" else {"note"}
        assert {k: v for k, v in en.items() if k not in ignored} == {k: v for k, v in ko.items() if k not in ignored}
        if en["record_type"] in ("metric", "criterion", "issue", "assumption", "limitation"):
            assert has_korean(ko["note"])
    assert korean[0]["code"] == "report_language" and korean[0]["value"] == "ko"
    assert next(row for row in korean if row["code"] == "short_distance_comparison")["value"] == "<"
    assert next(row for row in korean if row["code"] == "overlap_comparison")["value"] == "<="
    assert any("CSV 원자 번호는 1" in row["note"] for row in korean)


def test_unknown_diagnostics_keep_original_details_and_csv_formulas_stay_inert():
    report = analyze_cif(load("graphene.cif"))
    original = '=HYPERLINK("https://example.invalid", "detail 123")'
    report["issues"].append({"code": "FUTURE_DIAGNOSTIC", "severity": "info", "message": original})
    translated = localized_report(report, "ko")["issues"][-1]
    assert translated["message_en"] == original
    assert original in translated["message"]
    for language, note_key, code_key in (("en", "note", "code"), ("ko", "설명", "코드")):
        rows = list(csv.DictReader(io.StringIO(report_csv(report, language))))
        note = next(row[note_key] for row in rows if row[code_key] == "FUTURE_DIAGNOSTIC")
        assert not note.lstrip().startswith(("=", "+", "-", "@"))


@pytest.mark.parametrize("language", ["ja", "", None, 12])
def test_unsupported_language_is_not_silently_substituted(language):
    report = analyze_cif(load("graphene.cif"))
    with pytest.raises(ValueError, match="language"):
        localized_report(report, language)
    with pytest.raises(ValueError, match="language"):
        report_csv(report, language)


@pytest.mark.parametrize("name", ["partial_occupancy.cif", "symmetry_unsupported.cif", "tilted_c.cif", "multiple_blocks.cif"])
def test_real_unsupported_input_reasons_are_translated(name):
    with pytest.raises(UnsupportedStructure) as exc:
        analyze_cif(load(name))
    original = str(exc.value)
    assert localized_error_message(original) == original
    translated = localized_error_message(original, "ko")
    assert has_korean(translated)
    assert "원문:" not in translated
    if name == "partial_occupancy.cif":
        assert "점유율 1" in translated and "부분 점유" in translated
    if name == "tilted_c.cif":
        assert all(token in translated for token in ("c축", "a축", "b축", "90도"))


def test_finite_number_failure_preserves_the_affected_parameter():
    with pytest.raises(UnsupportedStructure) as exc:
        analyze_cif(load("graphene.cif"), short_distance=float("nan"))
    assert localized_error_message(str(exc.value), "ko") == "짧은 거리 기준 값은 유한한 숫자여야 합니다."


def test_cli_language_changes_delivery_not_analysis_or_exit_status(tmp_path):
    en_path, ko_path = tmp_path / "en.json", tmp_path / "ko.json"
    english = cli("examples/graphene_duplicate.cif", "--short-distance", "1.25", "--json", en_path)
    korean = cli("examples/graphene_duplicate.cif", "--short-distance", "1.25", "--language", "ko", "--json", ko_path)
    assert english.returncode == korean.returncode == 1
    en, ko = json.loads(en_path.read_text()), json.loads(ko_path.read_text())
    assert not ko_path.read_bytes().startswith(b"\xef\xbb\xbf")
    assert en["report_language"] == "en" and ko["report_language"] == "ko"
    for key in ("metrics", "criteria", "positions", "cell", "review_required", "gap_review_required", "short_contacts"):
        assert en[key] == ko[key]
    short = next(item for item in ko["issues"] if item["code"] == "SHORT_DISTANCE")
    assert "1.25 Å" in short["message"] and short["message_en"].startswith("1 distinct")


def test_cli_korean_csv_has_excel_bom_and_never_overwrites(tmp_path):
    path = tmp_path / "report.csv"
    first = cli("examples/graphene.cif", "--language", "ko", "--csv", path)
    assert first.returncode == 0, first.stderr
    contents = path.read_bytes()
    assert contents.startswith(b"\xef\xbb\xbf")
    rows = list(csv.DictReader(io.StringIO(contents.decode("utf-8-sig"))))
    assert rows[0]["코드"] == "report_language" and rows[0]["값"] == "ko"
    assert any("수렴" in row["설명"] for row in rows)
    assert cli("examples/mos2.cif", "--language", "ko", "--csv", path).returncode == 2
    assert path.read_bytes() == contents


def test_cli_korean_unsupported_input_still_creates_no_result(tmp_path):
    path = tmp_path / "unsupported.json"
    result = cli("examples/partial_occupancy.cif", "--language", "ko", "--json", path)
    assert result.returncode == 2
    assert "부분 점유" in result.stderr
    assert not path.exists()
