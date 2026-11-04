"""Interface regressions for complete example flows, using Streamlit's test harness."""
from pathlib import Path

from streamlit.testing.v1 import AppTest

ROOT = Path(__file__).resolve().parents[1]


def app():
    return AppTest.from_file(str(ROOT / "streamlit_app.py"), default_timeout=30).run()


def test_korean_default_shows_graphene_geometry():
    at = app()
    assert not at.exception
    assert at.title[0].value == "CalcLens"
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
    at.radio(key="source").set_value("upload").run()
    assert not at.exception
    assert len(at.metric) == 0


def test_visual_replication_does_not_change_report_geometry():
    from slab_preflight.core import analyze_cif
    from slab_preflight.plotting import structure_figure

    report = analyze_cif((ROOT / "examples/graphene.cif").read_bytes())
    fig = structure_figure(report, repeats=3, show_cell=True)
    carbon = fig.data[0]
    assert len(carbon.x) == 2 * 3 * 3
    assert {tuple(item[1:]) for item in carbon.customdata} == {(u, v) for u in range(3) for v in range(3)}
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
