"""Exercise the local React workspace through a real Chromium WebGL context."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import traceback
import urllib.parse
import zipfile


ROOT = Path(__file__).resolve().parents[1]
NOTE = "React workspace smoke: reviewed a-normal MoS2.\n원본과 거리 선택을 확인함."
TEXT = {
    "ko": {
        "title": "계산 전 구조 점검", "overview": "구조 개요", "compare": "구조 비교",
        "sample": "예제 불러오기", "settings": "선택 구조 편집", "apply": "변경 적용",
        "measurement": "원자 거리 측정", "measure": "거리 계산", "save_pair": "선택 저장",
        "save_project": "작업 저장", "mark_reviewed": "검토 완료로 표시",
        "reviewed": "검토 완료", "geometry_filter": "구조 상태",
    },
    "en": {
        "title": "Structure preflight", "overview": "Overview", "compare": "Compare structures",
        "sample": "Try sample", "settings": "Edit selected structure", "apply": "Apply changes",
        "measurement": "Measure atom pair", "measure": "Measure distance",
        "save_pair": "Save selection", "save_project": "Save project",
        "mark_reviewed": "Mark review complete", "reviewed": "Reviewed",
        "geometry_filter": "Geometry status",
    },
}


def require(condition, message):
    if not condition:
        raise AssertionError(message)


def accept_workspace_dialog(dialog):
    """Explicitly accept replacement and navigation dialogs exercised by smokes."""
    allowed = dialog.type == "beforeunload" or (
        dialog.type == "confirm" and any(text in dialog.message for text in (
            "Replace the unsaved workspace?", "저장하지 않은 작업을 바꾸시겠습니까?",
        ))
    )
    if allowed:
        dialog.accept()
        return
    dialog.dismiss()
    raise AssertionError(f"Unexpected browser dialog: {dialog.type}: {dialog.message}")


def read_project_document(path):
    """Read the user download, including the schema-3 single-member ZIP format."""
    path = Path(path)
    if zipfile.is_zipfile(path):
        with zipfile.ZipFile(path) as archive:
            require(archive.namelist() == ["project.json"], "Project ZIP has unexpected members.")
            return json.loads(archive.read("project.json"))
    return json.loads(path.read_text(encoding="utf-8-sig"))


def default_originals():
    return {
        name: (ROOT / "examples" / name).read_bytes()
        for name in ("mos2_a_normal.cif", "graphene.cif", "partial_occupancy.cif")
    }


def _origin(url):
    parsed = urllib.parse.urlsplit(url)
    port = parsed.port or (443 if parsed.scheme == "https" else 80)
    return parsed.scheme, parsed.hostname, port


def _idle(page, expect):
    expect(page.get_by_test_id("app-ready")).to_be_visible(timeout=60_000)
    expect(page.locator('[aria-label="Working"]')).to_have_count(0, timeout=60_000)
    page.wait_for_timeout(100)


def _details(page, label):
    return page.locator("details.tool-card").filter(has=page.get_by_text(label, exact=True))


def _open_details(details):
    if not details.evaluate("element => element.open"):
        details.locator("summary").click()


def _download(page, locator, destination):
    with page.expect_download(timeout=30_000) as pending:
        locator.click()
    download = pending.value
    require(download.failure() is None, f"Download failed: {destination.name}")
    download.save_as(destination)
    return destination


def _project_entry(document, filename):
    return next(entry for entry in document["entries"] if entry["filename"] == filename)


def _assert_project(document, expected_version=None):
    require(document.get("format") == "calclens.project", "Project format is wrong.")
    require(document.get("schema_version") == 3, "Project schema must be version 3.")
    require(len(document.get("entries", [])) == 3, "Project did not preserve all uploaded CIFs.")
    selected = _project_entry(document, "mos2_a_normal.cif")
    require(selected["normal_axis"] == "a", "Project lost the selected normal axis.")
    require(selected["short_distance"] == 2.5, "Project lost the edited cutoff.")
    require(selected["note"] == NOTE, "Project lost the review note.")
    require(selected["reviewed"] is True and selected["review_stamp"],
            "Project lost current review completion evidence.")
    require(len(selected["measurements"]) == 1, "Project lost the saved atom-pair selection.")
    pair = selected["measurements"][0]
    require(pair["i"] == 0 and pair["j"] == 1 and pair["mode"] == "minimum_image",
            "Project saved the wrong atom-pair selection.")
    if expected_version is not None:
        require(document["tools"]["calclens_version"] == expected_version,
                "Project was exported by an unexpected CalcLens version.")


def run_workspace_browser_smoke(
    base_url, language, output, originals=None, events=None, expected_version=None,
):
    """Run the reusable SPA workflow against a source or frozen local server."""
    from playwright.sync_api import expect, sync_playwright

    require(language in TEXT, "Unsupported expected workspace language.")
    output = Path(output).resolve()
    output.mkdir(parents=True, exist_ok=True)
    originals = dict(originals or default_originals())
    require(set(originals) == {
        "mos2_a_normal.cif", "graphene.cif", "partial_occupancy.cif",
    }, "Workspace smoke needs the three canonical CIF inputs.")
    events = events if events is not None else {}
    for key in (
        "console_errors", "page_errors", "failed_requests", "http_errors",
        "external_requests",
    ):
        events.setdefault(key, [])
    labels = TEXT[language]
    other_language = "en" if language == "ko" else "ko"
    other_labels = TEXT[other_language]
    expected_origin = _origin(base_url)
    trace_path = output / "workspace-trace.zip"
    saved_path = output / "workspace.calclens.zip"
    restored_path = output / "workspace-restored.calclens.zip"

    expect.set_options(timeout=30_000)
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(
            headless=True,
            args=["--enable-webgl", "--ignore-gpu-blocklist", "--enable-unsafe-swiftshader"],
        )
        context = browser.new_context(accept_downloads=True, viewport={"width": 1550, "height": 1050})
        context.set_default_timeout(30_000)
        context.tracing.start(screenshots=True, snapshots=True, sources=False)
        page = context.new_page()
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
        try:
            page.goto(base_url, wait_until="domcontentloaded", timeout=60_000)
            expect(page.get_by_role("heading", name=labels["title"], exact=True)).to_be_visible()
            _idle(page, expect)
            if expected_version is not None:
                expect(page.locator(".version")).to_contain_text(f"v{expected_version}")

            viewer = page.get_by_test_id("molecule-canvas").first
            expect(viewer).to_be_visible()
            expect(page.locator(".molecule-fallback")).to_have_count(0)
            canvas = viewer.locator("canvas").first
            expect(canvas).to_be_visible()
            webgl = canvas.evaluate("""element => {
                const renderer = element._3dmol_viewer?.renderer;
                const gl = renderer?.context;
                if (!gl) return null;
                const isWebGL = gl instanceof WebGLRenderingContext ||
                    (typeof WebGL2RenderingContext !== 'undefined' &&
                     gl instanceof WebGL2RenderingContext);
                return {isWebGL, width: element.width, height: element.height,
                        offscreenWidth: renderer._offscreen?.width ?? null,
                        offscreenHeight: renderer._offscreen?.height ?? null,
                        version: gl.getParameter(gl.VERSION), renderer: gl.getParameter(gl.RENDERER),
                        webglVersion: renderer._webglversion};
            }""")
            require(webgl and webgl["isWebGL"] and webgl["width"] > 0 and webgl["height"] > 0
                    and webgl["offscreenWidth"] > 0 and webgl["offscreenHeight"] > 0,
                    "The molecular viewer did not create a real WebGL drawing buffer.")
            require(webgl["version"] and webgl["renderer"], "WebGL runtime details are missing.")
            page.screenshot(path=str(output / "workspace-default.png"), full_page=True)
            viewer.screenshot(path=str(output / "workspace-3d-frame.png"))

            language_button = page.get_by_test_id("language-toggle")
            language_button.click()
            expect(page.get_by_role("heading", name=other_labels["title"], exact=True)).to_be_visible()
            _idle(page, expect)
            language_button.click()
            expect(page.get_by_role("heading", name=labels["title"], exact=True)).to_be_visible()
            _idle(page, expect)

            replace_input = page.get_by_test_id("cif-replace-upload")
            replace_input.set_input_files([
                {"name": name, "mimeType": "chemical/x-cif", "buffer": data}
                for name, data in originals.items()
            ])
            for filename in originals:
                expect(page.get_by_role("button", name=filename, exact=True)).to_be_visible()
            _idle(page, expect)

            settings = _details(page, labels["settings"])
            _open_details(settings)
            page.get_by_test_id("selected-axis").select_option("a")
            page.get_by_test_id("selected-cutoff").fill("2.5")
            settings.get_by_test_id("review-note").fill(NOTE)
            settings.get_by_role("button", name=labels["apply"], exact=True).click()
            _idle(page, expect)
            expect(settings.locator("summary")).to_contain_text("a · 2.5 Å")

            review_button = page.get_by_test_id("reviewed-toggle")
            review_button.click()
            _idle(page, expect)
            expect(review_button).to_contain_text(labels["reviewed"])

            measurement = _details(page, labels["measurement"])
            _open_details(measurement)
            page.get_by_test_id("measure-first-index").fill("0")
            page.get_by_test_id("measure-second-index").fill("1")
            page.get_by_test_id("measure-pair").click()
            expect(measurement.locator(".measurement-result")).to_be_visible()
            page.get_by_test_id("save-pair").click()
            expect(measurement.locator(".saved-pairs")).to_be_visible()
            _idle(page, expect)

            _download(
                page, page.get_by_test_id("project-export"),
                saved_path,
            )
            require(zipfile.is_zipfile(saved_path), "Project export was not a ZIP archive.")
            saved = read_project_document(saved_path)
            _assert_project(saved, expected_version)

            page.get_by_role("button", name=labels["sample"], exact=True).click()
            _idle(page, expect)
            page.get_by_test_id("project-import").set_input_files(str(saved_path))
            for filename in originals:
                expect(page.get_by_role("button", name=filename, exact=True)).to_be_visible()
            _idle(page, expect)
            settings = _details(page, labels["settings"])
            _open_details(settings)
            expect(page.get_by_test_id("selected-axis")).to_have_value("a")
            expect(page.get_by_test_id("selected-cutoff")).to_have_value("2.5")
            expect(settings.get_by_test_id("review-note")).to_have_value(NOTE)
            measurement = _details(page, labels["measurement"])
            _open_details(measurement)
            expect(measurement.locator(".saved-pairs")).to_be_visible()
            _download(
                page, page.get_by_test_id("project-export"),
                restored_path,
            )
            restored = read_project_document(restored_path)
            require(restored == saved, "Project export changed after reopening in the workspace.")

            page.get_by_test_id("nav-compare").click()
            expect(page.locator(".comparison-grid")).to_be_visible()
            expect(page.get_by_test_id("compare-card-0")).to_be_visible()
            expect(page.get_by_test_id("compare-card-1")).to_be_visible()
            expect(page.locator(".comparison-grid [data-testid='molecule-canvas']")).to_have_count(2)
            page.screenshot(path=str(output / "workspace-compare.png"), full_page=True)

            page.get_by_role("button", name=labels["overview"], exact=True).click()
            _idle(page, expect)
            page.get_by_test_id("geometry-filter").select_option("unsupported")
            expect(page.locator(".records-card tbody tr")).to_have_count(1)
            page.get_by_role("button", name="partial_occupancy.cif", exact=True).click()
            _idle(page, expect)
            expect(page.locator(".metric-value")).to_have_count(3)
            for index in range(3):
                expect(page.locator(".metric-value").nth(index)).to_have_text("—")
            expect(page.locator(".viewer-card [data-testid='molecule-canvas']")).to_have_count(0)
            expect(page.get_by_test_id("unsupported-empty")).to_be_visible()
            page.screenshot(path=str(output / "workspace-unsupported.png"), full_page=True)

            require(not events["console_errors"], "Browser console errors were recorded.")
            require(not events["page_errors"], "Browser JavaScript exceptions were recorded.")
            require(not events["failed_requests"], "Workspace requests failed.")
            require(not events["http_errors"], "Workspace assets or API endpoints returned errors.")
            require(not events["external_requests"], "Workspace made external network requests.")
            return {
                "language_round_trip": True,
                "uploaded_files": len(originals),
                "project_schema": saved["schema_version"],
                "project_roundtrip": True,
                "saved_pair": True,
                "comparison": True,
                "unsupported_has_no_metrics": True,
                "webgl": webgl,
                "browser_request_scope": "same-origin only",
            }
        finally:
            try:
                context.tracing.stop(path=str(trace_path))
            finally:
                context.close()
                browser.close()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--url", required=True)
    parser.add_argument("--language", required=True, choices=("ko", "en"))
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--version")
    args = parser.parse_args()
    output = args.output.resolve()
    output.mkdir(parents=True, exist_ok=True)
    events = {}
    result = {"status": "failed", "url": args.url, "language": args.language}
    try:
        result["workspace"] = run_workspace_browser_smoke(
            args.url, args.language, output, events=events, expected_version=args.version,
        )
        result["source_files"] = {
            name: {"sha256": hashlib.sha256(data).hexdigest(), "bytes": len(data)}
            for name, data in default_originals().items()
        }
        result["status"] = "passed"
    except Exception as error:
        result["error"] = str(error)
        result["traceback"] = traceback.format_exc()
        print(result["traceback"])
    (output / "workspace-browser-events.json").write_text(
        json.dumps(events, ensure_ascii=False, indent=2), encoding="utf-8",
    )
    (output / "workspace-smoke-report.json").write_text(
        json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8",
    )
    print(json.dumps(result, ensure_ascii=True))
    return 0 if result["status"] == "passed" else 1


if __name__ == "__main__":
    raise SystemExit(main())
