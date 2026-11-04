"""Exercise a copied frozen CalcLens executable through real Chromium controls.

CI installs Playwright and Chromium for this harness; neither is required by the
application. The executable receives no Python installation paths and starts in
an unrelated empty working directory. Public example CIFs are browser uploads.
"""

from __future__ import annotations

import argparse
import base64
from contextlib import contextmanager
import csv
import hashlib
import io
import json
import os
from pathlib import Path
import shutil
import signal
import socket
import subprocess
import sys
import tempfile
import time
import traceback
import urllib.error
import urllib.request


ROOT = Path(__file__).resolve().parents[1]
VERSION = "0.3.0"
NOTE = "Windows executable smoke: checked the a-normal layer.\n원본 CIF와 주기 이미지를 확인함."
LABELS = {
    "ko": {"language": "한국어", "title": "구조 개요", "batch": "여러 CIF 비교",
           "project": "저장한 작업 열기", "needs_review": "검토 필요", "unsupported": "입력 오류",
           "all": "전체", "minimum": "가장 가까운 원자쌍"},
    "en": {"language": "English", "title": "Structure overview", "batch": "Compare CIF files",
           "project": "Open saved work", "needs_review": "Needs review", "unsupported": "Input errors",
           "all": "All", "minimum": "Nearest atom pair"},
}
SELF_TEST_CHECKS = {
    "graphene_geometry", "mos2_axes", "invalid_cell_isolation", "project_roundtrip",
    "plotly_charts", "streamlit_static", "plotly_validators", "metadata",
}


def require(condition, message):
    if not condition:
        raise AssertionError(message)


def child_environment():
    environment = {key: value for key, value in os.environ.items()
                   if not key.upper().startswith("PYTHON")
                   and key.upper() not in {"PATH", "VIRTUAL_ENV", "CONDA_PREFIX", "CALCLENS_LANGUAGE"}}
    if os.name == "nt":
        windows = Path(os.environ.get("SystemRoot", r"C:\Windows"))
        environment["PATH"] = os.pathsep.join((str(windows / "System32"), str(windows)))
    else:
        environment["PATH"] = "/usr/bin:/bin"
    return environment


def executable_json(executable, flag, cwd, environment, output):
    options = ({"creationflags": subprocess.CREATE_NEW_PROCESS_GROUP} if os.name == "nt"
               else {"start_new_session": True})
    process = subprocess.Popen([str(executable), flag], cwd=cwd, env=environment,
                               stdout=subprocess.PIPE, stderr=subprocess.PIPE, **options)
    try:
        stdout, stderr = process.communicate(timeout=180)
    except subprocess.TimeoutExpired:
        stop_process_tree(process, output)
        stdout, stderr = process.communicate(timeout=10)
        (output / f"{flag.removeprefix('--')}.timeout.log").write_bytes(stdout + stderr)
        raise
    name = flag.removeprefix("--")
    (output / f"{name}.stdout.log").write_bytes(stdout)
    (output / f"{name}.stderr.log").write_bytes(stderr)
    require(process.returncode == 0, f"{flag} exited {process.returncode}; inspect its logs.")
    document = json.loads(stdout.decode("utf-8-sig"))
    require(isinstance(document, dict), f"{flag} must return a JSON object.")
    return document


def free_port():
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        return probe.getsockname()[1]


def wait_health(process, base_url):
    deadline = time.monotonic() + 180
    last_error = "server has not answered"
    local = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    while time.monotonic() < deadline:
        require(process.poll() is None, "The executable exited before the server became healthy.")
        try:
            with local.open(base_url + "/_stcore/health", timeout=2) as response:
                if response.status == 200 and response.read().strip() == b"ok":
                    return
        except (OSError, urllib.error.URLError) as error:
            last_error = str(error)
        time.sleep(0.25)
    raise TimeoutError(f"Frozen server did not become healthy: {last_error}")


def stop_process_tree(process, output):
    if process is None:
        return
    if os.name == "nt":
        taskkill = Path(os.environ.get("SystemRoot", r"C:\Windows")) / "System32/taskkill.exe"
        stopped = subprocess.run([str(taskkill), "/PID", str(process.pid), "/T", "/F"],
                                 stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                                 timeout=30, check=False)
        (output / "process-cleanup.log").write_bytes(stopped.stdout)
    elif process.poll() is None:
        os.killpg(process.pid, signal.SIGTERM)
    try:
        process.wait(timeout=20)
    except subprocess.TimeoutExpired:
        if os.name != "nt":
            os.killpg(process.pid, signal.SIGKILL)
        else:
            process.kill()
        process.wait(timeout=10)


def remove_isolated_directory(directory, *, timeout=30.0):
    """Wait briefly for terminated Windows images/AV handles to be released."""
    deadline = time.monotonic() + timeout
    while True:
        try:
            shutil.rmtree(directory)
            return
        except PermissionError:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise
            time.sleep(min(0.25, remaining))


@contextmanager
def isolated_work_directory():
    directory = Path(tempfile.mkdtemp(prefix="calclens-frozen-smoke-"))
    try:
        yield directory
    finally:
        remove_isolated_directory(directory)


def browser_flow(base_url, language, output, originals, browser_events):
    # Import only in the CI harness, never in the frozen application.
    from playwright.sync_api import expect, sync_playwright

    expect.set_options(timeout=30_000)
    contexts = []
    current_page = None

    def idle(page):
        expect(page.locator('[data-testid="stApp"]')).to_have_attribute(
            "data-test-script-state", "notRunning", timeout=60_000,
        )
        expect(page.locator('[data-testid="stException"]')).to_have_count(0)

    def metrics(page, expected):
        values = page.locator('[data-testid="stMetricValue"]')
        expect(values).to_have_count(len(expected))
        for index, value in enumerate(expected):
            expect(values.nth(index)).to_have_text(value)
        idle(page)

    def selectbox(page, container, option):
        page.locator(container).get_by_role("combobox").click()
        page.get_by_role("option", name=option, exact=True).click()
        idle(page)

    def radio(page, logical_key, choice):
        widget = page.locator(f".st-key-{logical_key}_{language}")
        control = widget.get_by_role("radio", name=LABELS[language][choice], exact=True)
        control.focus()
        control.press("Space")
        expect(control).to_be_checked()
        idle(page)

    def download(page, key, filename):
        idle(page)
        with page.expect_download(timeout=30_000) as pending:
            page.locator(f".st-key-{key}").get_by_role("button").click()
        received = pending.value
        require(received.failure() is None, f"Download failed: {key}")
        destination = output / filename
        received.save_as(destination)
        return destination

    def new_page(browser, label):
        nonlocal current_page
        context = browser.new_context(accept_downloads=True, viewport={"width": 1500, "height": 1050})
        context.set_default_timeout(30_000)
        context.tracing.start(screenshots=True, snapshots=True, sources=False)
        contexts.append((context, label))
        page = context.new_page()
        current_page = page
        page.on("console", lambda message: browser_events["console"].append(
            {"context": label, "type": message.type, "text": message.text,
             "location": message.location}))
        page.on("pageerror", lambda error: browser_events["page_errors"].append(
            {"context": label, "message": str(error)}))
        page.on("requestfailed", lambda request: browser_events["failed_requests"].append(
            {"context": label, "url": request.url, "failure": request.failure}))
        page.on("response", lambda response: browser_events["http_errors"].append(
            {"context": label, "url": response.url, "status": response.status})
            if response.status >= 400 and response.url.startswith(base_url) else None)
        page.goto(base_url, wait_until="domcontentloaded", timeout=60_000)
        expect(page.get_by_role("heading", name=LABELS[language]["title"], exact=True)).to_be_visible()
        idle(page)
        return page

    def read_project(path):
        document = json.loads(path.read_text("utf-8"))
        require(document.get("format") == "calclens.project" and document.get("schema_version") == 1,
                "Downloaded project format/schema is wrong.")
        entries = document["entries"]
        require(len(entries) == 3 and len({entry["id"] for entry in entries}) == 3,
                "Project lost or merged uploaded files.")
        require([entry["filename"] for entry in entries] == list(originals), "Project upload order changed.")
        for entry in entries:
            original = originals[entry["filename"]]
            require(base64.b64decode(entry["cif_base64"], validate=True) == original,
                    f"Project changed original bytes: {entry['filename']}")
            require(entry["sha256"] == hashlib.sha256(original).hexdigest(), "Project SHA-256 mismatch.")
        selected = next(entry for entry in entries if entry["id"] == document["state"]["selected_id"])
        require(selected["filename"] == "mos2_a_normal.cif", "Project selected the wrong file.")
        require(selected["normal_axis"] == "a" and selected["short_distance"] == 2.5,
                "Project lost the selected file's measurement settings.")
        require(selected["note"] == NOTE and selected["reviewed"] is True,
                "Project lost notes or review completion.")
        require(document["state"]["filter_mode"] == "needs_review"
                and document["state"]["review_focus"] == "minimum", "Project lost view state.")
        return document

    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        try:
            current_page = page = new_page(browser, "initial")
            metrics(page, ["1.420 Å", "0.000 Å", "20.000 Å"])
            expect(page.locator('[data-testid="stPlotlyChart"]')).to_have_count(2)
            expect(page.locator('[data-testid="stPlotlyChart"] .js-plotly-plot')).to_have_count(2)
            page.screenshot(path=str(output / "sample-default.png"), full_page=True)
            other = "en" if language == "ko" else "ko"
            for chosen in (other, language):
                selectbox(page, ".st-key-language", LABELS[chosen]["language"])
                expect(page.get_by_role("heading", name=LABELS[chosen]["title"], exact=True)).to_be_visible()
                metrics(page, ["1.420 Å", "0.000 Å", "20.000 Å"])

            radio(page, "source", "batch")
            page.locator(".st-key-batch_upload_holder input[type=file]").set_input_files([
                {"name": name, "mimeType": "chemical/x-cif", "buffer": data}
                for name, data in originals.items()
            ])
            axes = page.locator('[class*="st-key-batch_axis_batch_"]')
            expect(axes).to_have_count(3)
            # MoS2 goes first, avoiding platform-dependent canvas row coordinates.
            axes.first.get_by_role("combobox").click()
            page.get_by_role("option", name="a", exact=True).click()
            metrics(page, ["2.409 Å", "3.120 Å", "16.880 Å"])
            cutoff = page.locator('[class*="st-key-batch_cutoff_batch_"] input').first
            cutoff.fill("2.5")
            cutoff.press("Enter")
            idle(page)
            require(float(cutoff.input_value()) == 2.5, "The edited cutoff was not retained.")
            metrics(page, ["2.409 Å", "3.120 Å", "16.880 Å"])
            note = page.locator('[class*="st-key-review_note_batch_"] textarea')
            note.fill(NOTE)
            note.press("Tab")
            idle(page)
            done = page.locator('[class*="st-key-review_done_batch_"]')
            done.locator("label").click()
            expect(done.get_by_role("checkbox")).to_be_checked()
            idle(page)
            page.locator(".st-key-show_minimum_pair").get_by_role("button").click()
            expect(page.locator('[class*="st-key-review_focus_"]').get_by_role(
                "radio", name=LABELS[language]["minimum"], exact=True)).to_be_checked()
            idle(page)
            radio(page, "batch_filter", "needs_review")
            saved_path = download(page, "download_project", "review.calclens.json")
            saved = read_project(saved_path)
            report_path = download(page, "download_report", "selected-report.json")
            report = json.loads(report_path.read_text("utf-8"))
            selected_hash = hashlib.sha256(originals["mos2_a_normal.cif"]).hexdigest()
            require(report["normal_axis"] == "a" and report["short_distance_threshold_angstrom"] == 2.5,
                    "Downloaded JSON does not match edited measurement settings.")
            require(report["provenance"]["original_filename"] == "mos2_a_normal.cif"
                    and report["provenance"]["sha256"] == selected_hash,
                    "Downloaded JSON has the wrong source identity.")
            require(report["provenance"]["calclens_version"] == VERSION, "Wrong exported engine version.")
            page.screenshot(path=str(output / "batch-reviewed.png"), full_page=True)

            radio(page, "batch_filter", "unsupported")
            expect(page.locator('[data-testid="stMetricValue"]')).to_have_count(0)
            expect(page.locator('[data-testid="stPlotlyChart"]')).to_have_count(0)
            expect(page.locator('[data-testid="stAlert"]').filter(
                has_text="partial_occupancy.cif").first).to_be_visible()
            summary_path = download(page, "download_batch", "all-files.csv")
            rows = list(csv.DictReader(io.StringIO(summary_path.read_text("utf-8-sig"))))
            field = ({"filename": "파일명", "status": "상태", "sha256": "SHA-256",
                      "minimum": "최소 거리 / Å", "calclens_version": "CalcLens 버전", "ase_version": "ASE 버전"}
                     if language == "ko" else
                     {"filename": "filename", "status": "status", "sha256": "sha256",
                      "minimum": "minimum_distance_angstrom", "calclens_version": "calclens_version", "ase_version": "ase_version"})
            require(len(rows) == 3, "Filtered CSV must still export all three files.")
            by_name = {row[field["filename"]]: row for row in rows}
            require(set(by_name) == set(originals), "CSV lost original filenames.")
            for name, data in originals.items():
                row = by_name[name]
                require(row[field["sha256"]] == hashlib.sha256(data).hexdigest(), "CSV source hash mismatch.")
                require(row[field["calclens_version"]] == VERSION and row[field["ase_version"]],
                        "CSV lacks engine versions, including for failed input.")
            failed = by_name["partial_occupancy.cif"]
            require(failed[field["status"]] == "unsupported" and failed[field["minimum"]] == "",
                    "Failed input must have an unsupported status and blank measurements.")
            page.screenshot(path=str(output / "unsupported-no-metrics.png"), full_page=True)
            contexts[0][0].tracing.stop(path=str(output / "initial-trace.zip"))
            contexts[0][0].close()
            contexts.pop(0)

            current_page = fresh = new_page(browser, "reopened")
            radio(fresh, "source", "project")
            expect(fresh.locator('[data-testid="stMetricValue"]')).to_have_count(0)
            fresh.locator(".st-key-project_upload input[type=file]").set_input_files(str(saved_path))
            opener = fresh.locator(".st-key-load_project").get_by_role("button")
            expect(opener).to_be_enabled()
            idle(fresh)
            expect(fresh.locator('[data-testid="stMetricValue"]')).to_have_count(0)
            opener.click()
            metrics(fresh, ["2.409 Å", "3.120 Å", "16.880 Å"])
            expect(fresh.locator('[class*="st-key-review_note_project_"] textarea')).to_have_value(NOTE)
            expect(fresh.locator('[class*="st-key-review_done_project_"]').get_by_role("checkbox")).to_be_checked()
            expect(fresh.locator(f".st-key-batch_filter_{language}").get_by_role(
                "radio", name=LABELS[language]["needs_review"], exact=True)).to_be_checked()
            expect(fresh.locator('[class*="st-key-review_focus_"]').get_by_role(
                "radio", name=LABELS[language]["minimum"], exact=True)).to_be_checked()
            restored = read_project(download(fresh, "download_project", "reopened.calclens.json"))
            require(restored == saved, "A fresh browser session did not restore the exact saved project.")
            restored_report = json.loads(download(fresh, "download_report", "reopened-report.json").read_text("utf-8"))
            require(restored_report == report, "Reopened project produced a different selected report.")
            fresh.screenshot(path=str(output / "reopened-success.png"), full_page=True)
            require(not browser_events["page_errors"], "Browser JavaScript exceptions were recorded.")
            require(not browser_events["http_errors"], "Frozen app assets/endpoints returned HTTP errors.")
            return {"default_language": language, "language_round_trip": True,
                    "sample_charts": 2, "uploaded_files": len(originals),
                    "selection_strategy": "MoS2 first entry, then needs_review filter",
                    "selected_id": saved["state"]["selected_id"],
                    "project_roundtrip": True, "unsupported_has_no_metrics": True,
                    "all_file_csv": True}
        except Exception:
            if current_page is not None and not current_page.is_closed():
                try:
                    current_page.screenshot(path=str(output / "failure.png"), full_page=True)
                    (output / "failure.html").write_text(current_page.content(), encoding="utf-8")
                except Exception as error:
                    browser_events["capture_error"] = str(error)
            raise
        finally:
            for context, label in contexts:
                try:
                    context.tracing.stop(path=str(output / f"{label}-trace.zip"))
                except Exception as error:
                    browser_events.setdefault("cleanup_errors", []).append(str(error))
                finally:
                    try:
                        context.close()
                    except Exception as error:
                        browser_events.setdefault("cleanup_errors", []).append(str(error))
            try:
                browser.close()
            except Exception as error:
                browser_events.setdefault("cleanup_errors", []).append(str(error))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--exe", required=True, type=Path)
    parser.add_argument("--language", required=True, choices=("ko", "en"))
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    output = args.output.resolve()
    output.mkdir(parents=True, exist_ok=True)
    events = {"console": [], "page_errors": [], "failed_requests": [], "http_errors": []}
    result = {"status": "failed", "language": args.language, "exe": str(args.exe.resolve())}
    process = None
    try:
        source = args.exe.resolve(strict=True)
        require(source.is_file(), "--exe must identify a frozen executable file.")
        originals = {name: (ROOT / "examples" / name).read_bytes() for name in (
            "mos2_a_normal.cif", "graphene.cif", "partial_occupancy.cif",
        )}
        result["source_files"] = {name: {"sha256": hashlib.sha256(data).hexdigest(), "bytes": len(data)}
                                  for name, data in originals.items()}
        environment = child_environment()
        result["child_path"] = environment["PATH"]
        with isolated_work_directory() as isolated:
            app = isolated / "copied-application"
            if (source.parent / "_internal").is_dir():
                shutil.copytree(source.parent, app)
                result["layout"] = "onedir"
            else:
                app.mkdir()
                shutil.copy2(source, app / source.name)
                result["layout"] = "onefile"
            executable = app / source.name
            cwd = isolated / "unrelated-empty-working-directory"
            cwd.mkdir()
            diagnostic = executable_json(executable, "--self-test", cwd, environment, output)
            result["self_test"] = diagnostic
            require(diagnostic.get("status") == "ok" and diagnostic.get("frozen") is True,
                    "Self-test did not prove a successful frozen execution.")
            require(diagnostic.get("language") == args.language and diagnostic.get("version") == VERSION,
                    "Executable has the wrong embedded locale or version.")
            require(os.path.normcase(os.path.realpath(diagnostic["executable"]))
                    == os.path.normcase(os.path.realpath(executable)), "Self-test ran a different executable.")
            require(diagnostic.get("meipass"), "Frozen resource extraction path is missing.")
            checks = diagnostic.get("checks", {})
            require(isinstance(checks, dict) and SELF_TEST_CHECKS <= checks.keys(),
                    "Self-test omitted required frozen resource/geometry checks.")
            require(all(checks[key] is True or checks[key] in ("ok", "passed")
                        for key in SELF_TEST_CHECKS), "A frozen self-test check did not pass.")
            info = executable_json(executable, "--build-info", cwd, environment, output)
            require(info == diagnostic.get("build_info"), "Build-info CLI differs from frozen self-test metadata.")
            result["build_info"] = info
            port = free_port()
            base_url = f"http://127.0.0.1:{port}"
            with (output / "server.log").open("wb") as server_log:
                options = ({"creationflags": subprocess.CREATE_NEW_PROCESS_GROUP} if os.name == "nt"
                           else {"start_new_session": True})
                process = subprocess.Popen([str(executable), "--port", str(port), "--no-browser"],
                                           cwd=cwd, env=environment, stdout=server_log,
                                           stderr=subprocess.STDOUT, **options)
                try:
                    wait_health(process, base_url)
                    result["browser"] = browser_flow(base_url, args.language, output, originals, events)
                    require(process.poll() is None, "Frozen server exited during the browser smoke.")
                finally:
                    stop_process_tree(process, output)
                    process = None
        result["status"] = "passed"
    except Exception as error:
        result["error"] = str(error)
        result["traceback"] = traceback.format_exc()
        print(result["traceback"], file=sys.stderr)
    finally:
        if process is not None:
            try:
                stop_process_tree(process, output)
            except Exception as error:
                result["status"] = "failed"
                result["cleanup_error"] = str(error)
        (output / "browser-events.json").write_text(json.dumps(events, ensure_ascii=False, indent=2), encoding="utf-8")
        (output / "smoke-report.json").write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(result, ensure_ascii=True))
    return 0 if result["status"] == "passed" else 1


if __name__ == "__main__":
    raise SystemExit(main())
