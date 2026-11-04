"""Save and reopen portable review work through the actual Streamlit controls."""

from dataclasses import replace
import hashlib
import json

import ase
import pytest
import streamlit as st
from streamlit.delta_generator import DeltaGenerator
from streamlit.testing.v1 import AppTest

from slab_preflight import __version__, batch
from slab_preflight.project import Project, ProjectEntry, dumps_project, loads_project
from test_batch_state import ROOT, Upload, select_row


@pytest.fixture
def upload_state(monkeypatch):
    """Provide uploads without replacing their downstream parsing or UI logic."""
    state = {"batch_upload": [], "project_upload": None}
    monkeypatch.setenv("CALCLENS_LANGUAGE", "ko")
    monkeypatch.setattr(st, "file_uploader", lambda *args, **kwargs: state.get(kwargs.get("key")))
    return state


@pytest.fixture
def downloads(monkeypatch):
    captured = {}
    original = DeltaGenerator.download_button

    def capture(self, label, data, *args, **kwargs):
        key = kwargs.get("key")
        if key in ("download_project", "download_batch", "download_report", "download_csv"):
            captured[key] = {"data": data, "file_name": kwargs["file_name"]}
        return original(self, label, data, *args, **kwargs)

    monkeypatch.setattr(DeltaGenerator, "download_button", capture)
    return captured


def new_app(source="project"):
    at = AppTest.from_file(str(ROOT / "streamlit_app.py"), default_timeout=30).run()
    at.radio(key="source_ko").set_value(source).run()
    assert not at.exception
    return at


def note_widget(at):
    return next(widget for widget in at.text_area if widget.key.startswith("review_note_"))


def done_widget(at):
    return next(widget for widget in at.checkbox if widget.key.startswith("review_done_"))


def focus_widget(at):
    return next(widget for widget in at.radio if widget.key.startswith("review_focus_"))


def project_download(downloads):
    assert downloads["download_project"]["file_name"].endswith(".calclens.json")
    return loads_project(downloads["download_project"]["data"])


def example_bytes(name):
    return (ROOT / "examples" / name).read_bytes()


def saved_project():
    return Project(
        [
            ProjectEntry("first", "graphene.cif", example_bytes("graphene.cif")),
            ProjectEntry("second", "mos2.cif", example_bytes("mos2.cif"), short_distance=2.5,
                         note="저장한 메모\n원본 확인", reviewed=True),
        ],
        selected_id="second", review_focus="minimum",
    )


def open_project(at):
    at.button(key="load_project").click().run()
    assert not at.exception
    return at


def test_batch_save_reopens_fresh_with_raw_bytes_failures_duplicates_and_review_state(
    upload_state, downloads, monkeypatch,
):
    originals = [
        example_bytes("graphene.cif").replace(b"\n", b"\r\n"),
        example_bytes("mos2_a_normal.cif") + b"\n# original upload bytes\n",
        example_bytes("partial_occupancy.cif"),
    ]
    upload_state["batch_upload"] = [
        Upload("same.cif", originals[0], "first"),
        Upload("same.cif", originals[1], "second"),
        Upload("partial_occupancy.cif", originals[2], "failed"),
    ]
    at = new_app("batch")
    cutoffs = [widget for widget in at.number_input if widget.key.startswith("batch_cutoff_")]
    cutoffs[0].set_value(1.7).run()
    note_widget(at).set_value("첫 번째 검토").run()
    done_widget(at).check().run()
    axes = [widget for widget in at.selectbox if widget.key.startswith("batch_axis_")]
    axes[1].set_value("a").run()
    cutoffs = [widget for widget in at.number_input if widget.key.startswith("batch_cutoff_")]
    cutoffs[1].set_value(2.5).run()
    select_row(at, 1)
    note_widget(at).set_value("두 번째 검토\n층 방향 확인").run()
    done_widget(at).check().run()
    focus_widget(at).set_value("short").run()
    at.radio(key="batch_filter_ko").set_value("needs_review").run()
    assert not at.exception
    saved = project_download(downloads)
    assert [entry.data for entry in saved.entries] == originals
    assert [entry.filename for entry in saved.entries] == [
        "same.cif", "same.cif", "partial_occupancy.cif",
    ]
    assert len({entry.id for entry in saved.entries}) == 3
    assert [entry.reviewed for entry in saved.entries] == [True, True, False]
    assert saved.selected_id == saved.entries[1].id
    assert saved.filter_mode == "needs_review" and saved.review_focus == "short"

    analyses = []
    analyze = batch.analyze_cif

    def capture(data, **kwargs):
        analyses.append(data)
        return analyze(data, **kwargs)

    monkeypatch.setattr(batch, "analyze_cif", capture)
    upload_state["project_upload"] = Upload(
        "portable.calclens.json", downloads["download_project"]["data"]
    )
    reopened = new_app()
    assert "project_entries" not in reopened.session_state
    assert not reopened.metric
    assert not reopened.button(key="load_project").disabled
    open_project(reopened)

    assert analyses == originals
    assert project_download(downloads) == saved
    assert reopened.session_state["project_selected_id"] == saved.selected_id
    assert reopened.radio(key="batch_filter_ko").value == "needs_review"
    assert focus_widget(reopened).value == "short"
    assert note_widget(reopened).value == "두 번째 검토\n층 방향 확인"
    assert done_widget(reopened).value is True
    assert reopened.metric[1].value == "3.120 Å"
    assert list(reopened.dataframe[0].value["파일명"]) == ["same.cif", "same.cif"]
    report = json.loads(downloads["download_report"]["data"])
    assert report["normal_axis"] == "a"
    assert report["short_distance_threshold_angstrom"] == 2.5
    assert report["provenance"]["original_filename"] == "same.cif"
    assert report["provenance"]["sha256"] == hashlib.sha256(originals[1]).hexdigest()
    assert [entry.note for entry in saved.entries] == [
        "첫 번째 검토", "두 번째 검토\n층 방향 확인", "",
    ]


def test_project_upload_restores_state_only_when_open_is_clicked(upload_state, downloads):
    at = new_app()
    assert at.button(key="load_project").disabled
    assert "project_entries" not in at.session_state
    first = saved_project()
    upload_state["project_upload"] = Upload("first.calclens.json", dumps_project(first))
    at.run()
    assert not at.exception
    assert not at.button(key="load_project").disabled
    assert "project_entries" not in at.session_state
    assert not at.metric
    open_project(at)
    assert project_download(downloads) == first

    replacement = replace(first, entries=[replace(first.entries[0], note="새 작업")],
                          selected_id="first", review_focus="gap", filter_mode="all")
    upload_state["project_upload"] = Upload("replacement.calclens.json", dumps_project(replacement))
    at.run()
    assert not at.exception
    assert project_download(downloads) == first
    assert note_widget(at).value == first.entries[1].note
    open_project(at)
    assert project_download(downloads) == replacement
    assert note_widget(at).value == "새 작업"


@pytest.mark.parametrize("damage", ["json", "payload", "schema"])
def test_invalid_project_keeps_the_existing_work_intact(upload_state, downloads, damage):
    saved = saved_project()
    upload_state["project_upload"] = Upload("saved.calclens.json", dumps_project(saved))
    at = open_project(new_app())
    generation = at.session_state["project_generation"]
    if damage == "json":
        corrupted = b"not JSON"
    else:
        document = json.loads(dumps_project(saved))
        if damage == "payload":
            document["entries"][0]["cif_base64"] = "dGFtcGVyZWQ="
        else:
            document["schema_version"] = 999
        corrupted = json.dumps(document).encode()
    upload_state["project_upload"] = Upload("broken.calclens.json", corrupted)
    at.run()
    open_project(at)

    assert any("작업 파일을 열 수 없습니다" in error.value for error in at.error)
    assert at.session_state["project_generation"] == generation
    assert project_download(downloads) == saved
    assert note_widget(at).value == saved.entries[1].note
    assert done_widget(at).value is True
    assert at.metric[1].value == "3.120 Å"


def test_opening_the_same_file_again_restores_saved_conditions_selection_and_notes(
    upload_state, downloads,
):
    saved = saved_project()
    upload_state["project_upload"] = Upload("saved.calclens.json", dumps_project(saved))
    at = open_project(new_app())
    cutoff = [widget for widget in at.number_input if widget.key.startswith("batch_cutoff_")][1]
    cutoff.set_value(1.5).run()
    note_widget(at).set_value("아직 저장하지 않은 수정").run()
    focus_widget(at).set_value("gap").run()
    select_row(at, 0)
    at.radio(key="batch_filter_ko").set_value("unsupported").run()
    assert not at.metric
    assert project_download(downloads) != saved

    open_project(at)

    assert project_download(downloads) == saved
    assert at.session_state["project_selected_id"] == "second"
    assert note_widget(at).value == saved.entries[1].note
    assert done_widget(at).value is True
    assert at.radio(key="batch_filter_ko").value == "all"
    assert focus_widget(at).value == "minimum"
    cutoff = [widget for widget in at.number_input if widget.key.startswith("batch_cutoff_")][1]
    assert cutoff.value == 2.5
    assert at.metric[1].value == "3.120 Å"


def test_old_engine_versions_warn_and_current_results_and_versions_are_exported(
    upload_state, downloads,
):
    saved = replace(saved_project(), calclens_version="0.0.1", ase_version="3.0.0")
    upload_state["project_upload"] = Upload("old.calclens.json", dumps_project(saved))
    at = open_project(new_app())
    warnings = "\n".join(item.value for item in at.warning)
    assert "저장 당시 버전" in warnings
    assert "CalcLens 0.0.1" in warnings and "ASE 3.0.0" in warnings
    assert f"CalcLens {__version__}" in warnings and f"ASE {ase.__version__}" in warnings
    report = json.loads(downloads["download_report"]["data"])
    assert report["provenance"]["calclens_version"] == __version__
    assert report["provenance"]["ase_version"] == ase.__version__
    resaved = project_download(downloads)
    assert resaved.calclens_version == __version__
    assert resaved.ase_version == ase.__version__
    assert resaved.entries == saved.entries


def test_selected_failed_file_can_save_notes_and_progress_without_stale_measurements(
    upload_state, downloads,
):
    saved = Project(
        [ProjectEntry("good", "graphene.cif", example_bytes("graphene.cif")),
         ProjectEntry("failed", "partial_occupancy.cif", example_bytes("partial_occupancy.cif"))],
        selected_id="failed", filter_mode="unsupported", review_focus="metadata",
    )
    upload_state["project_upload"] = Upload("failed.calclens.json", dumps_project(saved))
    at = new_app()
    downloads.clear()
    open_project(at)
    note_widget(at).set_value("부분 점유를 확인해야 함").run()
    done_widget(at).check().run()

    assert not at.exception
    assert not at.metric
    assert not at.get("plotly_chart")
    assert "download_report" not in downloads
    assert "download_csv" not in downloads
    assert "download_batch" in downloads
    assert "partial_occupancy.cif" in at.error[0].value
    resaved = project_download(downloads)
    assert len(resaved.entries) == 2
    assert resaved.entries[1].data == saved.entries[1].data
    assert resaved.entries[1].note == "부분 점유를 확인해야 함"
    assert resaved.entries[1].reviewed is True
    assert resaved.selected_id == "failed" and resaved.filter_mode == "unsupported"
    assert resaved.review_focus == "metadata"


@pytest.mark.parametrize("source,change", [
    ("batch", "cutoff"), ("batch", "bytes"), ("project", "axis"), ("project", "cutoff"),
])
def test_measurement_or_original_changes_clear_review_completion_but_keep_notes(
    upload_state, downloads, source, change,
):
    upload = Upload("graphene.cif", file_id="unchanged-upload-id")
    if source == "batch":
        upload_state["batch_upload"] = [upload]
        at = new_app("batch")
    else:
        saved = Project([ProjectEntry("graphene", "graphene.cif", upload.data)])
        upload_state["project_upload"] = Upload("saved.calclens.json", dumps_project(saved))
        at = open_project(new_app())
    note_widget(at).set_value("조건 변경 후 다시 검토").run()
    done_widget(at).check().run()
    assert project_download(downloads).entries[0].reviewed is True

    if change == "bytes":
        upload.data += b"\n# changed original bytes\n"
        at.run()
    elif change == "axis":
        axis = next(widget for widget in at.selectbox if widget.key.startswith("batch_axis_"))
        axis.set_value("a").run()
    else:
        cutoff = next(widget for widget in at.number_input if widget.key.startswith("batch_cutoff_"))
        cutoff.set_value(2.0).run()

    assert not at.exception
    assert done_widget(at).value is False
    resaved = project_download(downloads)
    assert resaved.entries[0].reviewed is False
    assert resaved.entries[0].note == "조건 변경 후 다시 검토"
    assert resaved.entries[0].data == upload.data
