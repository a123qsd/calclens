"""Build the portable H₂ example from its local, hash-recorded SCF outputs."""

from hashlib import sha256
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from slab_preflight.density import cube_bytes, density_difference, parse_cube  # noqa: E402
from slab_preflight.project import Project, ProjectEntry, dumps_project_archive  # noqa: E402


def build(directory):
    case = json.loads((directory / "case.json").read_text())
    cif = (directory / case["structure"]).read_bytes()
    digest = sha256(cif).hexdigest()
    originals = {}
    grids = []
    for kind in ("AB", "A", "B"):
        entry = next(x for x in case["density_sources"] if x["role"] == kind)
        path = directory / entry["path"]
        data = path.read_bytes()
        original_digest = sha256(data).hexdigest()
        if original_digest != case["files"][entry["path"]]["sha256"]:
            raise ValueError(f"Changed input: {path.name}")
        originals[kind] = {"raw": data.decode("utf-8"), "filename": path.name}
        grids.append(parse_cube(data, kind="density", units=entry["units"], source_name=path.name))
    method = case["common_method"]
    conditions = case["reference_conditions"]
    axis = case["normal_axis"]
    result = density_difference(
        *grids,
        a_indices=case["a_indices"],
        b_indices=case["b_indices"],
        method=method,
        reference_conditions=conditions,
        frozen_geometry=True,
        axis=axis,
        device="cpu",
    )
    uid = "h2-frozen-difference"
    data = cube_bytes(result.grid).decode("utf-8")
    volume = {
        "id": uid,
        "name": "Δρ · H₂",
        "filename": "h2-difference.cube",
        "kind": "difference_density",
        "units": result.grid.units,
        "source": method,
        "rawText": data,
    }
    record = {
        "sources": originals,
        "units": "e/bohr^3",
        "a_indices": case["a_indices"],
        "b_indices": case["b_indices"],
        "method": method,
        "conditions": conditions,
        "frozen": True,
        "axis": axis,
        "result_id": uid,
    }
    project = Project(
        [
            ProjectEntry(
                "h2-frozen",
                "h2.cif",
                cif,
                note="Isolated H₂ UHF/STO-3G. Fixed 0.74 Å gas-phase geometry; the CIF is a display container.",
            )
        ],
        selected_id="h2-frozen",
        workspace_state={
            "schema_version": 1,
            "auxiliary": {},
            "drafts": {},
            "viewers": {},
            "comparison": {
                "rangeMode": "shared",
                "manualMin": "-1",
                "manualMax": "1",
                "sync": False,
                "before": "",
                "after": "",
            },
            "view": "overview",
            "native_research": {
                "schema_version": 1,
                "selections": {
                    digest: {
                        "charge": None,
                        "volume": uid,
                        "surface": True,
                        "level": 0.12,
                        "opacity": 0.45,
                    }
                },
                "signed": {digest: [volume]},
                "differences": {digest: {uid: record}},
            },
        },
    )
    return dumps_project_archive(project)


if __name__ == "__main__":
    base = ROOT / "examples/research_cases/h2_density"
    output = base / "h2-density.calclens.zip"
    output.write_bytes(build(base))
    print(output.name, output.stat().st_size, sha256(output.read_bytes()).hexdigest())
