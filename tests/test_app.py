"""Interface regressions for complete example flows, using Streamlit's test harness."""
from pathlib import Path

from streamlit.testing.v1 import AppTest

ROOT = Path(__file__).resolve().parents[1]


def app():
    return AppTest.from_file(str(ROOT / "streamlit_app.py"), default_timeout=30).run()


def focus_radio(at):
    return next(widget for widget in at.radio if widget.key.startswith("review_focus_"))


def translated_selectbox(at, logical_key):
    return next(widget for widget in at.selectbox if widget.key.startswith(logical_key + "_"))


def test_korean_default_shows_graphene_geometry():
    at = app()
    assert not at.exception
    assert at.title[0].value == "구조 개요"
    assert at.selectbox(key="language").value == "한국어"
    assert at.metric[0].value == "1.420 Å"
    assert at.metric[1].value == "0.000 Å"
    assert len(at.get("plotly_chart")) == 2


def test_language_and_mos2_example_change():
    at = app()
    at.selectbox(key="language").set_value("English").run()
    translated_selectbox(at, "example").set_value("mos2.cif").run()
    assert not at.exception
    assert at.metric[1].label == "Nuclear-span thickness"
    assert float(at.metric[1].value.split()[0]) > 0
    assert len(at.get("plotly_chart")) == 2


def test_duplicate_example_is_flagged_without_crashing():
    at = app()
    translated_selectbox(at, "example").set_value("graphene_duplicate.cif").run()
    assert not at.exception
    assert at.metric[0].value == "0.000 Å"
    assert len(at.error) + len(at.warning) > 0


def test_unsupported_example_is_explained_and_has_no_metrics():
    at = app()
    translated_selectbox(at, "example").set_value("partial_occupancy.cif").run()
    assert not at.exception
    assert len(at.error) > 0
    assert len(at.metric) == 0


def test_upload_empty_state_does_not_keep_previous_results():
    at = app()
    at.radio(key="source_ko").set_value("upload").run()
    assert not at.exception
    assert len(at.metric) == 0


def test_visual_replication_does_not_change_report_geometry():
    from slab_preflight.core import analyze_cif
    from slab_preflight.plotting import structure_figure

    report = analyze_cif((ROOT / "examples/graphene.cif").read_bytes())
    fig = structure_figure(report, repeats=3, show_cell=True)
    carbon = fig.data[0]
    assert len(carbon.x) == 2 * 3 * 3
    assert {tuple(item[1:]) for item in carbon.customdata} == {(u, v, 0) for u in range(3) for v in range(3)}
    assert report["atom_count"] == 2
    cell_lines = fig.data[-1]
    assert list(cell_lines.x).count(None) == 12


def test_profile_shading_matches_wrapped_gap_length():
    from slab_preflight.core import analyze_cif
    from slab_preflight.plotting import profile_figure

    for filename in ("graphene.cif", "mos2.cif", "mos2_wrapped.cif"):
        report = analyze_cif((ROOT / "examples" / filename).read_bytes())
        fig = profile_figure(report)
        total_shading = sum(shape.x1 - shape.x0 for shape in fig.layout.shapes)
        assert abs(total_shading - report["metrics"]["nuclei_gap_angstrom"]) < 1e-9
        assert sum(len(trace.x) for trace in fig.data) == report["atom_count"]


def test_check_selection_highlights_real_periodic_partner():
    import json

    at = app()
    translated_selectbox(at, "example").set_value("tiny_self_image.cif").run()
    focus_radio(at).set_value("short").run()
    assert not at.exception
    traces = [trace for chart in at.get("plotly_chart") for trace in json.loads(chart.proto.spec)["data"]]
    line = next(trace for trace in traces if trace.get("meta", {}).get("role") == "contact_line")
    assert line["meta"]["i"] == line["meta"]["j"] == 0
    assert any(value != 0 for value in line["meta"]["shift"])
    assert line["x"][0] != line["x"][1]


def test_a_normal_sample_sets_axis_and_keeps_gap_measurement():
    at = app()
    translated_selectbox(at, "example").set_value("mos2_a_normal.cif").run()
    assert not at.exception
    assert at.selectbox(key="normal_axis").value == "a"
    assert at.metric[1].value == "3.120 Å"
    assert at.metric[2].value == "16.880 Å"
    translated_selectbox(at, "example").set_value("mos2_b_normal.cif").run()
    assert not at.exception
    assert at.selectbox(key="normal_axis").value == "b"
    assert at.metric[2].value == "16.880 Å"


def test_ambiguous_gap_is_labeled_and_highlighted_for_review():
    import json

    at = app()
    translated_selectbox(at, "example").set_value("bilayer_graphene.cif").run()
    focus_radio(at).set_value("gap").run()
    assert not at.exception
    assert "검토 필요" in at.metric[2].label
    traces = [trace for chart in at.get("plotly_chart") for trace in json.loads(chart.proto.spec)["data"]]
    gaps = [trace for trace in traces if trace.get("meta", {}).get("role") == "gap"]
    assert gaps
    assert all(trace["color"] == "#D6A14B" for trace in gaps)
    assert at.warning


def test_header_buttons_change_input_mode():
    at = app()
    at.button(key="open_cif").click().run()
    assert at.radio(key="source_ko").value == "upload"
    assert not at.metric
    at.button(key="try_sample").click().run()
    assert at.radio(key="source_ko").value == "examples"
    assert len(at.metric) == 3


def test_periodic_contact_line_uses_shifted_endpoint():
    import numpy as np
    from slab_preflight.core import analyze_cif
    from slab_preflight.plotting import structure_figure

    report = analyze_cif((ROOT / "examples/tiny_self_image.cif").read_bytes())
    contact = report["short_contacts"][0]
    figure = structure_figure(report, highlighted_atoms=[contact["i"]], selected_contact=contact)
    line = next(trace for trace in figure.data if trace.meta.get("role") == "contact_line")
    image = next(trace for trace in figure.data if trace.meta.get("role") == "contact_image")
    expected = np.asarray(report["positions"])[contact["j"]] + np.asarray(contact["shift"]) @ np.asarray(report["cell"])
    np.testing.assert_allclose([line.x[1], line.y[1], line.z[1]], expected)
    np.testing.assert_allclose([image.x[0], image.y[0], image.z[0]], expected)
    assert abs(np.linalg.norm(np.array([line.x[1]-line.x[0], line.y[1]-line.y[0], line.z[1]-line.z[0]])) - contact["distance_angstrom"]) < 1e-10


def test_gap_mesh_and_repetition_follow_each_selected_normal():
    import numpy as np
    from slab_preflight.core import analyze_cif
    from slab_preflight.plotting import structure_figure

    for axis, filename in (("a", "mos2_a_normal.cif"), ("b", "mos2_b_normal.cif"), ("c", "mos2_wrapped.cif")):
        report = analyze_cif((ROOT / "examples" / filename).read_bytes(), normal_axis=axis)
        index = "abc".index(axis)
        figure = structure_figure(report, repeats=2, highlight_gap=True)
        sites = [trace for trace in figure.data if trace.meta.get("role") == "sites"]
        assert all(all(label[index + 1] == 0 for label in trace.customdata) for trace in sites)
        gaps = [trace for trace in figure.data if trace.meta.get("role") == "gap"]
        total = 0
        for trace in gaps:
            fractional = np.column_stack([trace.x, trace.y, trace.z]) @ np.linalg.inv(np.asarray(report["cell"]))
            lo, hi = trace.meta["fraction_range"]
            np.testing.assert_allclose(sorted(set(np.round(fractional[:, index], 10))), [lo, hi], atol=1e-9)
            total += hi - lo
        assert abs(total * report["metrics"]["normal_height_angstrom"] - report["metrics"]["nuclei_gap_angstrom"]) < 1e-9


def test_radio_selection_and_highlight_survive_language_round_trip():
    import json

    at = app()
    translated_selectbox(at, "example").set_value("mos2_wrapped.cif").run()
    focus_radio(at).set_value("gap").run()
    old_source_id = at.radio(key="source_ko").proto.id
    old_focus_id = focus_radio(at).proto.id
    at.selectbox(key="language").set_value("English").run()
    assert not at.exception
    assert at.radio(key="source_en").value == "examples"
    assert focus_radio(at).value == "gap"
    assert at.session_state["source"] == "examples"
    assert at.session_state["review_focus"] == "gap"
    assert at.radio(key="source_en").proto.id != old_source_id
    assert focus_radio(at).proto.id != old_focus_id
    traces = [trace for chart in at.get("plotly_chart") for trace in json.loads(chart.proto.spec)["data"]]
    assert any(trace.get("meta", {}).get("role") == "gap" for trace in traces)
    focus_radio(at).set_value("metadata").run()
    at.selectbox(key="language").set_value("한국어").run()
    assert not at.exception
    assert focus_radio(at).value == "metadata"
    assert at.session_state["review_focus"] == "metadata"
    assert at.metric[1].value == "3.120 Å"


def test_upload_source_survives_language_change_and_header_actions():
    at = app()
    at.radio(key="source_ko").set_value("upload").run()
    old_id = at.radio(key="source_ko").proto.id
    at.selectbox(key="language").set_value("English").run()
    assert not at.exception
    assert at.radio(key="source_en").value == "upload"
    assert at.radio(key="source_en").proto.id != old_id
    assert at.session_state["source"] == "upload"
    at.button(key="try_sample").click().run()
    assert at.radio(key="source_en").value == "examples"
    at.selectbox(key="language").set_value("한국어").run()
    assert at.radio(key="source_ko").value == "examples"
    assert len(at.metric) == 3


def test_review_selection_survives_changed_status_labels():
    at = app()
    focus_radio(at).set_value("short").run()
    before_id = focus_radio(at).proto.id
    at.number_input(key="threshold").set_value(2.0).run()
    assert not at.exception
    assert focus_radio(at).value == "short"
    assert focus_radio(at).proto.id != before_id
    assert at.selectbox(key="contact_short")


def test_english_launch_default_keeps_interactive_language_choice(monkeypatch):
    monkeypatch.setenv("CALCLENS_LANGUAGE", "en")
    at = app()
    assert not at.exception
    assert at.selectbox(key="language").value == "English"
    assert at.title[0].value == "Structure overview"
    assert any("README.en.md" in item.value for item in at.sidebar.markdown)
    at.selectbox(key="language").set_value("한국어").run()
    assert not at.exception
    assert at.selectbox(key="language").value == "한국어"
    assert at.title[0].value == "구조 개요"
    assert any("README.ko.md" in item.value for item in at.sidebar.markdown)
    translated_selectbox(at, "example").set_value("mos2.cif").run()
    assert at.selectbox(key="language").value == "한국어"
    assert at.metric[1].value == "3.120 Å"
    assert any("/releases)" in item.value for item in at.sidebar.markdown)


def test_korean_launch_default_and_missing_setting(monkeypatch):
    for setting in ("ko", None):
        if setting is None:
            monkeypatch.delenv("CALCLENS_LANGUAGE", raising=False)
        else:
            monkeypatch.setenv("CALCLENS_LANGUAGE", setting)
        at = app()
        assert not at.exception
        assert at.selectbox(key="language").value == "한국어"


def test_download_language_encoding_and_canonical_values(monkeypatch):
    import codecs
    import json
    from streamlit.delta_generator import DeltaGenerator

    monkeypatch.delenv("CALCLENS_LANGUAGE", raising=False)
    captured = {}
    original = DeltaGenerator.download_button

    def capture(self, label, data, *args, **kwargs):
        if kwargs.get("key") in ("download_csv", "download_report"):
            captured[kwargs["key"]] = {"data": data, "file_name": kwargs["file_name"]}
        return original(self, label, data, *args, **kwargs)

    monkeypatch.setattr(DeltaGenerator, "download_button", capture)
    at = app()
    assert not at.exception
    korean = json.loads(captured["download_report"]["data"])
    assert korean["report_language"] == "ko"
    assert captured["download_report"]["file_name"].endswith("_ko.json")
    assert captured["download_csv"]["file_name"].endswith("_ko.csv")
    assert captured["download_csv"]["data"].startswith(codecs.BOM_UTF8)
    korean_csv = captured["download_csv"]["data"].decode("utf-8-sig")
    assert any("가" <= char <= "힣" for char in korean_csv.splitlines()[0])
    assert any("가" <= char <= "힣" for char in korean["issues"][0]["message"])

    translated_selectbox(at, "report_language").set_value("en").run()
    assert not at.exception
    english = json.loads(captured["download_report"]["data"])
    assert english["report_language"] == "en"
    assert captured["download_report"]["file_name"].endswith("_en.json")
    assert captured["download_csv"]["file_name"].endswith("_en.csv")
    assert not captured["download_csv"]["data"].startswith(codecs.BOM_UTF8)
    assert captured["download_csv"]["data"].decode("utf-8").startswith("record_type,")
    for key in ("metrics", "criteria", "cell", "positions", "units", "short_contacts"):
        assert korean[key] == english[key]
    assert [issue["code"] for issue in korean["issues"]] == [issue["code"] for issue in english["issues"]]

    # An explicit output choice is independent of the interface. Switching to
    # automatic selection follows the current interface without changing data.
    translated_selectbox(at, "report_language").set_value("ko").run()
    at.selectbox(key="language").set_value("English").run()
    assert json.loads(captured["download_report"]["data"])["report_language"] == "ko"
    translated_selectbox(at, "report_language").set_value("interface").run()
    assert json.loads(captured["download_report"]["data"])["report_language"] == "en"


def test_unsupported_reason_is_translated_and_original_remains_available():
    at = app()
    translated_selectbox(at, "example").set_value("partial_occupancy.cif").run()
    assert not at.exception
    prose = "\n".join(item.value for item in at.markdown)
    assert "점유" in prose
    assert any("fully occupied" in block.value for block in at.code)
    at.selectbox(key="language").set_value("English").run()
    assert not at.exception
    assert any("fully occupied" in item.value for item in at.markdown)


def test_translated_selectboxes_remount_and_keep_selection_and_axis():
    at = app()
    translated_selectbox(at, "example").set_value("mos2_a_normal.cif").run()
    example_id = translated_selectbox(at, "example").proto.id
    report_id = translated_selectbox(at, "report_language").proto.id
    at.selectbox(key="language").set_value("English").run()
    assert not at.exception
    assert translated_selectbox(at, "example").value == "mos2_a_normal.cif"
    assert translated_selectbox(at, "example").proto.id != example_id
    assert "MoS₂ · a-axis normal" in translated_selectbox(at, "example").proto.options
    assert at.selectbox(key="normal_axis").value == "a"
    assert translated_selectbox(at, "report_language").value == "interface"
    assert translated_selectbox(at, "report_language").proto.id != report_id
    assert "Same as interface" in translated_selectbox(at, "report_language").proto.options
    translated_selectbox(at, "report_language").set_value("ko").run()
    translated_selectbox(at, "example").set_value("mos2_b_normal.cif").run()
    assert at.selectbox(key="normal_axis").value == "b"
    at.selectbox(key="language").set_value("한국어").run()
    assert not at.exception
    assert translated_selectbox(at, "example").value == "mos2_b_normal.cif"
    assert at.selectbox(key="normal_axis").value == "b"
    assert translated_selectbox(at, "report_language").value == "ko"
    assert "화면과 같음" in translated_selectbox(at, "report_language").proto.options


def test_language_change_does_not_reapply_sample_axis_callback():
    at = app()
    translated_selectbox(at, "example").set_value("tiny_self_image.cif").run()
    at.selectbox(key="normal_axis").set_value("b").run()
    assert not at.exception
    at.selectbox(key="language").set_value("English").run()
    assert not at.exception
    assert at.selectbox(key="normal_axis").value == "b"
    assert translated_selectbox(at, "example").value == "tiny_self_image.cif"


def test_mandatory_localized_selectors_are_not_clearable_and_recover_empty_values():
    at = app()
    translated_selectbox(at, "example").set_value("mos2_a_normal.cif").run()
    assert translated_selectbox(at, "example").proto.HasField("default")
    assert translated_selectbox(at, "report_language").proto.HasField("default")
    # A malformed/old client can still submit an empty value. Streamlit coerces
    # it to the nonempty default; the sample callback must remain safe.
    translated_selectbox(at, "example").set_value(None).run()
    assert not at.exception
    assert translated_selectbox(at, "example").value == "graphene.cif"
    assert at.selectbox(key="normal_axis").value == "c"
    translated_selectbox(at, "report_language").set_value("ko").run()
    translated_selectbox(at, "report_language").set_value(None).run()
    assert not at.exception
    assert translated_selectbox(at, "report_language").value == "interface"
