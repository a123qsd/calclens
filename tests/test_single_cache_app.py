"""Single inputs reuse geometry, including failures, across display reruns."""

import pytest
import streamlit as st
from streamlit.testing.v1 import AppTest

from slab_preflight import batch, core
from test_batch_state import ROOT, Upload


@pytest.mark.parametrize("source", ["examples", "upload"])
def test_single_input_display_changes_reuse_analysis(monkeypatch, source):
    calls = []
    analyze = core.analyze_cif

    def count(*args, **kwargs):
        calls.append(1)
        return analyze(*args, **kwargs)

    monkeypatch.setattr(core, "analyze_cif", count)
    monkeypatch.setattr(batch, "analyze_cif", count)
    upload = Upload("graphene.cif")
    monkeypatch.setattr(st, "file_uploader", lambda *a, **kw:
                        upload if kw.get("key") == "cif_upload" else [])
    at = AppTest.from_file(str(ROOT / "streamlit_app.py")).run()
    if source == "upload":
        at.radio(key="source_ko").set_value(source).run()
    initial = len(calls)
    at.checkbox(key="show_cell").uncheck().run()
    at.selectbox(key="repeats").set_value(3).run()
    at.selectbox(key="language").set_value("English").run()
    assert not at.exception
    assert len(calls) == initial
    at.number_input(key="threshold").set_value(2.0).run()
    assert len(calls) == initial + 1
    assert not at.exception


def test_unsupported_example_is_cached_without_stale_geometry(monkeypatch):
    calls = []
    analyze = core.analyze_cif

    def count(*args, **kwargs):
        calls.append(1)
        return analyze(*args, **kwargs)

    monkeypatch.setattr(core, "analyze_cif", count)
    monkeypatch.setattr(batch, "analyze_cif", count)
    at = AppTest.from_file(str(ROOT / "streamlit_app.py")).run()
    at.selectbox(key="example_ko").set_value("partial_occupancy.cif").run()
    initial = len(calls)
    at.selectbox(key="language").set_value("English").run()
    assert not at.exception
    assert len(calls) == initial
    assert not at.metric
    assert at.error
