"""Interface regressions for complete example flows, using Streamlit's test harness."""
from pathlib import Path

from streamlit.testing.v1 import AppTest

ROOT = Path(__file__).resolve().parents[1]


def app():
    return AppTest.from_file(str(ROOT / "streamlit_app.py"), default_timeout=30).run()


def focus_radio(at):
    return next(widget for widget in at.radio if widget.key.startswith("review_focus_"))


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
    at.selectbox(key="example").set_value("mos2.cif").run()
    assert not at.exception
    assert at.metric[1].label == "Nuclear-span thickness"
    assert float(at.metric[1].value.split()[0]) > 0
    assert len(at.get("plotly_chart")) == 2


def test_duplicate_example_is_flagged_without_crashing():
    at = app()
    at.selectbox(key="example").set_value("graphene_duplicate.cif").run()
    assert not at.exception
    assert at.metric[0].value == "0.000 Å"
    assert len(at.error) + len(at.warning) > 0


def test_unsupported_example_is_explained_and_has_no_metrics():
    at = app()
    at.selectbox(key="example").set_value("partial_occupancy.cif").run()
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
    at.selectbox(key="example").set_value("tiny_self_image.cif").run()
    focus_radio(at).set_value("short").run()
    assert not at.exception
    traces = [trace for chart in at.get("plotly_chart") for trace in json.loads(chart.proto.spec)["data"]]
    line = next(trace for trace in traces if trace.get("meta", {}).get("role") == "contact_line")
    assert line["meta"]["i"] == line["meta"]["j"] == 0
    assert any(value != 0 for value in line["meta"]["shift"])
    assert line["x"][0] != line["x"][1]


def test_a_normal_sample_sets_axis_and_keeps_gap_measurement():
    at = app()
    at.selectbox(key="example").set_value("mos2_a_normal.cif").run()
    assert not at.exception
    assert at.selectbox(key="normal_axis").value == "a"
    assert at.metric[1].value == "3.120 Å"
    assert at.metric[2].value == "16.880 Å"
    at.selectbox(key="example").set_value("mos2_b_normal.cif").run()
    assert not at.exception
    assert at.selectbox(key="normal_axis").value == "b"
    assert at.metric[2].value == "16.880 Å"


def test_ambiguous_gap_is_labeled_and_highlighted_for_review():
    import json

    at = app()
    at.selectbox(key="example").set_value("bilayer_graphene.cif").run()
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
    at.selectbox(key="example").set_value("mos2_wrapped.cif").run()
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
