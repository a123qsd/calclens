# CalcLens molecular workspace reference

The user supplied `calclens-reference.png` on 2026-11-05 as the approved visual
direction. It is a design concept, not scientific output. The earlier local
0.4.0 implementation is preserved at commit `2178fe5` and in source archives.

## Layout and visual language

Match the reference at 1584 × 992: approximately 254 px navy sidebar, warm white
main background, three summary cards, a large white structure card and a right
review card in a roughly 2:1 ratio, and a full-width records table below. Use a
consistent sans-serif typeface, dark ink, subtle borders, 10 px card radii,
16–24 px gaps, and teal primary actions. Main tokens are navy `#0B1929`, page
`#FAF8F5`, card `#FFFFFF`, teal `#009C90`, ink `#172331` and muted `#637083`.

The sidebar contains the CalcLens aperture mark, overview/comparison/review/method
navigation, current project information, documentation and repository links.
The header contains workspace context, title, a short description, file open,
sample and language controls. Keep all main actions keyboard accessible and
provide visible focus, readable contrast, loading and error states. On narrow
screens, collapse navigation and stack viewer/review cards.

## Scientific content

Reuse Python's original CIF parser, geometry report, project schema and exports.
Replace the mockup's SCF/optimization/frequency cards with minimum periodic
distance, nuclear-span thickness and candidate nuclear gap. Do not claim to
analyze calculation logs, convergence, stability or vibrational frequencies.

The 3D scene uses actual report elements, coordinates, cell and atom indices.
Show shaded spheres and optional sticks. Distance-inferred sticks are explicitly
labelled display-only connections and can be disabled; they never affect the
analysis. Preserve each repeated atom's original index and lattice image shift.
Fit the atomic structure initially, with separate full-cell fit and reset/rotate
controls. Review selections use Python's exact periodic-image evidence.

## Functional parity

Retain bilingual sample/CIF loading, batch input, saved-project opening,
add/replace/remove, per-file axis/cutoff, notes and review stamps, independent
geometry/progress filters, pair selections, before/after comparison and original
JSON/CSV/project downloads. Camera/display changes do not recalculate geometry.
All JavaScript, fonts, icons and viewer resources must run locally without a CDN.

## Verification

Build and typecheck the frontend, run the Python suite and API regressions, then
exercise actual uploads, mutations, exports and 3D interactions in a browser.
Capture the representative overview at 1584 × 992 and a narrow layout. Compare
the screenshot with the approved reference; record a structured visual verdict
and any differences caused by actual supported scientific content. Windows EXE
execution remains a separate Windows-runner check.

Work status is tracked in Beads under `calclens-boy`; this document records the
design contract rather than a task list.
