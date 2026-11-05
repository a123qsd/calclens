"""Measure viewer updates and check them in a real Chromium/WebGL session.

Run against `npm run dev` with --mode baseline before a change, then --mode
verify afterwards. The fixture replaces only the browser's main.tsx response;
production source and the Python analysis service are not modified.
"""
from __future__ import annotations

import argparse
from contextlib import contextmanager
import json
from pathlib import Path
import re
import statistics
import socket
import subprocess
import time
import urllib.error
import urllib.request

ROOT = Path(__file__).resolve().parents[1]


def require(condition, message):
    if not condition:
        raise AssertionError(message)


def fixture():
    positions = [[(i % 20) * 1.55, (i // 20) * 1.55, 0] for i in range(400)]
    contact = {"i": 0, "j": 1, "element_i": "C", "element_j": "C",
               "shift": [0, 0, 0], "distance_angstrom": 1.55, "is_self_image": False}
    return {
        "schema_version": "1.1", "formula": "C400", "atom_count": 400,
        "elements": ["C"] * 400, "positions": positions,
        "scaled_positions": [[p[0] / 32, p[1] / 32, 0] for p in positions],
        "cell": [[32, 0, 0], [0, 32, 0], [0, 0, 12]],
        "periodic_axes": [True, True, True], "normal_axis": "c", "normal_axis_index": 2,
        "in_plane_axes": ["a", "b"], "review_required": False, "gap_review_required": False,
        "metrics": {"minimum_distance_angstrom": 1.55, "minimum_pair": contact,
                    "c_height_angstrom": 12, "normal_height_angstrom": 12,
                    "nuclei_thickness_angstrom": 0, "nuclei_gap_angstrom": 12,
                    "gap_fraction": 1, "gap_start_fraction": 0, "gap_end_fraction": 1,
                    "second_largest_gap_angstrom": 0},
        "short_distance_threshold_angstrom": 1, "short_contacts": [],
        "short_contact_count": 0, "short_contacts_truncated": False,
        "issues": [], "assumptions": [], "limitations": [],
    }


def harness(source):
    react = re.search(r'from "([^"]*/react\.js[^\"]*)"', source)
    dom = re.search(r'from "([^"]*/react-dom_client\.js[^\"]*)"', source)
    require(react and dom, "Expected the Vite-transformed React entry module.")
    return f'''
import React from {json.dumps(react.group(1))};
import ReactDOM from {json.dumps(dom.group(1))};
import MolecularViewer from '/src/MolecularViewer.tsx';
import '/src/styles.css';
const root = ReactDOM.createRoot(document.getElementById('root'));
document.getElementById('root').style.cssText = 'width:1100px;margin:20px auto';
const initial = {json.dumps(fixture())};
let props = {{report: initial, language: 'en', onAtomPick: atom => {{window.__lastPick = atom;}}}};
const render = () => root.render(React.createElement(React.StrictMode, null,
    React.createElement(MolecularViewer, props)));
window.__viewerHarness = {{
    setProps(patch) {{props = {{...props, ...patch}}; render();}},
    get report() {{return props.report;}},
    reset() {{props = {{...props, report: structuredClone(initial), language: 'en',
        highlight: null, highlightGap: false, highlightedAtomIndices: undefined}}; render();}},
}};
render();
'''


INSTRUMENT = """() => {
    const canvas = document.querySelector('[data-testid="molecule-canvas"] canvas');
    const viewer = canvas._3dmol_viewer;
    const counters = {addModel: 0, removeAllModels: 0, addAtoms: 0, removeAtoms: 0,
        baseAddAtoms: 0, setStyle: 0, render: 0, show: 0, renderMs: 0, modelMs: 0};
    const labels = new Map();
    window.__viewerProbe = {viewer, counters, labels};
    const addLabel = viewer.addLabel;
    viewer.addLabel = function(...args) {
        const label = addLabel.apply(this, args);
        labels.set(label, String(args[0]));
        return label;
    };
    const removeLabels = viewer.removeAllLabels;
    viewer.removeAllLabels = function(...args) {
        labels.clear();
        return removeLabels.apply(this, args);
    };
    const wrapModel = model => {
        if (model.__viewerProbeWrapped) return model;
        model.__viewerProbeWrapped = true;
        for (const name of ['addAtoms', 'removeAtoms', 'setStyle']) {
            const original = model[name];
            model[name] = function(...args) {
                counters[name]++;
                if (name === 'addAtoms' && model.getID() === 0) counters.baseAddAtoms++;
                const start = performance.now();
                try { return original.apply(this, args); }
                finally { counters.modelMs += performance.now() - start; }
            };
        }
        return model;
    };
    for (const name of ['addModel', 'removeAllModels', 'render', 'show']) {
        const original = viewer[name];
        viewer[name] = function(...args) {
            counters[name]++;
            const start = performance.now();
            try {
                const result = original.apply(this, args);
                return name === 'addModel' ? wrapModel(result) : result;
            } finally {
                if (name === 'render') counters.renderMs += performance.now() - start;
            }
        };
    }
    wrapModel(viewer.getModel(0));
    wrapModel(viewer.getModel(1));
    const gl = viewer.renderer.context;
    return {atoms: viewer.getModel(0).selectedAtoms({}).length,
        renderer: gl.getParameter(gl.RENDERER), version: gl.getParameter(gl.VERSION),
        userAgent: navigator.userAgent, hardwareConcurrency: navigator.hardwareConcurrency};
}"""


MEASURE = """async action => {
    const {viewer, counters} = window.__viewerProbe;
    const before = {...counters};
    const model = viewer.getModel(0);
    const beforeView = viewer.getView();
    const start = performance.now();
    if (action.title) {
        const button = [...document.querySelectorAll('.molecule-toolbar button')]
            .find(node => node.title === action.title);
        if (!button) throw Error('Missing toolbar action: ' + action.title);
        button.click();
    } else if (action.patch) {
        window.__viewerHarness.setProps(action.patch);
    } else if (action.cloneReport) {
        window.__viewerHarness.setProps({report: structuredClone(window.__viewerHarness.report)});
    }
    await new Promise(resolve => requestAnimationFrame(() => requestAnimationFrame(resolve)));
    const afterView = viewer.getView();
    return {elapsedMs: performance.now() - start, sameModel: model === viewer.getModel(0),
        cameraDelta: Math.max(...beforeView.map((n, i) => Math.abs(n - afterView[i]))),
        counters: Object.fromEntries(Object.entries(counters).map(([k,v]) => [k, v-before[k]]))};
}"""


def run(url, output, mode, samples, browser_executable=None):
    from playwright.sync_api import sync_playwright, expect

    output.mkdir(parents=True, exist_ok=True)
    results = {"status": "failed", "mode": mode, "url": url, "samples": samples,
               "benchmark": {}, "checks": [], "page_errors": [], "console_errors": []}
    with sync_playwright() as pw:
        browser = pw.chromium.launch(headless=True, executable_path=browser_executable, args=[
            "--enable-webgl", "--ignore-gpu-blocklist", "--enable-unsafe-swiftshader",
        ])
        context = browser.new_context(viewport={"width": 1400, "height": 900})
        page = context.new_page()
        page.on("pageerror", lambda error: results["page_errors"].append(str(error)))
        page.on("console", lambda msg: results["console_errors"].append(msg.text)
                if msg.type == "error" else None)

        def replace_entry(route):
            response = route.fetch()
            route.fulfill(response=response, body=harness(response.text()),
                          content_type="text/javascript")

        page.route("**/src/main.tsx", replace_entry)
        try:
            page.goto(url, wait_until="networkidle", timeout=60_000)
            page.wait_for_function("""() => {
                const canvas = document.querySelector('[data-testid="molecule-canvas"] canvas');
                return canvas?._3dmol_viewer?.getModel(0)?.selectedAtoms({}).length === 3600;
            }""", timeout=60_000)
            expect(page.locator(".molecule-fallback")).to_have_count(0)
            results["environment"] = page.evaluate(INSTRUMENT)
            results["checks"].append("400 source sites create 3,600 displayed atoms")

            operations = [
                ("spin_start", {"title": "Rotate"}, False),
                ("spin_stop", {"title": "Stop rotation"}, False),
                ("labels_on", {"title": "Atom IDs"}, True),
                ("labels_off", {"title": "Atom IDs"}, True),
                ("cell_on", {"title": "Unit cell"}, True),
                ("cell_off", {"title": "Unit cell"}, True),
                ("bonds_off", {"title": "Display bonds"}, True),
                ("bonds_on", {"title": "Display bonds"}, True),
                ("highlight_atoms", {"patch": {"highlightedAtomIndices": [0]}}, True),
                ("clear_highlight", {"patch": {"highlightedAtomIndices": []}}, True),
                ("language_ko", {"patch": {"language": "ko"}}, True),
                ("language_en", {"patch": {"language": "en"}}, True),
                ("equal_report", {"cloneReport": True}, True),
                ("contact_inside", {"patch": {"highlight": fixture()["metrics"]["minimum_pair"]}}, False),
                ("contact_clear", {"patch": {"highlight": None}}, True),
                ("gap_on", {"patch": {"highlightGap": True}}, False),
                ("gap_off", {"patch": {"highlightGap": False}}, True),
            ]
            for _ in range(samples):
                for name, action, preserve_camera in operations:
                    outcome = page.evaluate(MEASURE, action)
                    results["benchmark"].setdefault(name, {"runs": []})["runs"].append(outcome)
                    if mode == "verify":
                        require(outcome["sameModel"], f"{name} replaced the unchanged atom model.")
                        require(outcome["counters"]["removeAllModels"] == 0,
                                f"{name} removed all models.")
                        require(outcome["counters"]["baseAddAtoms"] == 0,
                                f"{name} re-added unchanged atoms.")
                    if name == "labels_on":
                        require(page.evaluate("window.__viewerProbe.labels.size") == 180,
                                "Atom label limit or visible labels changed.")
                        if mode == "verify":
                            require(outcome["counters"]["show"] < 10,
                                    "Labels triggered a redraw per label instead of one batch.")
                        if len(results["benchmark"][name]["runs"]) == 1:
                            page.screenshot(path=str(output / "viewer-labels-3600.png"))
                    elif name == "labels_off":
                        require(page.evaluate("window.__viewerProbe.labels.size") == 0,
                                "Turning off atom labels left old labels in the viewer.")
                    if preserve_camera:
                        require(outcome["cameraDelta"] < 1e-7,
                                f"{name} changed the camera: {outcome['cameraDelta']}")
                    # Wait for zoom completion; software WebGL may stretch a nominal 350 ms animation.
                    if name in ("contact_inside", "gap_on"):
                        page.wait_for_function("!window.__viewerProbe.viewer.isAnimated()", timeout=30_000)
            for detail in results["benchmark"].values():
                detail["median_ms"] = statistics.median(r["elapsedMs"] for r in detail["runs"])
                detail["model_rebuilds"] = sum(r["counters"]["removeAllModels"] for r in detail["runs"])
                detail["median_render_ms"] = statistics.median(
                    r["counters"]["renderMs"] for r in detail["runs"])
            results["checks"].append("toolbar, language and highlight changes preserve camera as intended")

            # Check selection style is applied to all nine copies and removed again.
            page.evaluate(MEASURE, {"patch": {"highlightedAtomIndices": [0]}})
            highlighted = page.evaluate("""() => window.__viewerProbe.viewer.getModel(0)
                .selectedAtoms({}).filter(a => (a.style.sphere?.colorfunc?.(a)
                    ?? a.style.sphere?.color)?.toUpperCase() === '#F59E0B').length""")
            require(highlighted == 9, f"Expected nine highlighted copies, got {highlighted}.")
            page.evaluate(MEASURE, {"patch": {"highlightedAtomIndices": []}})
            require(page.evaluate("""() => window.__viewerProbe.viewer.getModel(0)
                .selectedAtoms({}).every(a => (a.style.sphere?.colorfunc?.(a)
                    ?? a.style.sphere?.color)?.toUpperCase() !== '#F59E0B')"""),
                "Clearing a selection left stale highlight styles.")
            results["checks"].append("all repeated atom highlights update and clear")

            if mode == "verify":
                expect(page.get_by_test_id("viewer-counts")).to_contain_text("Original cell: 400")
                expect(page.get_by_test_id("viewer-counts")).to_contain_text("Displayed atoms: 3600")
                expect(page.get_by_test_id("viewer-counts")).to_contain_text("3×3×1")
                page.get_by_title("Atom IDs", exact=True).click()
                page.wait_for_function("window.__viewerProbe.labels.size === 180")
                require(page.evaluate("[...window.__viewerProbe.labels.values()].every(text => text !== 'C400')"),
                        "The label-priority fixture unexpectedly starts with C400 visible.")
                page.evaluate(MEASURE, {"patch": {"highlightedAtomIndices": [399]}})
                expect(page.get_by_test_id("viewer-notices")).to_contain_text("180/3600")
                require(page.evaluate("[...window.__viewerProbe.labels.values()].filter(text => text === 'C400').length") == 9,
                        "The label cap omitted highlighted atoms outside the first 180 display entries.")
                page.get_by_title("Atom IDs", exact=True).click()
                page.evaluate("""() => {
                    const report = structuredClone(window.__viewerHarness.report);
                    report.positions = report.positions.map((_, i) => [i % 20, Math.floor(i / 20), 0]);
                    report.scaled_positions = report.positions.map(p => [p[0] / 32, p[1] / 32, 0]);
                    window.__viewerHarness.setProps({report, highlightedAtomIndices: []});
                }""")
                expect(page.get_by_test_id("viewer-notices")).to_contain_text("8,000")
                require(page.evaluate("window.__viewerProbe.viewer.getModel(0).selectedAtoms({}).reduce((n,a)=>n+a.bonds.length,0)/2") == 8000,
                        "The disclosed connection cap does not match the displayed connections.")
                page.evaluate("window.__viewerHarness.reset()")
                page.wait_for_function("window.__viewerProbe.viewer.getModel(0).selectedAtoms({})[1].x - window.__viewerProbe.viewer.getModel(0).selectedAtoms({})[0].x > 1.5")
                results["checks"].append("source/display counts and caps are disclosed; selected labels have priority")

            # Repeat and coordinate changes must rebuild the actual model.
            page.locator(".molecule-toolbar select").select_option("1")
            page.wait_for_function("window.__viewerProbe.viewer.getModel(0).selectedAtoms({}).length === 400")
            contact = dict(fixture()["metrics"]["minimum_pair"])
            contact.update({"start_shift": [-2, 0, 0], "end_shift": [2, 0, 0]})
            page.evaluate(MEASURE, {"patch": {"highlight": contact}})
            page.wait_for_function("!window.__viewerProbe.viewer.isAnimated()", timeout=30_000)
            endpoints = page.evaluate("""() => window.__viewerProbe.viewer.getModel(0).selectedAtoms({})
                .filter(a => a.style.sphere?.color === '#F59E0B').map(a => [a.x, a.y, a.z])""")
            require([-64, 0, 0] in endpoints and [65.55, 0, 0] in endpoints,
                    f"Out-of-repeat contact endpoints are missing: {endpoints}")
            require(page.evaluate("window.__viewerProbe.viewer.getModel(0).selectedAtoms({}).length") == 402,
                    "Out-of-repeat contact did not add exactly two atoms.")
            page.evaluate(MEASURE, {"patch": {"highlight": None}})
            require(page.evaluate("window.__viewerProbe.viewer.getModel(0).selectedAtoms({}).length") == 400,
                    "Clearing a contact retained extra endpoint atoms.")
            results["checks"].append("1x1 repeat adds and removes contact atoms outside the repeated region")

            page.evaluate("""() => {
                const report = structuredClone(window.__viewerHarness.report);
                report.positions[0][2] = 0.25;
                window.__viewerHarness.setProps({report});
            }""")
            page.wait_for_function("window.__viewerProbe.viewer.getModel(0).selectedAtoms({})[0].z === 0.25")
            results["checks"].append("changed coordinates replace stale atom positions")

            # Metric-only updates must move gap boundaries without rebuilding the atoms.
            page.evaluate(MEASURE, {"patch": {"highlightGap": True}})
            page.wait_for_function("!window.__viewerProbe.viewer.isAnimated()", timeout=30_000)
            gap_report = page.evaluate("structuredClone(window.__viewerHarness.report)")
            gap_report["metrics"].update({"gap_start_fraction": 0.2, "gap_fraction": 0.5})
            gap_update = page.evaluate(MEASURE, {"patch": {"report": gap_report}})
            if mode == "verify":
                require(gap_update["sameModel"] and gap_update["counters"]["baseAddAtoms"] == 0,
                        "Metric-only gap updates rebuilt unchanged atoms.")
            boundaries = page.evaluate("""() => {
                const {viewer, labels} = window.__viewerProbe;
                return {
                    cornerHeights: viewer.getModel(1).selectedAtoms({}).map(a => a.z),
                    shapeHeights: viewer.shapes.filter(Boolean).map(shape => shape.geo.geometryGroups
                        .flatMap(group => Array.from(group.vertexArray.slice(0, group.vertices * 3))
                            .filter((_, index) => index % 3 === 2))),
                    labelHeights: [...labels.keys()].map(label => label.stylespec.position.z),
                };
            }""")
            for expected_height in (2.4, 8.4):
                require(sum(abs(z - expected_height) < 1e-8 for z in boundaries["cornerHeights"]) == 4,
                        f"Gap fitting corners did not move to {expected_height} Å.")
            require(len(boundaries["shapeHeights"]) == 10 and all(
                heights and all(min(abs(z - 2.4), abs(z - 8.4)) < 1e-5 for z in heights)
                for heights in boundaries["shapeHeights"]
            ), f"Rendered gap faces/edges retained stale heights: {boundaries!r}")
            require(len(boundaries["labelHeights"]) == 1
                    and abs(boundaries["labelHeights"][0] - 2.4) < 1e-8,
                    "The gap label retained its old position.")
            page.evaluate(MEASURE, {"patch": {"highlightGap": False}})
            results["checks"].append("metric-only gap updates move rendered boundaries, label and fitting corners")

            # Use a small, clear fixture for picking and reset checks.
            small = fixture()
            small.update({"formula": "C2", "atom_count": 2, "elements": ["C", "C"],
                          "positions": [[0, 0, 0], [1.4, 0, 0]],
                          "scaled_positions": [[0, 0, 0], [0.35, 0, 0]],
                          "cell": [[4, 0, 0], [0, 4, 0], [0, 0, 12]]})
            page.evaluate(MEASURE, {"patch": {"report": small}})
            page.locator(".molecule-toolbar select").select_option("3")
            page.wait_for_function("window.__viewerProbe.viewer.getModel(0).selectedAtoms({}).length === 18")
            # Preserve coordinates and formula to ensure element identity invalidates connectivity.
            changed_elements = dict(small, elements=["C", "He"])
            page.evaluate(MEASURE, {"patch": {"report": changed_elements}})
            changed_atoms = page.evaluate("""() => window.__viewerProbe.viewer.getModel(0)
                .selectedAtoms({}).map(a => ({element: a.elem, bonds: a.bonds}))""")
            require(sum(atom["element"] == "He" for atom in changed_atoms) == 9,
                    "An element-only update left stale species in the model.")
            require(all(not atom["bonds"] for atom in changed_atoms),
                    "An element-only update retained the old C-C connectivity.")
            page.evaluate(MEASURE, {"patch": {"report": small}})
            page.get_by_title("Display bonds", exact=True).click()
            page.get_by_title("Display bonds", exact=True).click()
            page.evaluate(MEASURE, {"patch": {"highlightedAtomIndices": [0]}})
            results["checks"].append("element-only updates refresh species and connectivity")
            page.get_by_title("Reset", exact=True).click()
            page.wait_for_timeout(100)
            first_view = page.evaluate("window.__viewerProbe.viewer.getView()")
            page.get_by_title("Reset", exact=True).click()
            page.wait_for_timeout(100)
            second_view = page.evaluate("window.__viewerProbe.viewer.getView()")
            require(max(abs(a-b) for a, b in zip(first_view, second_view)) < 1e-7,
                    "Repeated Reset changed the camera.")
            point = page.evaluate("""() => {
                const viewer = window.__viewerProbe.viewer;
                const atom = viewer.getModel(0).selectedAtoms({}).find(a =>
                    a.properties.calclensIndex === 0 && a.properties.calclensShift.join() === '1,0,0');
                const p = viewer.modelToScreen(atom); return {x:p.x, y:p.y};
            }""")
            page.mouse.click(point["x"], point["y"])
            expect(page.locator(".molecule-status")).to_contain_text("Selected: C1 · [1, 0, 0]")
            require(page.evaluate("window.__lastPick") == {"index": 0, "shift": [1, 0, 0], "element": "C"},
                    "Repeated atom pick lost original index/shift/element.")
            results["checks"].append("camera reset is idempotent and picking remains correct after style changes")
            expect(page.locator(".molecule-fallback")).to_have_count(0)
            require(not results["page_errors"], f"Browser errors: {results['page_errors']}")
            require(not results["console_errors"], f"Console errors: {results['console_errors']}")
            page.get_by_title("Atom IDs", exact=True).click()
            page.wait_for_function("window.__viewerProbe.labels.size === 18")
            page.screenshot(path=str(output / "viewer-final.png"))
            results["status"] = "passed"
        finally:
            (output / "results.json").write_text(json.dumps(results, indent=2), encoding="utf-8")
            browser.close()
    return results


@contextmanager
def dev_server(output):
    """Start an isolated local Vite server; no external API/backend is needed."""
    output.mkdir(parents=True, exist_ok=True)
    with socket.socket() as reservation:
        reservation.bind(("127.0.0.1", 0))
        port = reservation.getsockname()[1]
    url = f"http://127.0.0.1:{port}"
    command = ["node", str(ROOT / "frontend/node_modules/vite/bin/vite.js"),
               "--host", "127.0.0.1", "--port", str(port), "--strictPort"]
    with (output / "vite.log").open("w", encoding="utf-8") as log:
        process = subprocess.Popen(command, cwd=ROOT / "frontend", stdout=log, stderr=log)
        try:
            deadline = time.monotonic() + 30
            while time.monotonic() < deadline:
                require(process.poll() is None, "Vite failed to start; see vite.log.")
                try:
                    with urllib.request.urlopen(url, timeout=1) as response:
                        if response.status == 200:
                            break
                except (urllib.error.URLError, TimeoutError):
                    time.sleep(0.1)
            else:
                raise TimeoutError("Vite did not become ready within 30 seconds.")
            yield url
        finally:
            process.terminate()
            try:
                process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(timeout=5)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--url", default=None, help="Existing Vite server; omitted starts a temporary one")
    parser.add_argument("--mode", choices=["baseline", "verify"], default="verify")
    parser.add_argument("--samples", type=int, default=3)
    parser.add_argument("--browser-executable", default=None)
    parser.add_argument("--output", type=Path, default=ROOT.parent / "viewer-updates")
    args = parser.parse_args()
    require(args.samples > 0, "--samples must be positive")
    output = args.output.resolve()
    if args.url:
        result = run(args.url, output, args.mode, args.samples, args.browser_executable)
    else:
        with dev_server(output) as url:
            result = run(url, output, args.mode, args.samples, args.browser_executable)
    print(json.dumps({"status": result["status"], "checks": result["checks"],
                      "benchmark": {k: {"median_ms": round(v["median_ms"], 2),
                                         "model_rebuilds": v["model_rebuilds"]}
                                    for k, v in result["benchmark"].items()}}, indent=2))


if __name__ == "__main__":
    main()
