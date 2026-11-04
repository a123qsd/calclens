"""Exercise batch transitions using the dataframe's native selection state."""

from pathlib import Path
from itertools import count

import pytest
import streamlit as st
from streamlit.testing.v1 import AppTest

ROOT = Path(__file__).resolve().parents[1]
UPLOAD_IDS = count()


class Upload:
    def __init__(self, name, data=None, file_id=None):
        self.name = name
        self.data = data if data is not None else (ROOT / "examples" / name).read_bytes()
        self.file_id = file_id if file_id is not None else f"upload-{next(UPLOAD_IDS)}"

    def getvalue(self):
        return self.data


def batch_app(monkeypatch, uploads):
    monkeypatch.setenv("CALCLENS_LANGUAGE", "ko")
    monkeypatch.setattr(
        st, "file_uploader",
        lambda *args, **kwargs: uploads if kwargs.get("key") == "batch_upload" else None,
    )
    at = AppTest.from_file(str(ROOT / "streamlit_app.py"), default_timeout=30).run()
    at.radio(key="source_ko").set_value("batch").run()
    assert not at.exception
    return at


def select_row(at, index):
    # AppTest has no dataframe click API. Set its actual keyed widget state;
    # keep st.dataframe and the app's selection processing unmodified.
    widget_key = at.dataframe[0].proto.id.split("-", 2)[-1]
    at.session_state[widget_key] = {
        "selection": {"rows": [index], "columns": [], "cells": []}
    }
    at.run()
    assert not at.exception


def configure_second_file(at):
    axes = [widget for widget in at.selectbox if widget.key.startswith("batch_axis_")]
    axis_key = axes[1].key
    axes[1].set_value("a").run()
    cutoffs = [widget for widget in at.number_input if widget.key.startswith("batch_cutoff_")]
    cutoff_key = cutoffs[1].key
    cutoffs[1].set_value(2.5).run()
    select_row(at, 1)
    assert at.metric[1].value == "3.120 Å"
    return axis_key, cutoff_key


@pytest.mark.parametrize("change", ["remove_first", "reorder"])
def test_file_settings_survive_upload_removal_or_reordering(monkeypatch, change):
    uploads = [Upload("graphene.cif"), Upload("mos2_a_normal.cif"), Upload("hbn.cif")]
    at = batch_app(monkeypatch, uploads)
    axis_key, cutoff_key = configure_second_file(at)

    if change == "remove_first":
        uploads.pop(0)
    else:
        uploads[:] = [uploads[2], uploads[0], uploads[1]]
    at.run()

    assert not at.exception
    assert not at.error
    assert at.selectbox(key=axis_key).value == "a"
    assert at.number_input(key=cutoff_key).value == 2.5
    rows = at.dataframe[0].value
    mos2_index = rows.index[rows["파일명"] == "mos2_a_normal.cif"][0]
    assert rows.loc[mos2_index, "선택 축"] == "a"
    assert rows.loc[mos2_index, "짧은 거리 기준 / Å"] == 2.5
    assert rows.loc[mos2_index, "핵 두께 / Å"] == pytest.approx(3.12)
    # Row positions change, but the selected MoS2 file remains the detail view.
    assert at.metric[1].value == "3.120 Å"
    select_row(at, int(mos2_index))
    assert at.metric[1].value == "3.120 Å"


def test_native_batch_selection_and_settings_survive_language_round_trip(monkeypatch):
    uploads = [Upload("graphene.cif"), Upload("mos2_a_normal.cif"), Upload("hbn.cif")]
    at = batch_app(monkeypatch, uploads)
    axis_key, cutoff_key = configure_second_file(at)

    for language, axis_column, cutoff_column in (
        ("English", "normal_axis", "short_distance_threshold_angstrom"),
        ("한국어", "선택 축", "짧은 거리 기준 / Å"),
    ):
        at.selectbox(key="language").set_value(language).run()
        assert not at.exception
        assert not at.error
        assert at.metric[1].value == "3.120 Å"
        assert at.metric[2].value == "16.880 Å"
        assert at.selectbox(key=axis_key).value == "a"
        assert at.number_input(key=cutoff_key).value == 2.5
        assert at.dataframe[0].value.iloc[1][axis_column] == "a"
        assert at.dataframe[0].value.iloc[1][cutoff_column] == 2.5


def test_identical_uploads_have_independent_measurement_settings(monkeypatch):
    at = batch_app(monkeypatch, [Upload("graphene.cif"), Upload("graphene.cif")])
    cutoffs = [widget for widget in at.number_input if widget.key.startswith("batch_cutoff_")]
    first_key, second_key = [widget.key for widget in cutoffs]
    at.number_input(key=first_key).set_value(1.4).run()
    at.number_input(key=second_key).set_value(2.0).run()
    assert not at.exception
    rows = at.dataframe[0].value
    assert list(rows["짧은 거리 기준 / Å"]) == [1.4, 2.0]
    assert list(rows["상태"]) == ["no_flags", "review_required"]
    select_row(at, 1)
    focus = next(widget for widget in at.radio if widget.key.startswith("review_focus_"))
    focus.set_value("short").run()
    assert not at.exception
    assert at.selectbox(key="contact_short")


def test_native_selection_of_failed_file_clears_previous_metrics(monkeypatch):
    uploads = [Upload("graphene.cif"), Upload("partial_occupancy.cif")]
    at = batch_app(monkeypatch, uploads)
    assert at.metric
    select_row(at, 1)
    assert not at.metric
    assert "partial_occupancy.cif" in at.error[0].value
    select_row(at, 0)
    assert not at.error
    assert at.metric[0].value == "1.420 Å"


def test_selected_mos2_is_retained_when_its_cutoff_changes(monkeypatch):
    at = batch_app(monkeypatch, [Upload("graphene.cif"), Upload("mos2.cif")])
    select_row(at, 1)
    cutoff = [widget for widget in at.number_input
              if widget.key.startswith("batch_cutoff_")][1]

    cutoff.set_value(2.5).run()

    assert not at.exception
    assert at.metric[1].value == "3.120 Å"
    assert at.metric[2].value == "16.880 Å"
    assert at.dataframe[0].value.iloc[1]["짧은 거리 기준 / Å"] == 2.5


def test_leaving_batch_and_returning_keeps_per_file_settings(monkeypatch):
    at = batch_app(monkeypatch, [Upload("graphene.cif"), Upload("mos2_a_normal.cif")])
    axis_key, cutoff_key = configure_second_file(at)

    at.radio(key="source_ko").set_value("examples").run()
    at.radio(key="source_ko").set_value("batch").run()

    assert not at.exception
    assert at.selectbox(key=axis_key).value == "a"
    assert at.number_input(key=cutoff_key).value == 2.5
    rows = at.dataframe[0].value
    assert rows.iloc[1]["선택 축"] == "a"
    assert rows.iloc[1]["짧은 거리 기준 / Å"] == 2.5
    assert rows.iloc[1]["핵 두께 / Å"] == pytest.approx(3.12)
