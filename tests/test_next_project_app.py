"""End-to-end work editing, human progress and explicit pair selections."""

from dataclasses import replace
import json
from streamlit.testing.v1 import AppTest

from slab_preflight.project import Project, ProjectEntry, dumps_project, mark_reviewed
from test_batch_state import ROOT, Upload
import test_project_app as project_tests
from test_project_app import (
    new_app, open_project, project_download,
    done_widget, note_widget, example_bytes,
)

downloads = project_tests.downloads
upload_state = project_tests.upload_state


def work():
    return Project([
        ProjectEntry("first", "graphene.cif", example_bytes("graphene.cif"), note="keep first"),
        mark_reviewed(ProjectEntry("second", "mos2.cif", example_bytes("mos2.cif"),
                                   note="keep second", short_distance=2.5)),
    ], selected_id="second")


def opened(upload_state, project=None):
    upload_state["project_upload"] = Upload("work.calclens.json", dumps_project(project or work()))
    return open_project(new_app())


def test_add_replace_remove_preserves_notes_identity_and_selection(upload_state, downloads):
    at = opened(upload_state)
    initial = project_download(downloads)
    generation = at.session_state["project_generation"]
    upload_state[f"project_add_upload_{generation}"] = [Upload("hbn.cif", example_bytes("hbn.cif"))]
    at.run().button(key="project_add").click().run()
    assert not at.exception
    added = project_download(downloads)
    assert len(added.entries) == 3
    assert added.entries[:2] == initial.entries
    assert added.selected_id == "second"

    at.selectbox(key="project_edit_target_ko").set_value("second").run()
    generation = at.session_state["project_generation"]
    upload_state[f"project_replace_upload_{generation}"] = Upload("changed.cif", example_bytes("hbn.cif"))
    at.run().button(key="project_replace").click().run()
    assert not at.exception
    replaced = project_download(downloads)
    assert replaced.selected_id == "second"
    second = replaced.entries[1]
    assert second.filename == "changed.cif"
    assert second.note == "keep second" and second.short_distance == 2.5
    assert not second.reviewed
    assert second.review_stamp == initial.entries[1].review_stamp
    assert not done_widget(at).value

    at.button(key="project_remove").click().run()
    assert not at.exception
    removed = project_download(downloads)
    assert [entry.id for entry in removed.entries] == ["first", added.entries[2].id]
    assert removed.selected_id == added.entries[2].id
    assert removed.entries[0].note == "keep first"


def test_progress_filter_is_independent_and_survives_save(upload_state, downloads):
    at = opened(upload_state)
    at.radio(key="progress_filter_ko").set_value("unreviewed").run()
    assert not at.exception
    assert list(at.dataframe[0].value["파일명"]) == ["graphene.cif"]
    assert project_download(downloads).selected_id == "first"
    done_widget(at).check().run()
    assert not at.exception
    assert not at.metric
    saved = project_download(downloads)
    assert saved.progress_filter == "unreviewed"
    assert all(entry.reviewed for entry in saved.entries)
    assert all(entry.review_stamp for entry in saved.entries)
    upload_state["project_upload"] = Upload("saved.json", dumps_project(saved))
    reopened = open_project(new_app())
    assert reopened.radio(key="progress_filter_ko").value == "unreviewed"
    assert not reopened.metric
    reopened.radio(key="progress_filter_ko").set_value("reviewed").run()
    assert len(reopened.dataframe[0].value) == 2


def test_side_by_side_is_optional_and_compares_distinct_valid_files(upload_state, downloads):
    at = opened(upload_state)
    assert len(at.get("plotly_chart")) == 2
    at.checkbox(key="show_comparison").check().run()
    assert not at.exception
    assert len(at.get("plotly_chart")) == 4
    assert at.selectbox(key="compare_before_ko").value != at.selectbox(key="compare_after_ko").value
    changes = next(table.value for table in at.dataframe if "변화량" in table.value.columns)
    thickness = changes.loc[changes["지표"] == "핵 두께 / Å"].iloc[0]
    assert abs(thickness["변화량"] - 3.12) < 1e-6


def test_pair_selection_records_images_and_reopens_without_trusted_distances(upload_state, downloads):
    at = opened(upload_state)
    at.checkbox(key="measure_pair_enabled").check().run()
    assert not at.exception
    at.number_input(key="measure_second_second_a").set_value(1).run()
    at.selectbox(key="measure_second_mode").set_value("displayed").run()
    at.button(key="measure_second_save").click().run()
    assert not at.exception
    saved = project_download(downloads)
    assert len(saved.entries[1].measurements) == 1
    selection = saved.entries[1].measurements[0]
    assert selection.second_shift == (1, 0, 0)
    assert selection.mode == "displayed"
    stored = json.loads(downloads["download_project"]["data"])
    assert "distance_angstrom" not in json.dumps(stored["entries"][1]["measurements"])
    upload_state["project_upload"] = Upload("pairs.json", dumps_project(saved))
    reopened = open_project(new_app())
    reopened.checkbox(key="measure_pair_enabled").check().run()
    reopened.button(key="measure_second_load").click().run()
    assert not reopened.exception
    assert reopened.number_input(key="measure_second_second_a").value == 1
    assert reopened.selectbox(key="measure_second_mode").value == "displayed"


def test_replaced_source_clears_saved_pairs_but_retains_note(upload_state, downloads):
    from slab_preflight.project import PairSelection

    original = work()
    original.entries[1] = replace(original.entries[1], measurements=(PairSelection(0, 1),))
    at = opened(upload_state, original)
    at.selectbox(key="project_edit_target_ko").set_value("second").run()
    generation = at.session_state["project_generation"]
    upload_state[f"project_replace_upload_{generation}"] = Upload("hbn.cif", example_bytes("hbn.cif"))
    at.run().button(key="project_replace").click().run()
    assert not at.exception
    assert project_download(downloads).entries[1].measurements == ()
    assert note_widget(at).value == "keep second"


def test_sample_pair_can_be_saved_and_survives_language_switch():
    at = AppTest.from_file(str(ROOT / "streamlit_app.py")).run()
    at.checkbox(key="measure_pair_enabled").check().run()
    save = next(button for button in at.button if button.key.startswith("measure_")
                and button.key.endswith("_save"))
    save.click().run()
    assert not at.exception
    entry = at.session_state["single_measurement_entry"]
    assert len(entry.measurements) == 1
    at.selectbox(key="language").set_value("English").run()
    assert not at.exception
    assert at.session_state["single_measurement_entry"] == entry


def test_analysis_revision_change_warns_even_when_app_and_ase_match(upload_state, downloads):
    saved = replace(work(), analysis_revision="older-engine")
    at = opened(upload_state, saved)
    assert not at.exception
    assert any("older-engine" in warning.value for warning in at.warning)
