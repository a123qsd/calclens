"""Run focused CalcLens workspace regressions in a real Chromium/WebGL session."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import re
import sys
import threading
import traceback
import urllib.parse

from smoke_workspace import accept_workspace_dialog


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_OUTPUT = ROOT.parent.parent / "work" / "browser" / "workspace-regressions"
sys.path.insert(0, str(ROOT / "src"))


def require(condition: object, message: str) -> None:
    if not condition:
        raise AssertionError(message)


def _origin(url: str) -> tuple[str, str | None, int]:
    parsed = urllib.parse.urlsplit(url)
    return parsed.scheme, parsed.hostname, parsed.port or (443 if parsed.scheme == "https" else 80)


def _idle(page, expect) -> None:
    expect(page.get_by_test_id("app-ready")).to_be_visible(timeout=60_000)
    expect(page.locator('[aria-label="Working"]')).to_have_count(0, timeout=60_000)
    page.wait_for_timeout(100)


def _details(page, label: str):
    return page.locator("details.tool-card").filter(has=page.get_by_text(label, exact=True))


def _open_details(details) -> None:
    if not details.evaluate("element => element.open"):
        details.locator("summary").click()


def _canvas(page):
    return page.get_by_test_id("molecule-canvas").first.locator("canvas").first


def _workspace(page) -> dict:
    return page.evaluate(
        "async () => (await fetch('/api/v1/workspace', {cache: 'no-store'})).json()"
    )


def _wait_for_note(page, expected: str) -> None:
    page.wait_for_function(
        """async expected => {
            const response = await fetch('/api/v1/workspace', {cache: 'no-store'});
            const workspace = await response.json();
            const selected = workspace.entries.find(
                entry => entry.id === workspace.project.selected_id
            );
            return selected?.note === expected;
        }""",
        arg=expected,
        timeout=30_000,
    )


def _load_example(page, expect, name: str) -> None:
    page.get_by_role("combobox", name="Try sample").select_option(name)
    page.get_by_role("button", name="Try sample", exact=True).click()
    expect(page.locator(".breadcrumb")).to_contain_text(name, timeout=60_000)
    _idle(page, expect)


def _view(page) -> list[float]:
    return _canvas(page).evaluate("element => element._3dmol_viewer.getView()")


def _max_delta(left: list[float], right: list[float]) -> float:
    return max(abs(a - b) for a, b in zip(left, right, strict=True))


def _check_viewer_camera(page, expect) -> dict:
    _load_example(page, expect, "graphene.cif")
    toolbar = page.get_by_role("toolbar", name="3D viewer tools")
    canvas = _canvas(page)
    expect(canvas).to_be_visible()
    canvas.evaluate(
        """element => {
            const viewer = element._3dmol_viewer;
            const original = viewer.zoomTo.bind(viewer);
            viewer.__calclensZoomCalls = [];
            viewer.zoomTo = (selection, duration) => {
                viewer.__calclensZoomCalls.push({selection, duration});
                return original(selection, duration);
            };
        }"""
    )
    toolbar.get_by_title("Fit cell", exact=True).click()
    page.wait_for_timeout(450)
    toolbar.get_by_title("Fit atoms", exact=True).click()
    page.wait_for_timeout(450)
    zoom_calls = canvas.evaluate("element => element._3dmol_viewer.__calclensZoomCalls")
    require(zoom_calls[-2]["selection"] == {"model": 1},
            "Fit cell did not target the dedicated corner model.")
    require(zoom_calls[-1]["selection"] == {"model": 0},
            "Fit atoms did not target the repeated atom model.")

    toolbar.get_by_title("Rotate", exact=True).click()
    expect(toolbar.get_by_title("Stop rotation", exact=True)).to_be_visible()
    page.wait_for_timeout(650)
    rotated = _view(page)
    toolbar.get_by_title("Stop rotation", exact=True).click()
    toolbar.get_by_title("Reset", exact=True).click()
    page.wait_for_timeout(100)
    reset_once = _view(page)
    toolbar.get_by_title("Reset", exact=True).click()
    page.wait_for_timeout(100)
    reset_twice = _view(page)
    require(_max_delta(rotated, reset_once) > 1e-4,
            "Rotate did not produce a camera state that Reset could restore.")
    require(_max_delta(reset_once, reset_twice) < 1e-7,
            "Reset changed the camera when invoked a second time.")
    return {
        "fit_cell_selection": zoom_calls[-2]["selection"],
        "fit_atoms_selection": zoom_calls[-1]["selection"],
        "reset_idempotence_max_delta": _max_delta(reset_once, reset_twice),
    }


def _pick_repeated_atom(page, expect) -> dict:
    page.evaluate("window.scrollTo(0, 0)")
    canvas = _canvas(page)
    point = canvas.evaluate(
        """element => {
            const viewer = element._3dmol_viewer;
            const atom = viewer.getModel(0).selectedAtoms({}).find(candidate => {
                const properties = candidate.properties ?? {};
                const shift = properties.calclensShift;
                return properties.calclensIndex === 0 && Array.isArray(shift) &&
                    shift[0] === 1 && shift[1] === 0 && shift[2] === 0;
            });
            if (!atom) return null;
            const projected = viewer.modelToScreen(atom);
            return {x: projected.x - window.scrollX, y: projected.y - window.scrollY};
        }"""
    )
    require(point is not None, "The repeated image atom C1 [1, 0, 0] was not rendered.")
    viewport = page.viewport_size
    require(0 < point["x"] < viewport["width"] and 0 < point["y"] < viewport["height"],
            f"Projected atom is outside the viewport: {point!r}")
    page.mouse.click(point["x"], point["y"])
    expect(page.locator(".molecule-status")).to_contain_text("Selected: C1 · [1, 0, 0]")
    return point


def _assert_pair_fields_reset(page, expect, measurement) -> None:
    expect(page.get_by_test_id("measure-first-index")).to_have_value("0")
    expect(page.get_by_test_id("measure-second-index")).to_have_value("1")
    shift_inputs = measurement.locator("fieldset.shift-fields input")
    require(shift_inputs.count() == 6, "Atom image-shift fields are missing.")
    for index in range(6):
        expect(shift_inputs.nth(index)).to_have_value("0")


def _check_atom_pick_and_input_reset(page, expect) -> dict:
    _pick_repeated_atom(page, expect)

    measurement = _details(page, "Measure atom pair")
    _open_details(measurement)
    expect(page.get_by_test_id("measure-first-index")).to_have_value("0")
    first_shift = measurement.locator("fieldset.shift-fields").nth(0).locator("input")
    require(first_shift.count() == 3, "First atom image-shift fields are missing.")
    expect(first_shift.nth(0)).to_have_value("1")
    expect(first_shift.nth(1)).to_have_value("0")
    expect(first_shift.nth(2)).to_have_value("0")

    settings = _details(page, "Edit selected structure")
    _open_details(settings)
    cutoff = page.get_by_test_id("selected-cutoff")
    cutoff.fill("2.25")
    settings.get_by_role("button", name="Apply changes", exact=True).click()
    expect(settings.locator("summary")).to_contain_text("2.25 Å", timeout=60_000)
    _idle(page, expect)
    expect(page.locator(".molecule-status")).not_to_contain_text("Selected:")
    expect(page.locator(".molecule-status")).to_contain_text(
        "Drag to rotate and select an atom."
    )
    _assert_pair_fields_reset(page, expect, measurement)

    _pick_repeated_atom(page, expect)
    before_replacement = _workspace(page)
    before_entry = next(
        entry for entry in before_replacement["entries"]
        if entry["id"] == before_replacement["project"]["selected_id"]
    )
    replacement_bytes = (
        (ROOT / "examples" / "graphene.cif").read_bytes()
        + b"\n# Identical coordinates, distinct source bytes for viewer identity regression.\n"
    )
    with page.expect_file_chooser() as pending:
        settings.get_by_role("button", name="Replace source", exact=True).click()
    pending.value.set_files({
        "name": "graphene_same_geometry.cif",
        "mimeType": "chemical/x-cif",
        "buffer": replacement_bytes,
    })
    expect(page.locator(".breadcrumb")).to_contain_text(
        "graphene_same_geometry.cif", timeout=60_000
    )
    _idle(page, expect)
    after_replacement = _workspace(page)
    after_entry = next(
        entry for entry in after_replacement["entries"]
        if entry["id"] == after_replacement["project"]["selected_id"]
    )
    require(after_entry["id"] == before_entry["id"],
            "Same-entry source replacement changed the entry ID.")
    require(after_entry["sha256"] != before_entry["sha256"],
            "Distinct source bytes did not change the entry identity hash.")
    require(after_entry["analysis"]["report"]["positions"]
            == before_entry["analysis"]["report"]["positions"],
            "The identity-only replacement unexpectedly changed atomic coordinates.")
    expect(page.locator(".molecule-status")).not_to_contain_text("Selected:")
    _assert_pair_fields_reset(page, expect, measurement)

    _pick_repeated_atom(page, expect)

    page.get_by_test_id("measure-first-index").fill("0.5")
    page.get_by_test_id("measure-second-index").fill("1")
    page.get_by_test_id("measure-pair").click()
    expect(page.locator(".notice.error")).to_contain_text(
        "Choose two different integer atom indices from 0 to 1."
    )
    expect(measurement.locator(".measurement-result")).to_have_count(0)

    page.get_by_role("combobox", name="Repeat").select_option("2")
    expect(page.locator(".molecule-status")).to_contain_text(
        "Drag to rotate and select an atom."
    )
    _load_example(page, expect, "hbn.cif")
    measurement = _details(page, "Measure atom pair")
    _open_details(measurement)
    expect(page.locator(".molecule-status")).not_to_contain_text("Selected:")
    _assert_pair_fields_reset(page, expect, measurement)
    return {"picked": "C1 · [1, 0, 0]", "fractional_index_rejected": True,
            "cutoff_only_reset": True, "same_geometry_new_bytes_reset": True,
            "source_switch_shift": [0, 0, 0]}


def _check_review_semantics(page, expect, output: Path) -> dict:
    _load_example(page, expect, "graphene_duplicate.cif")
    minimum = page.locator("button.check-row").filter(
        has=page.get_by_text("Minimum periodic distance", exact=True)
    )
    gap = page.locator("button.check-row").filter(
        has=page.get_by_text("Candidate nuclear gap", exact=True)
    )
    expect(minimum).to_be_visible()
    expect(gap).to_be_visible()
    minimum_class = minimum.locator(".status-mark").get_attribute("class") or ""
    gap_class = gap.locator(".status-mark").get_attribute("class") or ""
    require("status-clear" not in minimum_class,
            "An overlapping-site minimum was incorrectly shown as green.")
    require("status-clear" in gap_class,
            "A clean nuclear-gap check was not shown as green.")

    _load_example(page, expect, "partial_occupancy.cif")
    page.get_by_role("button", name="Review checks", exact=True).click()
    expect(page.locator(".issue-error")).to_be_visible()
    expect(page.locator(".all-clear")).to_have_count(0)

    _load_example(page, expect, "no_unique_gap.cif")
    page.get_by_role("button", name="Review checks", exact=True).click()
    issue = page.locator("button.issue").filter(
        has=page.get_by_text("AMBIGUOUS SLAB", exact=True)
    )
    expect(issue).to_be_visible()
    issue.click()
    expect(page.get_by_role("heading", name="Structure preflight", exact=True)).to_be_visible()
    _idle(page, expect)
    page.wait_for_function(
        """() => {
            const canvas = document.querySelector('[data-testid="molecule-canvas"] canvas');
            const viewer = canvas?._3dmol_viewer;
            return viewer?.models?.length === 2 &&
                viewer.getModel(1).selectedAtoms({}).length >= 16;
        }""",
        timeout=30_000,
    )
    model_summary = _canvas(page).evaluate(
        """element => {
            const viewer = element._3dmol_viewer;
            return {models: viewer.models.length,
                atoms: viewer.getModel(0).selectedAtoms({}).length,
                cornersAndGapVertices: viewer.getModel(1).selectedAtoms({}).length};
        }"""
    )
    require(model_summary["models"] == 2, "Gap inspection created an unexpected model count.")
    require(model_summary["cornersAndGapVertices"] >= 16,
            "Gap inspection did not add both highlighted boundary planes.")
    page.screenshot(path=str(output / "gap-inspection.png"), full_page=True)
    return {
        "overlap_minimum_class": minimum_class,
        "clean_gap_class": gap_class,
        "unsupported_has_error": True,
        "gap_models": model_summary,
    }


def _check_measure_revision_conflict(context, page, base_url, expect) -> tuple[object, dict]:
    _load_example(page, expect, "graphene.cif")
    second = context.new_page()
    second.goto(base_url, wait_until="domcontentloaded", timeout=60_000)
    _idle(second, expect)
    first_workspace = _workspace(page)
    first_id = first_workspace["project"]["selected_id"]

    measurement = _details(page, "Measure atom pair")
    _open_details(measurement)
    page.get_by_test_id("measure-first-index").fill("0")
    page.get_by_test_id("measure-second-index").fill("1")
    page.get_by_test_id("measure-pair").click()
    expect(measurement.locator(".measurement-result")).to_be_visible()

    settings = _details(second, "Edit selected structure")
    _open_details(settings)
    with second.expect_file_chooser() as pending:
        settings.get_by_role("button", name="Replace source", exact=True).click()
    pending.value.set_files(str(ROOT / "examples" / "hbn.cif"))
    expect(second.locator(".breadcrumb")).to_contain_text("hbn.cif", timeout=60_000)
    _idle(second, expect)
    second_workspace = _workspace(second)
    require(second_workspace["project"]["selected_id"] == first_id,
            "Replace source changed the selected entry ID.")

    page.get_by_test_id("measure-pair").click()
    expect(page.locator(".notice.info")).to_be_visible(timeout=30_000)
    expect(measurement.locator(".measurement-result")).to_have_count(0)
    expect(page.locator(".breadcrumb")).to_contain_text("hbn.cif")
    _idle(page, expect)
    return second, {"entry_id_preserved": first_id, "stale_distance_removed": True}


def _check_note_revision_conflict(first, second, expect) -> dict:
    first.reload(wait_until="domcontentloaded")
    second.reload(wait_until="domcontentloaded")
    _idle(first, expect)
    _idle(second, expect)
    draft_note = "first-tab draft retained after conflict"
    competing_note = "second-tab committed note"

    first_settings = _details(first, "Edit selected structure")
    second_settings = _details(second, "Edit selected structure")
    _open_details(first_settings)
    _open_details(second_settings)
    first.get_by_test_id("review-note").fill(draft_note)
    second.get_by_test_id("review-note").fill(competing_note)
    second_settings.get_by_role("button", name="Apply changes", exact=True).click()
    _wait_for_note(second, competing_note)
    _idle(second, expect)

    first_settings.get_by_role("button", name="Apply changes", exact=True).click()
    recovery = first.locator(".conflict-recovery")
    expect(recovery).to_be_visible(timeout=30_000)
    expect(first.get_by_test_id("review-note")).to_have_value(draft_note)
    expect(recovery.get_by_role("textbox", name="Preserved note")).to_have_value(draft_note)
    require(_workspace(first)["entries"][0]["note"] == competing_note,
            "A stale note overwrote the competing note automatically.")

    recovery.get_by_role("button", name="Reapply after review", exact=True).click()
    expect(recovery).to_have_count(0, timeout=30_000)
    _wait_for_note(first, draft_note)
    expect(first.get_by_test_id("review-note")).to_have_value(draft_note)
    return {"draft_preserved": draft_note, "competing_note_survived_until_reapply": True,
            "explicit_reapply_succeeded": True}


def _check_report_language_and_document(first, expect) -> dict:
    first.get_by_role("button", name="Method notes", exact=True).click()
    report_language = first.get_by_role("combobox", name="Report language")
    expect(report_language).to_be_visible()
    report_language.select_option("ko")
    expect(first.get_by_role("link", name="JSON", exact=True)).to_have_attribute(
        "href", re.compile(r"[?&]lang=ko(?:&|$)")
    )
    first.get_by_test_id("language-toggle").click()
    expect(first.locator("html")).to_have_attribute("lang", "ko")
    _idle(first, expect)
    korean_report_language = first.get_by_role("combobox", name="보고서 언어")
    expect(korean_report_language).to_have_value("ko")
    korean_report_language.select_option("en")
    expect(first.get_by_role("link", name="JSON", exact=True)).to_have_attribute(
        "href", re.compile(r"[?&]lang=en(?:&|$)")
    )
    document_title = first.title()
    require(document_title == "CalcLens · Molecular workspace",
            f"Unexpected document title: {document_title!r}")
    first.get_by_test_id("language-toggle").click()
    expect(first.locator("html")).to_have_attribute("lang", "en")
    _idle(first, expect)
    expect(first.get_by_role("combobox", name="Report language")).to_have_value("en")
    return {"document_title": document_title, "html_languages": ["ko", "en"],
            "report_languages": ["ko", "en"]}


def _check_mobile_layout(page, expect, output: Path) -> dict:
    page.get_by_role("button", name="Overview", exact=True).click()
    page.set_viewport_size({"width": 390, "height": 844})
    page.wait_for_timeout(200)
    geometry = page.get_by_test_id("geometry-filter")
    progress = page.get_by_test_id("progress-filter")
    expect(geometry).to_be_visible()
    expect(progress).to_be_visible()
    overflow = page.evaluate(
        """() => ({
            document: document.documentElement.scrollWidth - document.documentElement.clientWidth,
            body: document.body.scrollWidth - document.body.clientWidth,
        })"""
    )
    require(overflow["document"] <= 1 and overflow["body"] <= 1,
            f"The 390 px layout has horizontal overflow: {overflow!r}")
    for label, locator in (("geometry", geometry), ("progress", progress)):
        box = locator.bounding_box()
        require(box is not None and box["x"] >= 0 and box["x"] + box["width"] <= 391,
                f"The {label} filter is clipped at 390 px.")
    page.screenshot(path=str(output / "mobile-390.png"), full_page=True)
    return {"viewport_width": 390, "overflow": overflow,
            "geometry_visible": True, "progress_visible": True}


def run_regressions(base_url: str, output: Path) -> dict:
    from playwright.sync_api import expect, sync_playwright

    output.mkdir(parents=True, exist_ok=True)
    expect.set_options(timeout=30_000)
    results: list[dict] = []
    events = {key: [] for key in (
        "console_errors", "page_errors", "failed_requests", "http_errors",
        "external_requests",
    )}
    expected_origin = _origin(base_url)

    def record(name: str, operation):
        detail = operation()
        results.append({"name": name, "status": "passed", "detail": detail})
        return detail

    def attach(page) -> None:
        page.on("dialog", accept_workspace_dialog)
        page.on("console", lambda message: events["console_errors"].append({
            "type": message.type, "text": message.text,
        }) if message.type == "error" else None)
        page.on("pageerror", lambda error: events["page_errors"].append(str(error)))
        page.on("requestfailed", lambda request: events["failed_requests"].append({
            "url": request.url, "failure": request.failure,
        }))
        page.on("request", lambda request: events["external_requests"].append(request.url)
                if urllib.parse.urlsplit(request.url).scheme in ("http", "https")
                and _origin(request.url) != expected_origin else None)
        page.on("response", lambda response: events["http_errors"].append({
            "url": response.url, "status": response.status,
        }) if response.status >= 400 and _origin(response.url) == expected_origin else None)

    report = {"status": "failed", "base_url": base_url, "checks": results, "events": events}
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(
            headless=True,
            args=["--enable-webgl", "--ignore-gpu-blocklist", "--enable-unsafe-swiftshader"],
        )
        context = browser.new_context(viewport={"width": 1550, "height": 1050})
        context.set_default_timeout(30_000)
        context.on("page", attach)
        context.tracing.start(screenshots=True, snapshots=True, sources=False)
        page = context.new_page()
        try:
            page.goto(base_url, wait_until="domcontentloaded", timeout=60_000)
            _idle(page, expect)
            expect(page.locator("html")).to_have_attribute("lang", "en")
            record("viewer camera controls", lambda: _check_viewer_camera(page, expect))
            record("atom picking and input reset", lambda: _check_atom_pick_and_input_reset(page, expect))
            record("review semantics and gap inspection",
                   lambda: _check_review_semantics(page, expect, output))
            holder: dict = {}

            def measure_conflict():
                holder["second"], detail = _check_measure_revision_conflict(
                    context, page, base_url, expect
                )
                return detail

            record("measurement revision conflict", measure_conflict)
            second = holder["second"]
            record("note revision conflict", lambda: _check_note_revision_conflict(page, second, expect))
            record("report language and document metadata",
                   lambda: _check_report_language_and_document(page, expect))
            record("mobile layout", lambda: _check_mobile_layout(page, expect, output))
            page.screenshot(path=str(output / "workspace-regressions.png"), full_page=True)

            conflict_errors = [item for item in events["http_errors"] if item["status"] == 409]
            unexpected_http = [item for item in events["http_errors"] if item["status"] != 409]
            require(len(conflict_errors) == 2,
                    f"Expected exactly two deliberate 409 conflicts, got {conflict_errors!r}")
            require(any(item["url"].endswith("/api/v1/measure") for item in conflict_errors),
                    "The stale measurement did not receive HTTP 409.")
            require(any(item["url"].endswith("/api/v1/actions") for item in conflict_errors),
                    "The stale note update did not receive HTTP 409.")
            require(not unexpected_http, f"Unexpected HTTP errors: {unexpected_http!r}")
            expected_conflict_console = [
                item for item in events["console_errors"]
                if "status of 409 (Conflict)" in item["text"]
            ]
            unexpected_console = [
                item for item in events["console_errors"]
                if item not in expected_conflict_console
            ]
            require(len(expected_conflict_console) == 2,
                    f"Expected two deliberate 409 console diagnostics: {events['console_errors']!r}")
            require(not unexpected_console,
                    f"Browser console errors: {unexpected_console!r}")
            require(not events["page_errors"], f"Page errors: {events['page_errors']!r}")
            require(not events["failed_requests"],
                    f"Failed requests: {events['failed_requests']!r}")
            require(not events["external_requests"],
                    f"Unexpected external requests: {events['external_requests']!r}")
            results.append({"name": "browser event health", "status": "passed", "detail": {
                "expected_409": conflict_errors, "expected_409_console": expected_conflict_console,
                "unexpected_http": [], "unexpected_console": [],
            }})
            report["status"] = "passed"
            return report
        except Exception as error:
            report["error"] = str(error)
            report["traceback"] = traceback.format_exc()
            try:
                page.screenshot(path=str(output / "failure.png"), full_page=True)
            except Exception:
                pass
            raise
        finally:
            context.tracing.stop(path=str(output / "workspace-regressions-trace.zip"))
            context.close()
            browser.close()
            (output / "report.json").write_text(
                json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8"
            )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--url", help="Existing isolated workspace server")
    args = parser.parse_args()

    if args.url:
        report = run_regressions(args.url, args.output.resolve())
        print(json.dumps(report, ensure_ascii=False, indent=2))
        return 0

    from slab_preflight.web_api import create_server

    server = create_server(ROOT, 0, "en")
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    base_url = f"http://{server.expected_host}/"
    try:
        report = run_regressions(base_url, args.output.resolve())
        print(json.dumps(report, ensure_ascii=False, indent=2))
        return 0
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=10)


if __name__ == "__main__":
    raise SystemExit(main())
