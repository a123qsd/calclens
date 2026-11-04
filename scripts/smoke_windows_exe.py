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
import urllib.parse
import urllib.request


ROOT = Path(__file__).resolve().parents[1]
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
    # Prove the launcher pins the app to the root URL instead of inheriting a
    # machine-wide Streamlit prefix from the user's environment.
    environment["STREAMLIT_SERVER_BASE_URL_PATH"] = "inherited-prefix-must-not-apply"
    return environment


def executable_json(executable, flag, cwd, environment, output):
    options = ({"creationflags": subprocess.CREATE_NEW_PROCESS_GROUP} if os.name == "nt"
               else {"start_new_session": True})
    process = subprocess.Popen([str(executable), flag], cwd=cwd, env=environment,
                               stdout=subprocess.PIPE, stderr=subprocess.PIPE, **options)
    try:
        stdout, stderr = process.communicate(timeout=180)
    except subprocess.TimeoutExpired:
        stop_process_tree(process, output, label=flag.removeprefix("--") + "-timeout")
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


def stop_process_tree(process, output, *, label, require_graceful=False):
    if process is None:
        return "not-started"
    shutdown_log = output / f"{label}-shutdown.log"
    forced = False
    if process.poll() is None:
        try:
            process.send_signal(signal.CTRL_BREAK_EVENT if os.name == "nt" else signal.SIGINT)
            process.wait(timeout=20)
            shutdown_log.write_text(
                f"outcome=graceful\nexit_code={process.returncode}\n", encoding="utf-8"
            )
            return "graceful"
        except (OSError, subprocess.TimeoutExpired) as error:
            forced = True
            shutdown_log.write_text(
                f"outcome=force-fallback\nreason={type(error).__name__}: {error}\n",
                encoding="utf-8",
            )
    else:
        shutdown_log.write_text(
            f"outcome=already-stopped\nexit_code={process.returncode}\n", encoding="utf-8"
        )
        return "already-stopped"
    if os.name == "nt":
        taskkill = Path(os.environ.get("SystemRoot", r"C:\Windows")) / "System32/taskkill.exe"
        stopped = subprocess.run([str(taskkill), "/PID", str(process.pid), "/T", "/F"],
                                 stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                                 timeout=30, check=False)
        (output / f"{label}-force-cleanup.log").write_bytes(stopped.stdout)
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
    if require_graceful and forced:
        raise AssertionError(f"{label} required force termination; inspect {shutdown_log.name}.")
    return "forced"


def wait_port_closed(base_url, *, timeout=30.0):
    parsed = urllib.parse.urlsplit(base_url)
    require(parsed.hostname == "127.0.0.1" and parsed.port, "Invalid local URL for port check.")
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            with socket.create_connection((parsed.hostname, parsed.port), timeout=1):
                pass
        except OSError:
            return
        time.sleep(0.2)
    raise AssertionError(f"Local server port remained open after shutdown: {base_url}")


def descendant_process_ids(root_pid, parent_by_pid):
    """Return one process tree without admitting unrelated or cyclic branches."""
    descendants = {int(root_pid)}
    for _ in range(len(parent_by_pid)):
        added = {
            int(pid) for pid, parent in parent_by_pid.items()
            if int(pid) not in descendants and int(parent) in descendants
        }
        if not added:
            break
        descendants.update(added)
    return descendants


def windows_process_parents():
    """Snapshot the current Windows PID-to-parent-PID relationships."""
    require(os.name == "nt", "Process snapshots are Windows-only.")
    import ctypes
    from ctypes import wintypes

    class ProcessEntry32W(ctypes.Structure):
        _fields_ = [
            ("dwSize", wintypes.DWORD), ("cntUsage", wintypes.DWORD),
            ("th32ProcessID", wintypes.DWORD), ("th32DefaultHeapID", wintypes.WPARAM),
            ("th32ModuleID", wintypes.DWORD), ("cntThreads", wintypes.DWORD),
            ("th32ParentProcessID", wintypes.DWORD), ("pcPriClassBase", wintypes.LONG),
            ("dwFlags", wintypes.DWORD), ("szExeFile", wintypes.WCHAR * 260),
        ]

    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    create_snapshot = kernel32.CreateToolhelp32Snapshot
    create_snapshot.argtypes = (wintypes.DWORD, wintypes.DWORD)
    create_snapshot.restype = wintypes.HANDLE
    process_first = kernel32.Process32FirstW
    process_first.argtypes = (wintypes.HANDLE, ctypes.POINTER(ProcessEntry32W))
    process_first.restype = wintypes.BOOL
    process_next = kernel32.Process32NextW
    process_next.argtypes = (wintypes.HANDLE, ctypes.POINTER(ProcessEntry32W))
    process_next.restype = wintypes.BOOL
    close_handle = kernel32.CloseHandle
    close_handle.argtypes = (wintypes.HANDLE,)
    close_handle.restype = wintypes.BOOL
    snapshot = create_snapshot(0x00000002, 0)  # TH32CS_SNAPPROCESS
    if snapshot == wintypes.HANDLE(-1).value:
        error = ctypes.get_last_error()
        raise OSError(error, "CreateToolhelp32Snapshot failed")
    parents = {}
    try:
        entry = ProcessEntry32W()
        entry.dwSize = ctypes.sizeof(entry)
        if process_first(snapshot, ctypes.byref(entry)):
            while True:
                parents[int(entry.th32ProcessID)] = int(entry.th32ParentProcessID)
                entry.dwSize = ctypes.sizeof(entry)
                if not process_next(snapshot, ctypes.byref(entry)):
                    break
        else:
            error = ctypes.get_last_error()
            if error != 18:  # ERROR_NO_MORE_FILES
                raise OSError(error, "Process32FirstW failed")
    finally:
        close_handle(snapshot)
    return parents


def windows_manager_window(process, language, *, timeout=60.0):
    """Find the actual Tk top-level window owned by the frozen manager process."""
    require(os.name == "nt", "Manager window enumeration is Windows-only.")
    import ctypes
    from ctypes import wintypes

    expected = "CalcLens · 한국어" if language == "ko" else "CalcLens · English"
    user32 = ctypes.windll.user32
    callback_type = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
    user32.EnumWindows.argtypes = (callback_type, wintypes.LPARAM)
    user32.EnumWindows.restype = wintypes.BOOL
    user32.GetWindowThreadProcessId.argtypes = (wintypes.HWND, ctypes.POINTER(wintypes.DWORD))
    user32.GetWindowThreadProcessId.restype = wintypes.DWORD
    user32.IsWindowVisible.argtypes = (wintypes.HWND,)
    user32.IsWindowVisible.restype = wintypes.BOOL
    user32.GetWindowTextLengthW.argtypes = (wintypes.HWND,)
    user32.GetWindowTextLengthW.restype = ctypes.c_int
    user32.GetWindowTextW.argtypes = (wintypes.HWND, wintypes.LPWSTR, ctypes.c_int)
    user32.GetWindowTextW.restype = ctypes.c_int
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        require(process.poll() is None, "Default launch exited before its manager window appeared.")
        allowed_pids = descendant_process_ids(process.pid, windows_process_parents())
        matches = []

        @callback_type
        def inspect_window(handle, _parameter):
            owner = wintypes.DWORD()
            user32.GetWindowThreadProcessId(handle, ctypes.byref(owner))
            if owner.value not in allowed_pids or not user32.IsWindowVisible(handle):
                return True
            length = user32.GetWindowTextLengthW(handle)
            title = ctypes.create_unicode_buffer(length + 1)
            user32.GetWindowTextW(handle, title, len(title))
            if title.value == expected:
                matches.append((int(handle), title.value))
            return True

        user32.EnumWindows(inspect_window, 0)
        if matches:
            require(len(matches) == 1, "Multiple CalcLens manager windows were found.")
            return matches[0]
        time.sleep(0.2)
    raise AssertionError("The default launch did not create the CalcLens manager window.")


def close_windows_manager(process, handle):
    """Exercise the manager's real WM_DELETE close handler and require clean exit."""
    import ctypes
    from ctypes import wintypes

    post_message = ctypes.windll.user32.PostMessageW
    post_message.argtypes = (wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM)
    post_message.restype = wintypes.BOOL
    require(post_message(handle, 0x0010, 0, 0),
            "Could not post WM_CLOSE to the CalcLens manager.")
    try:
        process.wait(timeout=30)
    except subprocess.TimeoutExpired as error:
        raise AssertionError("CalcLens manager did not exit after WM_CLOSE.") from error
    require(process.returncode == 0,
            f"CalcLens manager exited {process.returncode} after WM_CLOSE instead of cleanly.")


def wait_for_no_pyinstaller_extractions(temp_root, *, timeout=30.0):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        leftovers = list(temp_root.glob("_MEI*"))
        if not leftovers:
            return
        time.sleep(0.25)
    raise AssertionError(f"PyInstaller extraction directories remain: {leftovers}")


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


def browser_flow(base_url, language, version, output, originals, browser_events):
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
            require(report["provenance"]["calclens_version"] == version, "Wrong exported engine version.")
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
                require(row[field["calclens_version"]] == version and row[field["ase_version"]],
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
            pyinstaller_temp = isolated / "PyInstaller 임시 추출"
            pyinstaller_temp.mkdir()
            environment["TMP"] = str(pyinstaller_temp)
            environment["TEMP"] = str(pyinstaller_temp)
            app = isolated / "복사한 CalcLens application"
            if (source.parent / "_internal").is_dir():
                shutil.copytree(source.parent, app)
                result["layout"] = "onedir"
            else:
                app.mkdir()
                shutil.copy2(source, app / source.name)
                result["layout"] = "onefile"
            executable = app / source.name
            cwd = isolated / "한글 및 공백 작업 폴더"
            cwd.mkdir()
            diagnostic = executable_json(executable, "--self-test", cwd, environment, output)
            result["self_test"] = diagnostic
            require(diagnostic.get("status") == "ok" and diagnostic.get("frozen") is True,
                    "Self-test did not prove a successful frozen execution.")
            version = diagnostic.get("version")
            require(diagnostic.get("language") == args.language and isinstance(version, str) and version,
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
            capture = isolated / "captured-browser-url.txt"
            manager_environment = dict(environment)
            manager_environment["CALCLENS_BROWSER_CAPTURE_FILE"] = str(capture)
            manager_environment["LOCALAPPDATA"] = str(isolated / "로컬 앱 데이터")
            options = ({"creationflags": subprocess.CREATE_NEW_PROCESS_GROUP} if os.name == "nt"
                       else {"start_new_session": True})
            started_at = time.monotonic()
            with (output / "default-launch.log").open("wb") as default_log:
                default_process = subprocess.Popen(
                    [str(executable)], cwd=cwd, env=manager_environment,
                    stdout=default_log, stderr=subprocess.STDOUT, **options,
                )
                try:
                    manager_handle, manager_title = windows_manager_window(
                        default_process, args.language
                    )
                    deadline = time.monotonic() + 180
                    while not capture.is_file() and time.monotonic() < deadline:
                        require(default_process.poll() is None,
                                "Default launch exited before opening its browser URL.")
                        time.sleep(0.25)
                    require(capture.is_file(), "Default launch did not open a browser URL.")
                    default_url = capture.read_text(encoding="utf-8").strip()
                    require(default_url.startswith("http://127.0.0.1:") and "/inherited-prefix" not in default_url,
                            "Default launch used the wrong local URL.")
                    wait_health(default_process, default_url)
                    result["default_launch"] = {
                        "url": default_url,
                        "startup_seconds": round(time.monotonic() - started_at, 3),
                        "automatic_port": True,
                        "browser_request_captured": True,
                        "manager_window": manager_title,
                    }
                    close_windows_manager(default_process, manager_handle)
                    wait_port_closed(default_url)
                    wait_for_no_pyinstaller_extractions(pyinstaller_temp)
                    logs = list((isolated / "로컬 앱 데이터" / "CalcLens" / "logs").glob("*.log"))
                    ready_files = list(
                        (isolated / "로컬 앱 데이터" / "CalcLens" / "logs").glob("*.ready")
                    )
                    require(len(logs) == 1, "Manager did not create exactly one diagnostic log.")
                    require(not ready_files, "Manager readiness marker was not cleaned up.")
                    manager_log = logs[0].read_text(encoding="utf-8", errors="replace")
                    for marker in (
                        "manager: starting url=", "manager: server process started pid=",
                        "manager: server ready; browser open requested",
                        "manager: close requested", "manager: server stop outcome=graceful",
                        "manager: manager finished",
                    ):
                        require(marker in manager_log,
                                f"Diagnostic log is missing lifecycle marker: {marker}")
                    result["default_launch"]["manager_close"] = "graceful"
                    result["default_launch"]["diagnostic_log"] = logs[0].name
                finally:
                    if default_process.poll() is None:
                        stop_process_tree(
                            default_process, output, label="default-manager-emergency"
                        )
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
                    result["browser"] = browser_flow(
                        base_url, args.language, version, output, originals, events,
                    )
                    require(process.poll() is None, "Frozen server exited during the browser smoke.")
                finally:
                    stop_process_tree(
                        process, output, label="no-browser", require_graceful=True
                    )
                    wait_port_closed(base_url)
                    process = None
            wait_for_no_pyinstaller_extractions(pyinstaller_temp)
        result["status"] = "passed"
    except Exception as error:
        result["error"] = str(error)
        result["traceback"] = traceback.format_exc()
        print(result["traceback"], file=sys.stderr)
    finally:
        if process is not None:
            try:
                stop_process_tree(process, output, label="emergency-cleanup")
            except Exception as error:
                result["status"] = "failed"
                result["cleanup_error"] = str(error)
        (output / "browser-events.json").write_text(json.dumps(events, ensure_ascii=False, indent=2), encoding="utf-8")
        (output / "smoke-report.json").write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(result, ensure_ascii=True))
    return 0 if result["status"] == "passed" else 1


if __name__ == "__main__":
    raise SystemExit(main())
