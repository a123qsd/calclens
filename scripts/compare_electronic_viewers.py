"""Compare actual water Cube surfaces in CalcLens and a separate local NGL viewer.

NGL is optional tool-only software: install ngl@2.5.0 under work/ngl-reference,
then pass its dist/ngl.js with --ngl-bundle. This script serves only loopback
resources and blocks browser requests to external origins. It never uploads
scientific files or adds an application dependency.
"""

from __future__ import annotations

import argparse
import base64
from hashlib import sha256
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from importlib.metadata import version
import json
from pathlib import Path
import threading
import urllib.parse

import numpy as np
from ase.io.cube import read_cube
from ase.units import Bohr

from smoke_research_workspace import (
    apply_surface, camera, select_dataset, uploaded_files,
)
from smoke_viewer_features import (
    canvas, idle, import_file, instrument, open_auxiliary, open_settings,
    settle, viewer, workspace_server,
)
from smoke_workspace import accept_workspace_dialog, require


ROOT = Path(__file__).resolve().parents[1]
CASE = ROOT / "examples" / "electronic_case"
DEFAULT_OUTPUT = ROOT.parent.parent / "work" / "browser" / "independent-viewer"
NGL_BOHR_ANGSTROM = 0.529177210859

HTML = r"""<!doctype html><html lang="en"><meta charset="utf-8">
<title>Independent NGL water Cube reference</title>
<style>
*{box-sizing:border-box}body{margin:0;padding:24px;font:17px Arial,sans-serif;color:#1c2838;background:white}
h1{font-size:27px;margin:0 0 9px}p{margin:7px 0 18px}main{display:grid;grid-template-columns:1fr 1fr;gap:20px}
article{border:1px solid #cad4dd;border-radius:12px;overflow:hidden}h2{font-size:20px;margin:16px 18px 8px}
.viewport{height:520px;width:100%;background:white}.legend{padding:12px 18px;font-size:15px;line-height:1.5}
.swatch{display:inline-block;width:12px;height:12px;border-radius:50%;margin-right:5px}
footer{margin-top:16px;font-size:14px;color:#455468}
</style>
<h1>NGL 2.5.0 — independent 3D reference</h1>
<p>Original PySCF Cube files · absolute scalar isovalues · original O/H/H coordinates</p>
<main><article id="density-panel"><h2>Electron density</h2><div class="viewport" id="density"></div>
<div class="legend"><span class="swatch" style="background:#4d9db0"></span>ρ = 0.05 e/bohr³<br>
Original 30³ grid · opacity 0.35 · one smoothing iteration</div></article>
<article id="homo-panel"><h2>HOMO — occupied MO 5</h2><div class="viewport" id="homo"></div>
<div class="legend"><span class="swatch" style="background:#8064ad"></span>+ψ = 0.05
<span class="swatch" style="background:#1eaa9a;margin-left:18px"></span>−ψ = −0.05 bohr⁻³ᐟ²<br>
Wavefunction signs, not electric charge · opacity 0.35</div></article></main>
<footer>Local NGL Cube parser + surface renderer. Atom colors: elements. Camera and lighting may differ from CalcLens.</footer>
<script src="/ngl.js"></script><script>
window.referenceReady=false; window.referenceError=null;
const reports={}; const stages={}; const components={};
function meshInfo(surface){return {isovalue:surface.info.isolevel,smoothing:surface.info.smooth,
    position:Array.from(surface.getPosition()),indexCount:surface.getIndex().length};}
async function hexDigest(data){return [...new Uint8Array(await crypto.subtle.digest('SHA-256',data))]
    .map(value=>value.toString(16).padStart(2,'0')).join('');}
async function renderField(name){
    const stage=new NGL.Stage(name,{backgroundColor:'white',cameraType:'perspective',
        sampleLevel:2,quality:'high',clipNear:0,fogNear:80,fogFar:100}); stages[name]=stage;
    const atoms=await stage.loadFile('/water.pdb',{ext:'pdb',defaultRepresentation:false,inferBonds:'none'});
    atoms.addRepresentation('ball+stick',{colorScheme:'element',radiusScale:0.45,aspectRatio:1.5});
    const component=await stage.loadFile('/'+name+'.cube',{ext:'cube',defaultRepresentation:false});
    components[name]=component;
    const volume=component.volume;
    const levels=name==='density'?[0.05]:[0.05,-0.05]; const representations=[];
    for(const level of levels){
        const rep=component.addRepresentation('surface',{isolevelType:'value',isolevel:level,
            negateIsolevel:false,smooth:1,useWorker:false,opacity:0.35,opaqueBack:false,
            colorScheme:'uniform',colorValue:name==='density'?0x4d9db0:level>0?0x8064ad:0x1eaa9a,
            side:'double',boxSize:0,wrap:false,isolevelScroll:false});
        representations.push(rep);
    }
    await new Promise(resolve=>stage.tasks.onZeroOnce(resolve));
    const meshes=representations.map(rep=>meshInfo(rep.repr.surface));
    atoms.autoView(0);
    const q=[0.1484525055,0.3904865563,-0.2044767861,0.8868410086];
    stage.viewerControls.rotate(q.map(value=>value/Math.hypot(...q)));
    const atomPositions=[]; atoms.structure.eachAtom(atom=>atomPositions.push({element:atom.element,
        position:[atom.x,atom.y,atom.z]}));
    reports[name]={runtimeVersion:NGL.Version,isolevelType:'value',isolevels:levels,opacity:0.35,
        smooth:1,spatialUnits:'angstrom after NGL Bohr conversion; scalar values unchanged',
        pointCount:volume.data.length,minimum:volume.min,maximum:volume.max,
        scalarFloat32Sha256:await hexDigest(volume.data.buffer),matrix:volume.matrix.elements,
        atoms:atomPositions,meshes};
}
(async()=>{try{await Promise.all(['density','homo'].map(renderField));
    await new Promise(resolve=>requestAnimationFrame(()=>requestAnimationFrame(resolve)));
    window.referenceReports=reports; window.referenceStages=stages; window.referenceReady=true;
}catch(error){window.referenceError=String(error);console.error(error);}})();
</script></html>"""


def pdb_water() -> str:
    lines = ["REMARK Original water.xyz coordinates translated by +6,+6,+6 angstrom"]
    for index, line in enumerate((CASE / "source" / "water.xyz").read_text().splitlines()[2:], 1):
        element, *raw = line.split()
        x, y, z = (float(value) + 6 for value in raw)
        lines.append(f"HETATM{index:5d} {element + str(index):<4s} HOH A   1    "
                     f"{x:8.3f}{y:8.3f}{z:8.3f}  1.00  0.00          {element:>2s}")
    lines.extend(["CONECT    1    2    3", "END"])
    return "\n".join(lines) + "\n"


def mesh_summary(positions) -> dict:
    points = np.array(positions).reshape(-1, 3)
    require(len(points) > 0 and np.isfinite(points).all(), "A renderer produced an empty/nonfinite mesh.")
    return {"vertices": len(points), "minimum_angstrom": points.min(axis=0).tolist(),
            "maximum_angstrom": points.max(axis=0).tolist(),
            "vertex_mean_angstrom": points.mean(axis=0).tolist()}


def mesh_comparison(first, second) -> dict:
    a = np.array(first).reshape(-1, 3)
    b = np.array(second).reshape(-1, 3)
    distances = np.sqrt(np.sum((a[:, None] - b[None, :]) ** 2, axis=2))
    return {"ngl_to_calclens_max_nearest_vertex_angstrom": float(distances.min(axis=1).max()),
            "calclens_to_ngl_max_nearest_vertex_angstrom": float(distances.min(axis=0).max()),
            "bounds_max_difference_angstrom": float(max(
                np.max(np.abs(a.min(axis=0) - b.min(axis=0))),
                np.max(np.abs(a.max(axis=0) - b.max(axis=0)))))}


def ngl_reference(browser, bundle: Path, output: Path) -> tuple[dict, list]:
    assets = {"/": (HTML.encode(), "text/html; charset=utf-8"),
              "/ngl.js": (bundle.read_bytes(), "text/javascript"),
              "/water.pdb": (pdb_water().encode(), "text/plain"),
              "/density.cube": ((CASE / "density.cube").read_bytes(), "text/plain"),
              "/homo.cube": ((CASE / "homo.cube").read_bytes(), "text/plain"),
              "/favicon.ico": (b"", "image/x-icon")}

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *_args):
            pass

        def do_GET(self):
            path = urllib.parse.urlsplit(self.path).path
            if path not in assets:
                self.send_error(404)
                return
            content, mime = assets[path]
            self.send_response(200)
            self.send_header("Content-Type", mime)
            self.send_header("Content-Length", str(len(content)))
            self.end_headers()
            self.wfile.write(content)

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    origin = f"http://127.0.0.1:{server.server_port}"
    context = browser.new_context(viewport={"width": 1500, "height": 790}, device_scale_factor=1)
    events = []
    context.route("**/*", lambda route: route.continue_()
                  if route.request.url.startswith(origin + "/") else route.abort())
    page = context.new_page()
    page.on("pageerror", lambda error: events.append(str(error)))
    page.on("console", lambda message: events.append(message.text) if message.type == "error" else None)
    try:
        page.goto(origin, wait_until="domcontentloaded")
        page.wait_for_function("() => window.referenceReady || window.referenceError", timeout=60_000)
        require(page.evaluate("window.referenceError") is None,
                f"NGL reference failed: {page.evaluate('window.referenceError')}")
        page.wait_for_timeout(400)
        reports = page.evaluate("window.referenceReports")
        page.screenshot(path=str(output / "ngl-reference.png"), full_page=True)
        for name in ("density", "homo"):
            page.locator(f"#{name}").screenshot(path=str(output / f"ngl-{name}.png"))
        require(not events, f"NGL browser errors: {events}")
        return reports, events
    finally:
        context.close()
        server.shutdown()
        server.server_close()
        thread.join(timeout=10)


def calclens_reference(browser, base_url, output: Path) -> dict:
    from playwright.sync_api import expect

    context = browser.new_context(accept_downloads=True, viewport={"width": 1500, "height": 1000})
    page = context.new_page()
    page.on("dialog", accept_workspace_dialog)
    events = []
    page.on("pageerror", lambda error: events.append(str(error)))
    try:
        page.goto(base_url, wait_until="domcontentloaded")
        idle(page)
        uploaded_files(page, [CASE / "water.cif"])
        open_auxiliary(page)
        for name, kind, units in (("density", "density", "e/bohr^3"),
                                  ("homo", "orbital", "bohr^-3/2")):
            page.get_by_test_id("volume-kind").select_option(kind)
            page.get_by_test_id("volume-units").select_option(units)
            page.get_by_test_id("volume-name").fill(name)
            page.get_by_test_id("volume-source").fill("Actual PySCF 2.12.0 molecular RHF/STO-3G")
            import_file(page, "volume-import", name + ".cube", (CASE / (name + ".cube")).read_bytes(),
                        "text/plain")
            expect(page.get_by_test_id("auxiliary-error")).to_have_count(0)
        open_settings(page)
        viewer(page).locator(".molecule-toolbar select").select_option("1")
        page.get_by_test_id("viewer-color").select_option("element")
        page.get_by_test_id("viewer-quality").select_option("light")
        page.get_by_test_id("viewer-projection").select_option("perspective")
        page.wait_for_timeout(450)
        reports = {}
        viewer(page).get_by_title("Fit atoms", exact=True).click()
        page.wait_for_timeout(450)
        for name in ("density", "homo"):
            select_dataset(page, 0, "viewer-volume-dataset", name)
            instrument(page)
            canvas(page).evaluate("""element => {
                const v=element._3dmol_viewer;const add=v.addIsosurface;
                v.addIsosurface=function(data,...rest){
                    window.__comparisonScalars=new Float32Array(data.data);
                    return add.call(this,data,...rest);
                };
            }""")
            apply_surface(page, 0, opacity="0.35")
            page.wait_for_function("() => window.__featureProbe.isosurfaces.length > 0")
            reports[name] = canvas(page).evaluate("""element => ({
                atoms:element._3dmol_viewer.getModel(0).selectedAtoms({}).map(atom =>
                    ({element:atom.elem,position:[atom.x,atom.y,atom.z]})),
                meshes:window.__featureProbe.isosurfaces.map(item=>({isovalue:item.isoval,
                    position:item.shape.geo.geometryGroups.flatMap(group =>
                        Array.from(group.vertexArray.slice(0,group.vertices*3)))}))
            })""")
            reports[name]["scalarFloat32Sha256"] = page.evaluate("""async () => {
                const bytes=new Uint8Array(await crypto.subtle.digest('SHA-256',
                    window.__comparisonScalars.buffer));
                return [...bytes].map(value=>value.toString(16).padStart(2,'0')).join('');
            }""")
            # One shared orientation for the two quantities; screenshots compare
            # world geometry rather than claiming identical camera conventions.
            if name == "density":
                canvas(page).evaluate("""element => {
                    const v=element._3dmol_viewer;v.rotate(60,'y').rotate(-15,'z').zoom(2.7).render();
                }""")
            settle(page)
            with page.expect_download() as pending:
                page.get_by_test_id("viewer-export-png").click()
            pending.value.save_as(output / f"calclens-{name}.png")
            reports[name]["camera"] = camera(page)
        require(not events, f"CalcLens reference browser errors: {events}")
        return reports
    finally:
        context.close()


def comparison_figure(output: Path) -> None:
    """Lay out untouched renderer screenshots in a local browser document."""
    from playwright.sync_api import sync_playwright

    def image(name):
        encoded = base64.b64encode((output / name).read_bytes()).decode("ascii")
        return f'<img alt="{name}" src="data:image/png;base64,{encoded}">'

    html = """<!doctype html><meta charset="utf-8"><style>
    *{box-sizing:border-box}body{margin:0;padding:26px;font:17px Arial,sans-serif;color:#172637;background:#fff}
    h1{font-size:28px;margin:0 0 8px}p{margin:6px 0 16px;color:#435264}
    .grid{display:grid;grid-template-columns:1fr 1fr;gap:14px}
    h2{font-size:21px;margin:10px 0}article{border:1px solid #cbd6df;border-radius:10px;overflow:hidden}
    h3{font-size:17px;margin:14px 18px 0}img{width:100%;height:330px;object-fit:contain;display:block}
    footer{font-size:15px;line-height:1.5;margin-top:15px;color:#3a4d60}
    </style><h1>Same water Cube data in two 3D viewers</h1>
    <p>Original 30³ scalar grids and O/H/H coordinates · absolute thresholds · opacity 0.35 · smoothing 1</p>
    <div class="grid"><h2>CalcLens · 3Dmol 2.5.5</h2><h2>Independent NGL 2.5.0</h2>
    <article><h3>Electron density · 0.05 e/bohr³</h3>"""
    html += image("calclens-density.png") + "</article><article><h3>Electron density · 0.05 e/bohr³</h3>"
    html += image("ngl-density.png") + "</article><article><h3>HOMO · +0.05 / −0.05 bohr⁻³ᐟ²</h3>"
    html += image("calclens-homo.png") + "</article><article><h3>HOMO · +0.05 / −0.05 bohr⁻³ᐟ²</h3>"
    html += image("ngl-homo.png") + """</article></div><footer>
    Both engines preserve the original float32 scalar arrays. The HOMO has two opposite-sign lobes.<br>
    Rendered boundaries differ: different triangulation and smoothing implementations;
    world-space boundary differences are about 0.17 Å on this coarse grid.<br>
    Camera orientation, atom radii and lighting differ. This compares field display and data mapping,
    not pixel identity or electronic-structure accuracy.</footer>"""
    with sync_playwright() as pw:
        browser = pw.chromium.launch(headless=True)
        try:
            page = browser.new_page(viewport={"width": 1500, "height": 1100})
            page.set_content(html, wait_until="load")
            page.screenshot(path=str(output / "comparison.png"), full_page=True)
        finally:
            browser.close()


def main() -> int:
    from playwright.sync_api import sync_playwright

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--ngl-bundle", type=Path, required=True)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args()
    output = args.output.resolve()
    output.mkdir(parents=True, exist_ok=True)
    bundle = args.ngl_bundle.resolve()
    package = json.loads((bundle.parent.parent / "package.json").read_text())
    require(package["name"] == "ngl" and package["version"] == "2.5.0",
            "Use the recorded tool-only ngl@2.5.0 package.")
    with sync_playwright() as pw:
        browser = pw.chromium.launch(headless=True, args=["--enable-webgl", "--ignore-gpu-blocklist",
                                                        "--enable-unsafe-swiftshader"])
        chromium_version = browser.version
        try:
            ngl, _events = ngl_reference(browser, bundle, output)
            with workspace_server() as url:
                calclens = calclens_reference(browser, url, output)
        finally:
            browser.close()
    result = {"status": "passed", "ngl_package_version": package["version"],
              "playwright_version": version("playwright"), "chromium_version": chromium_version,
              "ngl_bundle_sha256": sha256(bundle.read_bytes()).hexdigest(),
              "scalar_isovalue_type": "absolute value; not sigma", "opacity": 0.35,
              "smoothing_iterations": 1, "atom_colors": "element", "projection": "perspective",
              "fields": {},
              "ngl_bohr_to_angstrom": NGL_BOHR_ANGSTROM,
              "calclens_bohr_to_angstrom": 0.529177210903,
              "external_file_transmission": False,
              "references": [
                  "https://github.com/nglviewer/ngl/blob/v2.5.0/src/parser/cube-parser.ts",
                  "https://github.com/nglviewer/ngl/blob/v2.5.0/src/representation/surface-representation.ts",
                  "https://github.com/3dmol/3Dmol.js/blob/2.5.5/src/GLShape.ts",
              ]}
    for name in ("density", "homo"):
        with (CASE / f"{name}.cube").open() as handle:
            reference = read_cube(handle, read_data=True)
        expected_hash = sha256(np.array(reference["data"], dtype="<f4").tobytes()).hexdigest()
        require(ngl[name]["scalarFloat32Sha256"] == expected_hash,
                "NGL did not preserve the exact Cube scalar array at float32 precision.")
        require(calclens[name]["scalarFloat32Sha256"] == expected_hash,
                "CalcLens/3Dmol did not preserve the exact Cube scalar array at float32 precision.")
        require(ngl[name]["pointCount"] == 27_000 and ngl[name]["isolevelType"] == "value",
                "NGL used a different grid or isovalue convention.")
        require(np.allclose([atom["position"] for atom in ngl[name]["atoms"]],
                            [atom["position"] for atom in calclens[name]["atoms"]],
                            atol=1e-6, rtol=0), "The viewers displayed different water coordinates.")
        require([atom["element"] for atom in ngl[name]["atoms"]]
                == [atom["element"] for atom in calclens[name]["atoms"]] == ["O", "H", "H"],
                "The viewers displayed different atom elements or ordering.")
        spacing = reference["spacing"] / Bohr * NGL_BOHR_ANGSTROM
        origin = reference["origin"] / Bohr * NGL_BOHR_ANGSTROM
        expected_matrix = [*spacing[2], 0, *spacing[1], 0, *spacing[0], 0, *origin, 1]
        require(np.allclose(ngl[name]["matrix"], expected_matrix, atol=1e-12, rtol=0),
                "NGL's Cube world-coordinate transform differs from the checked unit/order mapping.")
        meshes = []
        for first in ngl[name]["meshes"]:
            second = next(item for item in calclens[name]["meshes"]
                          if item["isovalue"] == first["isovalue"])
            require(first["isovalue"] in (0.05, -0.05), "A reference used a different isovalue.")
            meshes.append({"isovalue": first["isovalue"],
                           "ngl": mesh_summary(first["position"]),
                           "calclens_3dmol": mesh_summary(second["position"]),
                           "comparison": mesh_comparison(first["position"], second["position"])})
        result["fields"][name] = {"original_cube_sha256": sha256((CASE / f"{name}.cube").read_bytes()).hexdigest(),
                                  "units": "e/bohr^3" if name == "density" else "bohr^-3/2",
                                  "float32_scalar_sha256": expected_hash, "point_count": 27_000,
                                  "ngl_runtime_version": ngl[name]["runtimeVersion"], "meshes": meshes}
    (output / "comparison.json").write_text(json.dumps(result, indent=2, allow_nan=False) + "\n")
    (output / "water-display.pdb").write_text(pdb_water())
    comparison_figure(output)
    names = ["ngl-reference.png", "ngl-density.png", "ngl-homo.png", "calclens-density.png",
             "calclens-homo.png", "comparison.png", "comparison.json", "water-display.pdb"]
    manifest = {"script": "scripts/compare_electronic_viewers.py",
                "script_sha256": sha256(Path(__file__).read_bytes()).hexdigest(),
                "sha256": {name: sha256((output / name).read_bytes()).hexdigest() for name in names}}
    (output / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n")
    print(json.dumps(result, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
