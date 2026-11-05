"""Check durable research workflows with actual water electronic-calculation files.

Run against an isolated built local server, or omit --url to start a temporary
one. Scientific inputs come from examples/electronic_case; the one deliberately
damaged project is an explicit negative test. No electronic calculation is run.
"""

from __future__ import annotations

import argparse
import base64
from hashlib import sha256
import json
from pathlib import Path
import traceback
import urllib.parse
import zipfile

from smoke_viewer_features import (
    assert_camera_equal, canvas, choose_source, idle, import_file, instrument,
    open_auxiliary, open_settings, png_header, scene_state, settle, viewer, workspace_server,
)
from smoke_workspace import (
    _download, accept_workspace_dialog, read_project_document, require,
)


ROOT = Path(__file__).resolve().parents[1]
CASE = ROOT / "examples" / "electronic_case"
DEFAULT_OUTPUT = ROOT.parent.parent / "work" / "browser" / "research-workspace"
NOTE = "Unapplied water research note.\n다른 파일과 화면을 확인한 뒤 이어서 편집합니다."
SECOND_NOTE = "Unapplied graphene draft belongs to this file only."


def workspace(page):
    return page.evaluate("async () => (await fetch('/api/v1/workspace', {cache:'no-store'})).json()")


def entry_by_name(state, filename):
    return next(entry for entry in state["entries"] if entry["filename"] == filename)


def overview(page):
    page.get_by_role("button", name="Overview", exact=True).click()
    idle(page)


def prepare_record_filters(page, expect):
    """Establish the record visibility needed by this independently callable flow.

    Frozen-Windows checks run after the basic workspace smoke on the same server.
    Its final unsupported-only filter is intentionally preserved by CIF replacement,
    and would hide both supported research inputs unless this flow resets it.
    """
    overview(page)
    previous = {}
    for name in ("geometry-filter", "progress-filter"):
        control = page.get_by_test_id(name)
        previous[name] = control.input_value()
        if previous[name] != "all":
            control.select_option("all")
            idle(page)
        expect(control).to_have_value("all")
    return previous


def edit_panel(page):
    panel = page.locator("details.tool-card").filter(
        has=page.get_by_text("Edit selected structure", exact=True),
    )
    if not panel.evaluate("element => element.open"):
        panel.locator("summary").click()
    return panel


def uploaded_files(page, paths):
    page.get_by_test_id("cif-replace-upload").set_input_files([str(path) for path in paths])
    idle(page)


def camera(page, index=0):
    settle(page)
    return scene_state(page, index)["view"]


def rotate_by_drag(page, index=0, dx=67, dy=31):
    target = canvas(page, index)
    target.scroll_into_view_if_needed()
    box = target.bounding_box()
    x, y = box["x"] + box["width"] * 0.45, box["y"] + box["height"] * 0.45
    initial = camera(page, index)
    page.mouse.move(x, y)
    page.mouse.down()
    page.mouse.move(x + dx, y + dy, steps=12)
    page.mouse.up()
    page.wait_for_timeout(100)
    changed = camera(page, index)
    require(max(abs(a - b) for a, b in zip(initial, changed)) > 1e-4,
            "A real pointer drag did not rotate the molecular camera.")
    return changed


def assert_overview_state(page, expect, expected_camera):
    edit_panel(page)
    expect(page.get_by_test_id("review-note")).to_have_value(NOTE)
    expect(page.get_by_test_id("selected-cutoff")).to_have_value("2.35")
    open_settings(page)
    expect(page.get_by_test_id("viewer-representation")).to_have_value("stick")
    expect(page.get_by_test_id("viewer-projection")).to_have_value("orthographic")
    expect(page.get_by_test_id("viewer-quality")).to_have_value("light")
    expect(viewer(page).locator(".molecule-toolbar select")).to_have_value("1")
    assert_camera_equal(expected_camera, camera(page), "Overview camera changed across navigation.")


def check_drafts_and_navigation(page, expect):
    uploaded_files(page, [CASE / "water.cif", ROOT / "examples" / "graphene.cif"])
    choose_source(page, "water.cif")
    initial = workspace(page)
    original = entry_by_name(initial, "water.cif")
    edit_panel(page)
    page.get_by_test_id("review-note").fill(NOTE)
    page.get_by_test_id("selected-cutoff").fill("2.35")
    expect(page.get_by_test_id("draft-status")).to_be_visible()
    expect(page.get_by_test_id("project-export")).to_be_enabled()
    open_settings(page)
    page.get_by_test_id("viewer-representation").select_option("stick")
    page.get_by_test_id("viewer-projection").select_option("orthographic")
    page.get_by_test_id("viewer-quality").select_option("light")
    viewer(page).locator(".molecule-toolbar select").select_option("1")
    saved_camera = rotate_by_drag(page)
    page.get_by_test_id("nav-compare").click()
    page.get_by_role("button", name="Method notes", exact=True).click()
    overview(page)
    assert_overview_state(page, expect, saved_camera)
    choose_source(page, "graphene.cif")
    edit_panel(page)
    page.get_by_test_id("review-note").fill(SECOND_NOTE)
    page.get_by_test_id("selected-cutoff").fill("1.35")
    choose_source(page, "water.cif")
    assert_overview_state(page, expect, saved_camera)
    current = entry_by_name(workspace(page), "water.cif")
    require(current["note"] == original["note"] and current["short_distance"] == original["short_distance"],
            "Unapplied draft changed the applied analysis settings.")
    return {"overview_camera": saved_camera, "water_id": original["id"],
            "water_sha256": original["sha256"], "applied_cutoff": original["short_distance"],
            "applied_note": original["note"], "drafts_are_file_keyed": True}


def select_dataset(page, index, test_id, text):
    select = viewer(page, index).get_by_test_id(test_id)
    options = select.locator("option").evaluate_all(
        "nodes => nodes.map(node => ({text:node.textContent, value:node.value}))",
    )
    matches = [option["value"] for option in options if text in option["text"]]
    require(len(matches) == 1, f"Dataset selector does not uniquely identify {text}: {options!r}")
    select.select_option(matches[0])
    settle(page)
    return matches[0]


def apply_surface(page, index, level="0.05", opacity="0.55"):
    current = viewer(page, index)
    current.get_by_test_id("viewer-isovalue").fill(level)
    current.get_by_test_id("viewer-opacity").fill(opacity)
    current.get_by_test_id("viewer-surface-apply").click()
    settle(page)


def import_real_files(page, expect):
    open_auxiliary(page)
    for method, name in (("mulliken", "Mulliken RHF/STO-3G"), ("lowdin", "Lowdin RHF/STO-3G")):
        page.get_by_test_id("charge-name").fill(name)
        import_file(page, "charge-import", f"charges_{method}.json",
                    (CASE / f"charges_{method}.json").read_bytes())
        expect(page.get_by_test_id("auxiliary-error")).to_have_count(0)
    for name, kind, units in (("density", "density", "e/bohr^3"),
                              ("homo", "orbital", "bohr^-3/2")):
        page.get_by_test_id("volume-kind").select_option(kind)
        page.get_by_test_id("volume-units").select_option(units)
        page.get_by_test_id("volume-source").fill("PySCF 2.12.0; isolated H2O RHF/STO-3G")
        page.get_by_test_id("volume-name").fill("RHF density" if name == "density" else "RHF HOMO MO5")
        import_file(page, "volume-import", f"{name}.cube", (CASE / f"{name}.cube").read_bytes(),
                    "text/plain")
        expect(page.get_by_test_id("auxiliary-error")).to_have_count(0)
    expect(page.get_by_test_id("clear-charge-partial_charge")).to_have_count(2)
    expect(page.get_by_test_id("clear-volume")).to_have_count(2)


def check_real_data(page, expect, output):
    import_real_files(page, expect)
    open_settings(page)
    page.get_by_test_id("viewer-color").select_option("partial_charge")
    select_dataset(page, 0, "viewer-charge-dataset", "Mulliken RHF/STO-3G")
    select_dataset(page, 0, "viewer-volume-dataset", "RHF HOMO MO5")
    instrument(page)
    apply_surface(page, 0)
    page.wait_for_function("() => window.__featureProbe.isosurfaces.length === 2")
    surfaces = page.evaluate("""() => window.__featureProbe.isosurfaces.map(item => ({
        isoval:item.isoval, count:item.count, finite:item.finite,
        vertices:item.shape.geo.geometryGroups.reduce((sum, group) => sum + group.vertices, 0)
    }))""")
    require(all(item["count"] == 27_000 and item["finite"] and item["vertices"] > 0
                for item in surfaces), "Actual HOMO Cube did not create populated signed surfaces.")
    require(sorted(item["isoval"] for item in surfaces) == [-0.05, 0.05],
            "Actual HOMO surface used a different threshold or lost one sign.")
    with page.expect_download() as pending:
        page.get_by_test_id("viewer-export-png").click()
    png = output / "water-homo.png"
    pending.value.save_as(png)
    png_detail = png_header(png)
    require(max(png_detail["width"], png_detail["height"]) == 1600,
            "Actual water PNG export did not use the selected resolution.")
    page.screenshot(path=str(output / "water-overview.png"), full_page=True)
    return {"charge_datasets": 2, "volume_datasets": 2, "orbital_surfaces": surfaces,
            "png": png_detail, "overview_camera_after_import": camera(page)}


def oxygen_colors(page):
    return [canvas(page, index).evaluate("""element => {
        const atom=element._3dmol_viewer.getModel(0).selectedAtoms({}).find(atom =>
            atom.properties.calclensIndex === 0 && atom.properties.calclensShift.join() === '0,0,0');
        const style=atom.style.sphere;
        const ctx=document.createElement('canvas').getContext('2d');
        ctx.fillStyle=style.colorfunc ? style.colorfunc(atom) : style.color;
        return ctx.fillStyle;
    }""") for index in (0, 1)]


def check_comparison(page, expect, water_id, output):
    page.get_by_test_id("nav-compare").click()
    page.get_by_test_id("compare-before").select_option(water_id)
    page.get_by_test_id("compare-after").select_option(water_id)
    for index in (0, 1):
        open_settings(page, index)
        viewer(page, index).get_by_test_id("viewer-color").select_option("partial_charge")
        viewer(page, index).get_by_test_id("viewer-representation").select_option("ball-stick")
    left = select_dataset(page, 0, "viewer-charge-dataset", "Mulliken RHF/STO-3G")
    right = select_dataset(page, 1, "viewer-charge-dataset", "Lowdin RHF/STO-3G")
    require(left != right, "Two methods on the same structure shared one dataset selection.")
    page.get_by_test_id("compare-range-mode").select_option("shared")
    expect(page.get_by_test_id("shared-range")).to_contain_text("0.365509")
    shared_colors = oxygen_colors(page)
    require(shared_colors[0] != shared_colors[1],
            "Two unequal oxygen charges acquired identical colors on the shared range.")
    page.get_by_test_id("compare-range-mode").select_option("manual")
    page.get_by_test_id("compare-range-min").fill("-0.5")
    page.get_by_test_id("compare-range-max").fill("0.75")
    expect(page.get_by_test_id("shared-range")).to_contain_text("-0.5 … 0.75")
    for index in (0, 1):
        expect(viewer(page, index).get_by_test_id("viewer-legend")).to_contain_text(
            "Color range set by comparison",
        )
    density = select_dataset(page, 0, "viewer-volume-dataset", "RHF density")
    homo = select_dataset(page, 1, "viewer-volume-dataset", "RHF HOMO MO5")
    apply_surface(page, 0, opacity="0.4")
    apply_surface(page, 1)
    expect(viewer(page, 0).get_by_test_id("viewer-volume-enabled")).to_be_checked()
    expect(viewer(page, 1).get_by_test_id("viewer-volume-enabled")).to_be_checked()
    left_camera = rotate_by_drag(page, 0)
    right_camera = rotate_by_drag(page, 1, dx=-43, dy=51)
    require(max(abs(a - b) for a, b in zip(left_camera, right_camera)) > 1e-4,
            "Independent left/right camera interactions did not retain different views.")
    page.get_by_role("button", name="Method notes", exact=True).click()
    page.get_by_test_id("nav-compare").click()
    for index in (0, 1):
        open_settings(page, index)
    assert_camera_equal(left_camera, camera(page, 0), "Left comparison camera was lost.")
    assert_camera_equal(right_camera, camera(page, 1), "Right comparison camera was lost.")
    expect(viewer(page, 0).get_by_test_id("viewer-charge-dataset")).to_have_value(left)
    expect(viewer(page, 1).get_by_test_id("viewer-charge-dataset")).to_have_value(right)
    page.screenshot(path=str(output / "water-method-comparison.png"), full_page=True)
    return {"left_charge": left, "right_charge": right, "left_volume": density,
            "right_volume": homo, "left_camera": left_camera, "right_camera": right_camera,
            "shared_oxygen_colors": shared_colors, "manual_range": [-0.5, 0.75]}


def check_zip_roundtrip(page, expect, drafts, comparison, output):
    path = _download(page, page.get_by_test_id("project-export-global"),
                     output / "water-research.calclens.zip")
    require(zipfile.is_zipfile(path), "Save project did not download ZIP bytes.")
    saved = read_project_document(path)
    require(saved["schema_version"] == 3, "Research project did not use schema 3.")
    water = entry_by_name(saved, "water.cif")
    state = saved["workspace_state"]
    draft = state["drafts"][drafts["water_id"]]
    require(draft["note"] == NOTE and draft["cutoff"] == "2.35",
            "Save project lost the unapplied water draft.")
    graphene = entry_by_name(saved, "graphene.cif")
    require(state["drafts"][graphene["id"]]["note"] == SECOND_NOTE,
            "Save project lost the separate graphene draft.")
    require(water["note"] == drafts["applied_note"]
            and water["short_distance"] == drafts["applied_cutoff"],
            "ZIP save silently applied the draft.")
    data = state["auxiliary"][drafts["water_sha256"]]
    require(len(data["charges"]) == len(data["volumes"]) == 2,
            "Saved project did not preserve all four actual electronic datasets.")
    for dataset in data["charges"] + data["volumes"]:
        require(dataset["rawText"].encode("utf-8") == (CASE / dataset["filename"]).read_bytes(),
                f"Saved project changed the authoritative file: {dataset['filename']}")
    uploaded_files(page, [ROOT / "examples" / "graphene.cif"])
    page.get_by_test_id("project-import").set_input_files(str(path))
    idle(page)
    expect(page.locator(".comparison-grid")).to_be_visible()
    for index, charge, volume_id, expected_camera in (
        (0, comparison["left_charge"], comparison["left_volume"], comparison["left_camera"]),
        (1, comparison["right_charge"], comparison["right_volume"], comparison["right_camera"]),
    ):
        open_settings(page, index)
        current = viewer(page, index)
        expect(current.get_by_test_id("viewer-charge-dataset")).to_have_value(charge)
        expect(current.get_by_test_id("viewer-volume-dataset")).to_have_value(volume_id)
        expect(current.get_by_test_id("viewer-volume-enabled")).to_be_checked()
        expect(current.get_by_test_id("viewer-isovalue")).to_have_value("0.05")
        assert_camera_equal(expected_camera, camera(page, index), "ZIP reopen lost comparison camera.")
    expect(page.get_by_test_id("compare-range-mode")).to_have_value("manual")
    expect(page.get_by_test_id("compare-range-min")).to_have_value("-0.5")
    expect(page.get_by_test_id("compare-range-max")).to_have_value("0.75")
    overview(page)
    assert_overview_state(page, expect, drafts["overview_camera"])
    open_auxiliary(page)
    expect(page.get_by_test_id("clear-charge-partial_charge")).to_have_count(2)
    expect(page.get_by_test_id("clear-volume")).to_have_count(2)
    page.screenshot(path=str(output / "water-reopened.png"), full_page=True)
    return saved


def check_invalid_binding(page, expect, saved, output, requests):
    damaged = json.loads(json.dumps(saved))
    source = next(iter(damaged["workspace_state"]["auxiliary"].values()))
    charge = json.loads(source["charges"][0]["rawText"])
    charge["structure_sha256"] = "0" * 64
    source["charges"][0]["rawText"] = json.dumps(charge)
    path = output / "deliberately-invalid-binding.calclens.zip"
    with zipfile.ZipFile(path, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("project.json", json.dumps(damaged, ensure_ascii=False))
    before = workspace(page)
    imports = sum(url.endswith("/api/v1/project/import") for url in requests)
    page.get_by_test_id("project-import").set_input_files(str(path))
    expect(page.locator(".notice.error")).to_contain_text("SHA-256")
    idle(page)
    after = workspace(page)
    require(after["revision"] == before["revision"] and after["entries"] == before["entries"],
            "Invalid saved electronic data replaced the existing server workspace.")
    require(sum(url.endswith("/api/v1/project/import") for url in requests) == imports,
            "Invalid binding passed preflight and reached the mutating project-import endpoint.")
    expect(page.get_by_test_id("review-note")).to_have_value(NOTE)
    expect(page.get_by_test_id("clear-volume")).to_have_count(2)
    return {"negative_fixture": path.name, "preflight_rejected": True,
            "server_revision_unchanged": after["revision"], "existing_draft_and_data_preserved": True}


def check_pending_export_keeps_later_edits_unsaved(page, expect, output):
    """A completed older snapshot must not mark newer local work as saved."""
    overview(page)
    open_settings(page)
    before_camera = camera(page)
    before_representation = page.get_by_test_id("viewer-representation").input_value()
    changed_representation = "spacefill" if before_representation != "spacefill" else "stick"
    pending_routes = []
    pattern = "**/api/v1/project/export"

    def hold_export(route):
        pending_routes.append(route)

    released = False
    page.route(pattern, hold_export)
    try:
        with page.expect_request(pattern):
            page.get_by_test_id("project-export-global").click()
        page.wait_for_timeout(100)
        require(len(pending_routes) == 1, "The export request was not held for the regression.")
        expect(page.get_by_test_id("project-export-global")).to_be_disabled()
        page.get_by_test_id("viewer-representation").select_option(changed_representation)
        changed_camera = rotate_by_drag(page, dx=-41, dy=-28)
        with page.expect_download(timeout=30_000) as pending:
            pending_routes[0].continue_()
            released = True
        path = output / "snapshot-before-pending-edits.calclens.zip"
        pending.value.save_as(path)
        idle(page)
    finally:
        if pending_routes and not released:
            pending_routes[0].abort()
        page.unroute(pattern, hold_export)

    saved = read_project_document(path)
    entry = next(item for item in saved["entries"] if item["id"] == saved["state"]["selected_id"])
    saved_view = saved["workspace_state"]["viewers"][f"overview:{entry['id']}:{entry['sha256']}"]
    require(saved_view["representation"] == before_representation,
            "The delayed download did not retain its original representation snapshot.")
    assert_camera_equal(before_camera, saved_view["camera"],
                        "The delayed download did not retain its original camera snapshot.")
    expect(page.get_by_test_id("viewer-representation")).to_have_value(changed_representation)
    assert_camera_equal(changed_camera, camera(page), "Completing export overwrote newer camera work.")

    before_replace = workspace(page)
    dialogs = []

    def dismiss_unsaved(dialog):
        dialogs.append({"type": dialog.type, "message": dialog.message})
        dialog.dismiss()

    page.remove_listener("dialog", accept_workspace_dialog)
    page.on("dialog", dismiss_unsaved)
    try:
        page.get_by_role("combobox", name="Try sample").select_option("hbn.cif")
        with page.expect_event("dialog", timeout=5_000):
            page.get_by_role("button", name="Try sample", exact=True).click()
    finally:
        page.remove_listener("dialog", dismiss_unsaved)
        page.on("dialog", accept_workspace_dialog)
    require(len(dialogs) == 1 and dialogs[0]["type"] == "confirm"
            and "unsaved workspace" in dialogs[0]["message"],
            f"Newer edits did not retain an explicit replacement warning: {dialogs!r}")
    after_replace = workspace(page)
    require(after_replace["revision"] == before_replace["revision"]
            and after_replace["entries"] == before_replace["entries"],
            "Dismissing the replacement warning changed the existing workspace.")
    expect(page.get_by_test_id("viewer-representation")).to_have_value(changed_representation)
    assert_camera_equal(changed_camera, camera(page), "Dismissing replacement lost the newer camera.")
    return {"download_retains_old_snapshot": True, "new_representation": changed_representation,
            "later_camera_preserved": True, "replacement_warning_dismissed": dialogs[0],
            "workspace_unchanged_after_dismiss": True}


def check_same_identity_reopen_restores_saved_camera(page, expect, output):
    """Reopening the current project must replace its viewer's live camera."""
    overview(page)
    open_settings(page)
    saved_camera = camera(page)
    saved_representation = page.get_by_test_id("viewer-representation").input_value()
    identity = [(entry["id"], entry["sha256"]) for entry in workspace(page)["entries"]]
    path = _download(page, page.get_by_test_id("project-export-global"),
                     output / "same-identity-saved-camera.calclens.zip")
    changed_camera = rotate_by_drag(page, dx=49, dy=-43)
    require(max(abs(a - b) for a, b in zip(saved_camera, changed_camera)) > 1e-4,
            "The same-identity reopen test did not first change the live camera.")
    old_canvas = canvas(page).element_handle()
    # Import directly: no sample load, source replacement or entry-ID change.
    page.get_by_test_id("project-import").set_input_files(str(path))
    idle(page)
    page.wait_for_function("""() => {
        const canvas=document.querySelector('[data-testid="molecule-canvas"] canvas');
        return Boolean(canvas?._3dmol_viewer);
    }""")
    page.wait_for_timeout(100)
    require([(entry["id"], entry["sha256"]) for entry in workspace(page)["entries"]] == identity,
            "The same-identity reopen unexpectedly replaced entry identities.")
    old_canvas_retired = old_canvas.evaluate("element => !element.isConnected")
    open_settings(page)
    expect(page.get_by_test_id("viewer-representation")).to_have_value(saved_representation)
    assert_camera_equal(saved_camera, camera(page),
                        "The old live viewer overwrote the archived camera on same-identity reopen.")
    page.screenshot(path=str(output / "same-identity-camera-restored.png"), full_page=True)
    return {"entry_ids_and_hashes_unchanged": True, "old_live_viewer_retired": old_canvas_retired,
            "archived_camera_restored": True, "camera": saved_camera}


def check_p1_preparation(page, expect, output):
    source_path = ROOT / "examples" / "public_case" / "source" / "9011577-rev291877.cif"
    source = source_path.read_bytes()
    uploaded_files(page, [source_path])
    before = workspace(page)
    require(before["entries"][0]["analysis"]["report"] is None,
            "The unexpanded graphite source was silently treated as ordinary P1.")
    panel = page.get_by_test_id("p1-panel")
    expect(panel).to_have_count(1)
    if not panel.evaluate("element => element.open"):
        panel.locator("summary").click()
    page.get_by_test_id("p1-preview").click()
    expect(page.get_by_test_id("p1-result")).to_contain_text("2 → 4")
    preview = workspace(page)
    require(preview["revision"] == before["revision"]
            and preview["entries"][0]["sha256"] == sha256(source).hexdigest(),
            "P1 preview changed the original workspace before explicit Apply.")
    page.get_by_test_id("p1-apply").click()
    idle(page)
    prepared = workspace(page)["entries"][0]
    require(prepared["analysis"]["report"]["atom_count"] == 4,
            "Applied graphite P1 preparation did not produce four explicit sites.")
    require(prepared["preparation"]["source_sha256"] == sha256(source).hexdigest(),
            "P1 preparation lost the original source identity.")
    path = _download(page, page.get_by_test_id("project-export-global"),
                     output / "graphite-prepared.calclens.zip")
    saved = read_project_document(path)
    record = saved["entries"][0]["preparation"]
    require(base64.b64decode(record["source"]["cif_base64"]) == source,
            "Prepared project did not retain the exact original graphite source bytes.")
    uploaded_files(page, [CASE / "water.cif"])
    page.get_by_test_id("project-import").set_input_files(str(path))
    idle(page)
    reopened = workspace(page)["entries"][0]
    require(reopened["sha256"] == prepared["sha256"]
            and reopened["analysis"]["report"]["atom_count"] == 4,
            "P1 project lost the prepared structure on reopen.")
    restored = _download(page, page.get_by_test_id("project-export-global"),
                         output / "graphite-prepared-reopened.calclens.zip")
    require(read_project_document(restored)["entries"][0]["preparation"] == record,
            "P1 project lost original source or conversion history on reopen.")
    page.screenshot(path=str(output / "graphite-prepared-reopened.png"), full_page=True)
    return {"source_sites": 2, "prepared_sites": 4, "original_bytes_preserved": True,
            "preview_nonmutating": True, "project_roundtrip": True}


def create_curated_example(page, expect, output):
    """Build a clean, practical saved project through the same visible controls."""
    output.mkdir(parents=True, exist_ok=True)
    uploaded_files(page, [CASE / "water.cif"])
    choose_source(page, "water.cif")
    import_real_files(page, expect)
    open_settings(page)
    viewer(page).locator(".molecule-toolbar select").select_option("1")
    page.get_by_test_id("viewer-color").select_option("partial_charge")
    select_dataset(page, 0, "viewer-charge-dataset", "Mulliken RHF/STO-3G")
    water_id = workspace(page)["entries"][0]["id"]
    page.get_by_test_id("nav-compare").click()
    page.get_by_test_id("compare-before").select_option(water_id)
    page.get_by_test_id("compare-after").select_option(water_id)
    page.get_by_test_id("compare-range-mode").select_option("shared")
    images = []
    selections = []
    for index, method, volume_name, filename in (
        (0, "Mulliken RHF/STO-3G", "RHF density", "real-water-density.png"),
        (1, "Lowdin RHF/STO-3G", "RHF HOMO MO5", "real-water-homo.png"),
    ):
        open_settings(page, index)
        current = viewer(page, index)
        current.locator(".molecule-toolbar select").select_option("1")
        current.get_by_test_id("viewer-color").select_option("partial_charge")
        current.get_by_test_id("viewer-representation").select_option("ball-stick")
        current.get_by_test_id("viewer-quality").select_option("balanced")
        charge_id = select_dataset(page, index, "viewer-charge-dataset", method)
        volume_id = select_dataset(page, index, "viewer-volume-dataset", volume_name)
        apply_surface(page, index, opacity="0.35")
        current.get_by_title("Fit atoms", exact=True).click()
        page.wait_for_timeout(450)
        # Public 3Dmol zoom, equivalent to a wheel gesture: water is much smaller
        # than the minimum radius used by zoomTo's default framing.
        canvas(page, index).evaluate("""element => {
            const viewer=element._3dmol_viewer;
            // The molecule lies in yz; tilt away from the slab's z-normal
            // default so the H-O-H angle and the two HOMO lobes are both visible.
            viewer.rotate(60, 'y').rotate(-15, 'z').zoom(2.7).render();
        }""")
        settle(page)
        view = camera(page, index)
        with page.expect_download() as pending:
            current.get_by_test_id("viewer-export-png").click()
        pending.value.save_as(output / filename)
        assert_camera_equal(view, camera(page, index), "Curated PNG export changed the camera.")
        images.append({"filename": filename, **png_header(output / filename)})
        selections.append({"charge": charge_id, "volume": volume_id})
    page.screenshot(path=str(output / "real-water-comparison.png"), full_page=True)
    page.locator(".comparison-grid").screenshot(path=str(output / "real-water-viewers.png"))
    path = _download(page, page.get_by_test_id("project-export-global"),
                     output / "real-water.calclens.zip")
    saved = read_project_document(path)
    require(len(saved["entries"]) == 1 and saved["entries"][0]["filename"] == "water.cif",
            "Curated example includes unrelated test structures.")
    require(saved["workspace_state"]["drafts"] == {} and saved["entries"][0]["note"] == "",
            "Curated example retained smoke-test drafts or notes.")
    require(saved["workspace_state"]["comparison"]["rangeMode"] == "shared",
            "Curated example does not use the common charge range.")
    require(selections[0]["charge"] != selections[1]["charge"],
            "Curated example did not retain the two distinct charge methods.")
    return {"project": str(path), "images": images, "notes_and_drafts": "empty",
            "charge_range": "shared", "surface_isovalue": 0.05, "surface_opacity": 0.35}


def run(base_url, output, example_output=None):
    from playwright.sync_api import expect, sync_playwright

    output.mkdir(parents=True, exist_ok=True)
    events = {"page_errors": [], "console_errors": [], "external_requests": []}
    report = {"status": "failed", "checks": [], "events": events}
    requests = []
    origin = urllib.parse.urlsplit(base_url).netloc
    with sync_playwright() as pw:
        browser = pw.chromium.launch(headless=True, args=[
            "--enable-webgl", "--ignore-gpu-blocklist", "--enable-unsafe-swiftshader",
        ])
        context = browser.new_context(accept_downloads=True,
                                      viewport={"width": 1584, "height": 1100})
        context.set_default_timeout(30_000)
        context.tracing.start(screenshots=True, snapshots=True, sources=False)
        page = context.new_page()
        page.on("dialog", accept_workspace_dialog)
        page.on("pageerror", lambda error: events["page_errors"].append(str(error)))
        page.on("console", lambda message: events["console_errors"].append(message.text)
                if message.type == "error" else None)
        page.on("request", lambda request: requests.append(request.url))
        page.on("request", lambda request: events["external_requests"].append(request.url)
                if urllib.parse.urlsplit(request.url).scheme in ("http", "https")
                and urllib.parse.urlsplit(request.url).netloc != origin else None)

        def record(name, operation):
            print(f"Checking {name}", flush=True)
            detail = operation()
            report["checks"].append({"name": name, "status": "passed", "detail": detail})
            return detail

        try:
            page.goto(base_url, wait_until="domcontentloaded", timeout=60_000)
            idle(page)
            if page.locator("html").get_attribute("lang") == "ko":
                page.get_by_test_id("language-toggle").click()
                idle(page)
            expect(page.locator("html")).to_have_attribute("lang", "en")
            report["inherited_record_filters"] = prepare_record_filters(page, expect)
            drafts = record("file-keyed drafts and persistent overview camera",
                            lambda: check_drafts_and_navigation(page, expect))
            record("actual water multi-dataset imports and signed orbital PNG",
                   lambda: check_real_data(page, expect, output))
            comparison = record("same-structure methods, shared/manual ranges and comparison cameras",
                                lambda: check_comparison(page, expect, drafts["water_id"], output))
            saved = check_zip_roundtrip(page, expect, drafts, comparison, output)
            report["checks"].append({"name": "ZIP reopen retains drafts, real files and viewer state",
                                     "status": "passed", "detail": {"schema": 3, "datasets": 4}})
            record("invalid electronic binding rejected before workspace replacement",
                   lambda: check_invalid_binding(page, expect, saved, output, requests))
            record("late camera and representation edits survive a pending project export",
                   lambda: check_pending_export_keeps_later_edits_unsaved(page, expect, output))
            record("same-ID and same-SHA project reopen restores the archived camera",
                   lambda: check_same_identity_reopen_restores_saved_camera(page, expect, output))
            record("original graphite P1 preview, apply, save and reopen",
                   lambda: check_p1_preparation(page, expect, output))
            if example_output is not None:
                record("clean actual-water project and native PNG deliverables",
                       lambda: create_curated_example(page, expect, example_output))
            require(not events["page_errors"], f"Browser page errors: {events['page_errors']}")
            require(not events["console_errors"], f"Browser console errors: {events['console_errors']}")
            require(not events["external_requests"], "Research workspace requested external resources.")
            report["status"] = "passed"
        except Exception as error:
            report["error"] = str(error)
            report["traceback"] = traceback.format_exc()
            page.screenshot(path=str(output / "failure.png"), full_page=True)
            raise
        finally:
            (output / "report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2),
                                                encoding="utf-8")
            context.tracing.stop(path=str(output / "research-workspace-trace.zip"))
            context.close()
            browser.close()
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--url", help="Existing isolated local workspace server")
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--example-output", type=Path,
                        help="Also create a clean real-water project and comparison/native PNGs")
    args = parser.parse_args()
    example_output = args.example_output.resolve() if args.example_output else None
    if args.url:
        result = run(args.url, args.output.resolve(), example_output)
    else:
        with workspace_server() as url:
            result = run(url, args.output.resolve(), example_output)
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
