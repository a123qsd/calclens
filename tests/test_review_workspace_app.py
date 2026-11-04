"""Review state, per-file analysis reuse, and filtered row-to-file mapping."""

import csv
import io
import json

import pytest
from streamlit.delta_generator import DeltaGenerator

from slab_preflight import batch
from test_batch_state import ROOT, Upload, batch_app, select_row


@pytest.fixture
def downloads(monkeypatch):
    """Inspect the delivered files while keeping the real download controls."""
    captured = {}
    original = DeltaGenerator.download_button

    def capture(self, label, data, *args, **kwargs):
        key = kwargs.get("key")
        if key in ("download_batch", "download_report", "download_csv"):
            captured[key] = {"data": data, "file_name": kwargs["file_name"]}
        return original(self, label, data, *args, **kwargs)

    monkeypatch.setattr(DeltaGenerator, "download_button", capture)
    return captured


@pytest.fixture
def analysis_calls(monkeypatch):
    """Count actual geometry analyses, including unsupported inputs."""
    calls = []
    original = batch.analyze_cif

    def capture(data, **kwargs):
        calls.append({"data": data, **kwargs})
        return original(data, **kwargs)

    monkeypatch.setattr(batch, "analyze_cif", capture)
    return calls


def selected_report(downloads):
    return json.loads(downloads["download_report"]["data"])


def comparison_csv(downloads):
    data = downloads["download_batch"]["data"].decode("utf-8-sig")
    return list(csv.DictReader(io.StringIO(data)))


@pytest.mark.parametrize("change", ["remove_first", "reorder"])
def test_identical_upload_ids_keep_surviving_settings_and_selection(
    monkeypatch, downloads, change,
):
    uploads = [Upload("graphene.cif", file_id="first"),
               Upload("graphene.cif", file_id="second"),
               Upload("hbn.cif", file_id="third")]
    at = batch_app(monkeypatch, uploads)
    cutoffs = [widget for widget in at.number_input
               if widget.key.startswith("batch_cutoff_")]
    first_key, second_key = cutoffs[0].key, cutoffs[1].key
    at.number_input(key=first_key).set_value(1.4).run()
    at.number_input(key=second_key).set_value(2.0).run()
    select_row(at, 1)
    assert selected_report(downloads)["short_distance_threshold_angstrom"] == 2.0

    if change == "remove_first":
        uploads.pop(0)
    else:
        uploads[:] = [uploads[2], uploads[1], uploads[0]]
    at.run()

    assert not at.exception
    assert at.number_input(key=second_key).value == 2.0
    report = selected_report(downloads)
    assert report["provenance"]["original_filename"] == "graphene.cif"
    assert report["short_distance_threshold_angstrom"] == 2.0
    expected = [2.0, 1.0] if change == "remove_first" else [1.0, 2.0, 1.4]
    assert list(at.dataframe[0].value["짧은 거리 기준 / Å"]) == expected


def test_display_controls_language_and_selection_reuse_per_file_analysis(
    monkeypatch, analysis_calls,
):
    at = batch_app(monkeypatch, [Upload("graphene.cif"), Upload("mos2.cif"),
                               Upload("partial_occupancy.cif")])
    # Sample mode may also analyze once; measure only changes after batch entry.
    count = len(analysis_calls)
    assert count >= 3

    at.checkbox(key="show_cell").uncheck().run()
    assert not at.exception
    assert len(analysis_calls) == count
    at.selectbox(key="repeats").set_value(3).run()
    assert not at.exception
    assert len(analysis_calls) == count
    select_row(at, 1)
    assert at.metric[1].value == "3.120 Å"
    assert len(analysis_calls) == count
    at.selectbox(key="language").set_value("English").run()
    assert not at.exception
    assert len(analysis_calls) == count
    select_row(at, 2)
    assert not at.metric
    assert len(analysis_calls) == count
    select_row(at, 0)
    assert at.metric[0].value == "1.420 Å"
    assert len(analysis_calls) == count


@pytest.mark.parametrize("change", ["cutoff", "bytes"])
def test_only_the_changed_file_is_reanalyzed(monkeypatch, analysis_calls, change):
    uploads = [Upload("graphene.cif", file_id="graphene"),
               Upload("mos2.cif", file_id="mos2")]
    at = batch_app(monkeypatch, uploads)
    count = len(analysis_calls)
    cutoffs = [widget for widget in at.number_input
               if widget.key.startswith("batch_cutoff_")]
    second_key = cutoffs[1].key
    select_row(at, 1)
    assert len(analysis_calls) == count

    if change == "cutoff":
        at.number_input(key=second_key).set_value(2.5).run()
    else:
        # Keep the upload's identity while changing its exact original bytes.
        uploads[1].data += b"\n# edited without replacing this upload\n"
        at.run()

    assert not at.exception
    assert len(analysis_calls) == count + 1
    assert analysis_calls[-1]["data"] == uploads[1].data
    assert analysis_calls[-1]["short_distance"] == (2.5 if change == "cutoff" else 1.0)
    assert at.metric[1].value == "3.120 Å"
    assert at.number_input(key=second_key).value == (2.5 if change == "cutoff" else 1.0)


def test_same_bytes_with_different_names_keep_selected_export_identity(
    monkeypatch, downloads, analysis_calls,
):
    data = (ROOT / "examples" / "graphene.cif").read_bytes()
    uploads = [Upload("first.cif", data, "first"), Upload("second.cif", data, "second")]
    at = batch_app(monkeypatch, uploads)
    count = len(analysis_calls)
    for index, name in ((0, "first.cif"), (1, "second.cif"), (0, "first.cif")):
        select_row(at, index)
        assert selected_report(downloads)["provenance"]["original_filename"] == name
        assert downloads["download_report"]["file_name"] == name.replace(
            ".cif", "_calclens_ko.json"
        )
        assert len(analysis_calls) == count
    rows = comparison_csv(downloads)
    assert [row["파일명"] for row in rows] == ["first.cif", "second.cif"]
    assert rows[0]["SHA-256"] == rows[1]["SHA-256"]


def test_filters_map_visible_rows_to_original_files_and_export_all_inputs(
    monkeypatch, downloads, analysis_calls,
):
    uploads = [Upload("graphene.cif"), Upload("partial_occupancy.cif"),
               Upload("graphene_duplicate.cif"), Upload("mos2.cif"),
               Upload("tiny_self_image.cif")]
    at = batch_app(monkeypatch, uploads)
    count = len(analysis_calls)
    at.radio(key="batch_filter_ko").set_value("needs_review").run()
    assert not at.exception
    assert list(at.dataframe[0].value["파일명"]) == [
        "graphene_duplicate.cif", "tiny_self_image.cif",
    ]
    select_row(at, 1)  # Visible row 1 is original input 4, not input 1.
    assert at.metric[0].value == "0.500 Å"
    assert selected_report(downloads)["provenance"]["original_filename"] == (
        "tiny_self_image.cif"
    )
    select_row(at, 0)
    assert at.metric[0].value == "0.000 Å"
    assert selected_report(downloads)["provenance"]["original_filename"] == (
        "graphene_duplicate.cif"
    )
    assert len(comparison_csv(downloads)) == 5
    assert len(analysis_calls) == count

    for language, widget_key, filename_column in (
        ("English", "batch_filter_en", "filename"),
        ("한국어", "batch_filter_ko", "파일명"),
    ):
        at.selectbox(key="language").set_value(language).run()
        assert not at.exception
        assert at.radio(key=widget_key).value == "needs_review"
        assert at.session_state["batch_filter"] == "needs_review"
        assert list(at.dataframe[0].value[filename_column]) == [
            "graphene_duplicate.cif", "tiny_self_image.cif",
        ]
        assert at.metric[0].value == "0.000 Å"
        assert len(analysis_calls) == count

    at.radio(key="batch_filter_ko").set_value("unsupported").run()
    assert not at.exception
    assert list(at.dataframe[0].value["파일명"]) == ["partial_occupancy.cif"]
    select_row(at, 0)
    assert not at.metric
    assert "partial_occupancy.cif" in at.error[0].value
    assert len(comparison_csv(downloads)) == 5
    assert len(analysis_calls) == count


@pytest.mark.parametrize("filter_value", ["needs_review", "unsupported"])
def test_empty_filter_clears_previous_detail_but_exports_every_file(
    monkeypatch, downloads, filter_value,
):
    at = batch_app(monkeypatch, [Upload("graphene.cif"), Upload("mos2.cif")])
    select_row(at, 1)
    assert at.metric[1].value == "3.120 Å"

    at.radio(key="batch_filter_ko").set_value(filter_value).run()

    assert not at.exception
    assert not at.metric
    assert not at.get("plotly_chart")
    assert at.info
    assert len(comparison_csv(downloads)) == 2
    # Rendering no table at all is also a valid empty state.
    assert not at.dataframe or at.dataframe[0].value.empty
