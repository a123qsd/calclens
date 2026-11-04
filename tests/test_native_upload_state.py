"""Exercise upload identity and lifecycle with Streamlit's real file widget."""

import pytest
from streamlit.testing.v1 import AppTest

from test_batch_state import ROOT, select_row


def native_batch_app(monkeypatch, files):
    monkeypatch.setenv("CALCLENS_LANGUAGE", "ko")
    at = AppTest.from_file(str(ROOT / "streamlit_app.py"), default_timeout=30).run()
    if not hasattr(at, "file_uploader"):
        pytest.skip("Native file-upload interactions require a newer Streamlit AppTest.")
    at.radio(key="source_ko").set_value("batch").run()
    uploader = at.file_uploader(key="batch_upload")
    if not hasattr(uploader, "set_value"):
        pytest.skip("This Streamlit AppTest cannot supply native upload bytes.")
    uploader.set_value(files).run()
    assert not at.exception
    return at


def test_native_uploads_retain_selected_review_across_source_and_language_changes(monkeypatch):
    files = [(name, (ROOT / "examples" / name).read_bytes(), "chemical/x-cif")
             for name in ("graphene.cif", "mos2_a_normal.cif")]
    at = native_batch_app(monkeypatch, files)
    axes = [widget for widget in at.selectbox if widget.key.startswith("batch_axis_")]
    axis_key = axes[1].key
    at.selectbox(key=axis_key).set_value("a").run()
    cutoffs = [widget for widget in at.number_input if widget.key.startswith("batch_cutoff_")]
    cutoff_key = cutoffs[1].key
    at.number_input(key=cutoff_key).set_value(2.5).run()
    select_row(at, 1)
    note = next(widget for widget in at.text_area if widget.key.startswith("review_note_"))
    note_key = note.key
    note.input("Checked the a-normal layer and its periodic image.").run()
    done_key = next(widget.key for widget in at.checkbox
                    if widget.key.startswith("review_done_"))
    at.checkbox(key=done_key).check().run()
    selected_id = at.session_state["batch_selected_id"]
    upload_ids = [upload.file_id for upload in at.file_uploader(key="batch_upload").value]

    at.radio(key="source_ko").set_value("examples").run()
    at.selectbox(key="language").set_value("English").run()
    at.radio(key="source_en").set_value("batch").run()

    assert not at.exception
    assert at.session_state["batch_selected_id"] == selected_id
    assert [upload.file_id for upload in at.file_uploader(key="batch_upload").value] == upload_ids
    assert at.selectbox(key=axis_key).value == "a"
    assert at.number_input(key=cutoff_key).value == 2.5
    assert at.text_area(key=note_key).value == "Checked the a-normal layer and its periodic image."
    assert at.checkbox(key=done_key).value is True
    assert at.metric[1].value == "3.120 Å"
    assert at.metric[2].value == "16.880 Å"


def test_native_identical_uploads_stay_independent_and_explicit_clear_removes_results(monkeypatch):
    data = (ROOT / "examples" / "graphene.cif").read_bytes()
    at = native_batch_app(monkeypatch, [("same.cif", data, "chemical/x-cif")] * 2)
    uploads = at.file_uploader(key="batch_upload").value
    assert len(uploads) == 2
    assert uploads[0] is not uploads[1]
    assert uploads[0].file_id != uploads[1].file_id
    cutoffs = [widget for widget in at.number_input if widget.key.startswith("batch_cutoff_")]
    first_key, second_key = [widget.key for widget in cutoffs]
    at.number_input(key=first_key).set_value(1.4).run()
    at.number_input(key=second_key).set_value(2.0).run()
    select_row(at, 1)
    selected_id = at.session_state["batch_selected_id"]
    at.number_input(key=first_key).set_value(1.5).run()

    assert not at.exception
    assert at.session_state["batch_selected_id"] == selected_id
    assert list(at.dataframe[0].value["짧은 거리 기준 / Å"]) == [1.5, 2.0]
    assert list(at.dataframe[0].value["상태"]) == ["review_required", "review_required"]
    assert at.metric[0].value == "1.420 Å"

    at.file_uploader(key="batch_upload").clear().run()

    assert not at.exception
    assert at.session_state["upload_records"] == []
    assert not at.metric
    assert not at.get("plotly_chart")
    assert not at.dataframe
    assert at.info
