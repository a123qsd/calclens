# CalcLens structure workspace reference

The user's 2026-11-06 feedback replaces the earlier dashboard direction.
[DESIGN.md](../../DESIGN.md) is the current contract. The old calclens-reference.png
is retained as a historical concept, not a target for new implementation.

## Layout

At 1584 × 992, use compact horizontal navigation, a selected-file heading with
file/project actions and a scrollable file strip. The main view has a large
structure canvas and an approximately 300 px inspection panel. Keep measurements
in concise rows in that panel. Retire the 254 px sidebar, large generic title,
three summary cards and permanently amber methods banner.

Keep fit/reset/rotation/repeat tools at the viewer. Group advanced display and
image export settings beneath it. Editing, measurements, auxiliary inputs,
preparation and the records table remain available in the same workspace.
Narrow windows stack the inspector and comparison views. Long filenames wrap
in the heading and remain available in file-tab titles.

## Visual language

Use flat neutral surfaces, thin borders, 4–6 px corners, a local system typeface
and tabular numerals. Teal marks selected items and primary actions. Sample
loading is secondary to opening a file. A quiet methods note explains limits;
amber and red are reserved for actual warnings and errors.

## Scientific content and functional parity

Reuse Python's parser, geometry report, project schema and exports. Keep minimum
periodic distance, nuclear-span thickness and candidate nuclear gap with their
units and meaning. Do not imply energy, convergence or stability analysis.

The 3D scene uses actual elements, coordinates, cell and atom indices. Display-only
inferred connections never change analysis. Repeated atoms retain their original
index and lattice shift. Preserve rendering defaults, camera state, exact
periodic-image evidence and atom picking.

Retain bilingual sample/CIF loading, batch input, saved-project opening,
add/replace/remove, per-file settings/drafts, notes/review stamps, independent
filters, pair selections, comparison and all exports. Validated charge/Cube
source data remains included in schema-3 projects. Runtime assets are local.

## Verification

Run frontend tests/typecheck/build, Python tests/lint and existing real-browser
regressions. Check file switching, save/reopen, drafts, atom selection, camera
retention, inspector collapse, comparison and image export. Capture overview
screenshots at 1584 × 992 and at 390, 820 and 1100 px widths, including English,
Korean, long filenames and expanded controls. Record actual layout checks.
Verify Windows packages on the Windows runner before publishing release assets.
