"""Archive replay validates historical inputs without current slab assumptions."""

from copy import deepcopy
from hashlib import sha256
from pathlib import Path

import numpy as np

from slab_preflight.core import analyze_cif
from slab_preflight.density import cube_bytes, parse_cube
from slab_preflight.density_records import (
    calculation_record, freeze_difference_inputs, migrate_difference, replay_difference,
    validate_computation,
)
from slab_preflight.project import Project, ProjectEntry

ROOT = Path(__file__).resolve().parents[1]
CIF = b"""data_skew_plane
_cell_length_a 2
_cell_length_b 2
_cell_length_c 10
_cell_angle_alpha 90
_cell_angle_beta 90
_cell_angle_gamma 120
_space_group_IT_number 1
_space_group_name_H-M_alt 'P 1'
loop_
_space_group_symop_operation_xyz
'x,y,z'
loop_
_atom_site_label
_atom_site_type_symbol
_atom_site_fract_x
_atom_site_fract_y
_atom_site_fract_z
_atom_site_occupancy
H1 H 0 0 0.5 1
H2 H 0.37 0 0.5 1
"""


def cube(positions, value):
    rows = ["Synthetic validation fixture", "Not an electronic calculation",
            f"{len(positions)} 0 0 5", "-2 1 0 0", "-2 0 1 0", "-2 0 0 1"]
    rows += ["1 1 " + " ".join(map(str, xyz)) for xyz in positions]
    rows.append(" ".join([str(value)] * 8))
    return "\n".join(rows) + "\n"


def retained(*, legacy=False):
    digest = sha256(CIF).hexdigest()
    entry = {"id": "skew", "sha256": digest, "normal_axis": "c", "short_distance": 1,
             "analysis": {"report": analyze_cif(CIF)}}
    sources = {"AB": {"filename": "AB.cube", "raw": cube([(0, 0, 5), (.74, 0, 5)], 1)},
               "A": {"filename": "A.cube", "raw": cube([(0, 0, 5)], .3)},
               "B": {"filename": "B.cube", "raw": cube([(.74, 0, 5)], .4)}}
    bundle = {"sources": sources, "units": "e/angstrom^3", "a_indices": [1], "b_indices": [2],
              "method": "Synthetic method declaration", "conditions": "Fixed numerical test conditions",
              "frozen": True, "axis": 2, "result_id": "difference"}
    if not legacy:
        bundle = freeze_difference_inputs(bundle, entry)
    result = replay_difference(bundle, entry)
    if not legacy:
        bundle["computation"] = deepcopy(result.to_dict())
    item = {"id": "difference", "name": "Test Δρ", "filename": "difference.cube",
            "kind": "difference_density", "units": "e/angstrom^3", "source": bundle["method"],
            "rawText": cube_bytes(result.grid).decode()}
    if not legacy:
        bundle["result_sha256"] = sha256(item["rawText"].encode()).hexdigest()
    state = {"native_research": {"schema_version": 1, "signed": {digest: [item]},
                                 "selections": {digest: {"volume": "difference", "surface": False}},
                                 "differences": {digest: {"difference": bundle}}}}
    project = Project([ProjectEntry("skew", "skew.cif", CIF, "c", note="Original memo · 메모")],
                      selected_id="skew", workspace_state=state)
    return project, entry, bundle, item, result


def test_replay_uses_captured_normal_and_legacy_migration_documents_missing_orientation():
    project, entry, bundle, item, result = retained()
    changed = deepcopy(entry)
    changed["normal_axis"] = "a"
    # A current c-report is deliberately not needed: immutable normals win.
    changed["analysis"]["report"]["normal_axis_index"] = 0
    replay = replay_difference(bundle, changed)
    np.testing.assert_array_equal(replay.grid.values, result.grid.values)
    assert replay.profile["normal_unit_vector"] == [0, 0, 1]
    validate_computation(bundle, replay)
    _, _, old, _, _ = retained(legacy=True)
    migrated = migrate_difference(old, changed)
    assert migrated["schema_version"] == 2
    assert migrated["calculation"]["structure_normal_axis"] is None
    assert "orientation was not recorded" in migrated["calculation"]["migration_note"]
    assert "original execution device" in migrated["computation"]["execution_origin"]
    assert {k: v["raw"] for k, v in migrated["sources"].items()} == {k: v["raw"] for k, v in old["sources"].items()}
    validate_computation(migrated, replay_difference(migrated, changed))
    exported = calculation_record(migrated, item, changed)
    assert exported["dataset"]["source_sha256"] == sha256(item["rawText"].encode()).hexdigest()


def test_self_identifying_cube_comments_do_not_change_normalized_scalar_or_atoms():
    _, entry, _, _, result = retained()
    exported = cube_bytes(result.grid, metadata={"dataset_id": "difference", "structure_sha256": entry["sha256"],
                                                 "grid_plane_axis": 2, "normal_vector": [0, 0, 10]})
    reread = parse_cube(exported, kind="difference_density", units="e/angstrom^3")
    np.testing.assert_array_equal(reread.values, result.grid.values)
    np.testing.assert_array_equal(reread.atom_positions_angstrom, result.grid.atom_positions_angstrom)
    assert reread.atom_record_charges == result.grid.atom_record_charges
    assert b'"dataset_id": "difference"' in exported.splitlines()[1]
