"""Regression checks for source transitions and inspectable measurement evidence."""
import json
from pathlib import Path

import pytest
import streamlit as st
from streamlit.testing.v1 import AppTest

ROOT = Path(__file__).resolve().parents[1]


class Upload:
    def __init__(self, name, data=None):
        self.name = name
        self.data = data if data is not None else (ROOT / "examples" / name).read_bytes()

    def getvalue(self):
        return self.data


def app():
    return AppTest.from_file(str(ROOT / "streamlit_app.py"), default_timeout=30).run()


def example(at):
    return next(widget for widget in at.selectbox if widget.key.startswith("example_"))


@pytest.mark.parametrize("via_button", [True, False])
def test_return_to_sample_restores_matching_axis(monkeypatch, via_button):
    monkeypatch.setattr(st, "file_uploader", lambda *a, **kw: Upload("graphene.cif"))
    at = app()
    example(at).set_value("mos2_a_normal.cif").run()
    at.button(key="open_cif").click().run()
    at.selectbox(key="normal_axis").set_value("c").run()
    assert at.metric[0].value == "1.420 Å"
    if via_button:
        at.button(key="try_sample").click().run()
    else:
        at.radio(key="source_ko").set_value("examples").run()
    assert not at.exception
    assert not at.error
    assert example(at).value == "mos2_a_normal.cif"
    assert at.selectbox(key="normal_axis").value == "a"
    assert at.metric[1].value == "3.120 Å"


def test_minimum_pair_button_shows_evidence_above_cutoff():
    at = app()
    at.button(key="show_minimum_pair").click().run()
    assert not at.exception
    traces = [trace for chart in at.get("plotly_chart")
              for trace in json.loads(chart.proto.spec)["data"]]
    line = next(trace for trace in traces if trace.get("meta", {}).get("role") == "contact_line")
    assert {line["meta"]["i"], line["meta"]["j"]} == {0, 1}
    assert "1.420" in "\n".join(item.value for item in at.markdown)
    at.selectbox(key="language").set_value("English").run()
    assert not at.exception
    assert at.session_state["review_focus"] == "minimum"


def test_batch_keeps_failures_and_uses_selected_file_settings(monkeypatch):
    from types import SimpleNamespace

    uploads = [Upload("graphene.cif"), Upload("mos2_a_normal.cif"), Upload("partial_occupancy.cif")]
    monkeypatch.setattr(st, "file_uploader", lambda *a, **kw: uploads)
    selected = []
    original = st.dataframe

    def select_row(*args, **kwargs):
        result = original(*args, **kwargs)
        if kwargs.get("on_select") == "rerun":
            return SimpleNamespace(selection=SimpleNamespace(rows=selected))
        return result

    monkeypatch.setattr(st, "dataframe", select_row)
    at = app()
    at.radio(key="source_ko").set_value("batch").run()
    assert not at.exception
    table = at.dataframe[0].value
    assert list(table["상태"]) == ["no_flags", "unsupported", "unsupported"]
    assert at.metric[0].value == "1.420 Å"
    second_axis = [w for w in at.selectbox if w.key.startswith("batch_axis_")][1]
    selected[:] = [1]
    second_axis.set_value("a").run()
    assert not at.exception
    assert at.metric[1].value == "3.120 Å"
    assert at.dataframe[0].value.iloc[1]["선택 축"] == "a"
    at.selectbox(key="language").set_value("English").run()
    assert at.metric[1].value == "3.120 Å"
    assert at.dataframe[0].value.iloc[1]["normal_axis"] == "a"
    selected[:] = [2]
    at.run()
    assert not at.exception
    assert not at.metric
    assert "fully occupied" in at.error[0].value
    assert len(at.dataframe[0].value) == 3
    at.button(key="try_sample").click().run()
    assert not at.exception
    assert at.metric[0].value == "1.420 Å"


def test_batch_limit_is_explained_without_analyzing(monkeypatch):
    monkeypatch.setattr(st, "file_uploader", lambda *a, **kw: [Upload("graphene.cif")] * 21)
    at = app()
    at.radio(key="source_ko").set_value("batch").run()
    assert not at.exception
    assert "20" in at.error[0].value
    assert not at.metric


def test_late_overlap_remains_selectable_with_truncation_notice(monkeypatch):
    from io import BytesIO
    from ase import Atoms
    from ase.io import write

    positions = [[index * 0.02, 0, 0] for index in range(29)] + [[28 * 0.02, 0, 0]]
    raw = BytesIO()
    write(raw, Atoms("C30", positions=positions, cell=[10, 10, 20], pbc=True), format="cif")
    monkeypatch.setattr(st, "file_uploader", lambda *a, **kw: Upload("dense.cif", raw.getvalue()))
    at = app()
    at.button(key="open_cif").click().run()
    focus = next(w for w in at.radio if w.key.startswith("review_focus_"))
    focus.set_value("overlap").run()
    assert not at.exception
    assert at.selectbox(key="contact_overlap")
    assert any("435" in item.value for item in at.warning)
    assert not any("거리 기록이 없습니다" in item.value for item in at.markdown)
    traces = [trace for chart in at.get("plotly_chart")
              for trace in json.loads(chart.proto.spec)["data"]]
    line = next(trace for trace in traces if trace.get("meta", {}).get("role") == "contact_line")
    assert {line["meta"]["i"], line["meta"]["j"]} == {28, 29}
