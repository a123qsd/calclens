# Design

## Source of truth
- Status: Active. Last refreshed: 2026-11-06.
- Surfaces: local Korean/English structure workspace, comparison, review and method notes.
- Evidence: user feedback dated 2026-11-06, existing React/CSS, browser regressions and docs/design/API.md.
- This contract supersedes the sidebar/dashboard concept in calclens-reference.png.
  docs/design/REFERENCE.md describes the current layout and verification criteria.

## Brand
- A quiet scientific workbench with an identifiable current file and generous structure view.
- Trust comes from actual coordinates, explicit units, provenance and honest missing-data states.
- Avoid decorative gradients, large branding, repeated circular icons and summary-card grids.

## Product goals
- Make the selected structure the first thing the user sees and the largest working surface.
- Keep file actions together, inspection results beside the structure and display tools at the viewer.
- Preserve every analysis, measurement, draft, project and comparison workflow.
- Success: visible file identity, reachable open/save actions, no overlap, unchanged saved-project behavior.
- Non-goals: a new calculation engine, dependencies, project schema or invented scientific data.

## Personas and jobs
- Students and researchers inspect prepared CIFs, measure periodic contacts and compare structures.
- They switch files, adjust inspection conditions, record notes and reopen saved work.
- The application runs locally, including fonts, scripts, icons and viewer assets.

## Information architecture
- A compact horizontal bar provides overview, comparison, review and method navigation.
- The file header names the selected CIF and groups open, save and project actions.
- A horizontal file list allows direct selection; sample loading is a quiet secondary control.
- A large viewer sits beside a narrower inspection panel. Measurements use compact rows
  inside that panel rather than separate cards above the viewer.
- Editing and measurement follow the viewer. Detailed records retain their filters/export.
- Advanced display/export controls remain at the viewer; auxiliary inputs and P1 preparation
  remain separate labelled sections. Schema-3 projects include validated auxiliary source data.

## Design principles
- Allocate space according to the task: structure first, selected file second, supporting tools next.
- Emphasize selected items and primary actions. Reserve amber/red callouts for actual issues.
- Nuclear span and candidate nuclear gap do not measure material stability.
- Missing charge is unknown, never zero. Element identity, partial charge and oxidation state differ.
- Reuse viewer models/camera state. Opening panels, resizing and changing language do not reset them.
- Keep units, source indices and periodic-image evidence where they affect interpretation.

## Visual language
- Color: neutral page #F4F6F7, white panels, ink #202D35, muted #617079,
  teal #18786C for selections/actions. Use a flat pale neutral canvas.
- Typography: local system sans-serif, compact headings, tabular numerals for measurements.
- Spacing/layout rhythm: 4 px base, 8–16 px control gaps, 20–24 px outer spacing.
- Shape/radius/elevation: 4–6 px corners, thin borders, no decorative shadows or gradients.
- Motion: rotation is opt-in; honor reduced-motion preferences.
- Imagery/iconography: actual molecular scenes; small existing icons supplement text.

## Components
- Reuse MolecularViewer, native inputs/details, status text and existing icons.
- The application bar, selected-file header and file strip replace the sidebar and hero heading.
- The inspection panel combines numeric rows, review actions and evidence links.
- App owns workspace/draft/source state; the viewer owns rendering/camera state.
- Tokens belong in styles.css; viewer layout belongs in viewer.css. No new design-system layer.

## Accessibility
- Target WCAG 2.2 AA controls: visible focus, meaningful labels and readable contrast.
- Active navigation/file selections expose their state. Color has a text counterpart.
- All actions are keyboard reachable. A skip link reaches the workspace.
- Announce import errors/save status. Hiding the inspector leaves the viewer mounted.
- Native fullscreen restores focus; expanded view is available when fullscreen is unavailable.

## Responsive behavior
- Verify 390, 820, 1100 and 1584 px widths, both languages, long filenames and enlarged text.
- Navigation wraps; file tabs scroll within their region. Avoid horizontal page overflow.
- Stack the inspector and comparison views on narrow windows.
- Viewer controls use container-aware wrapping and retain readable labels at touch sizes.

## Interaction states
- Loading: preserve context and show parsing, saving or surface-building progress.
- Empty: retain file identity and explain unsupported input without a decorative empty scene.
- Error: show the rejection reason and preserve the last valid state/data.
- Success: show the current result, review state or download without a blocking modal.
- Disabled: distinguish unavailable actions. Unapplied drafts remain visible and saved as drafts.
- Offline: the running application uses no external assets or data requests.

## Content voice
- Concise Korean/English labels, stable scientific terminology and explicit units.
- Explain methods quietly; use prominent warnings for current input/workflow problems.
- Distinguish original sites, repeated atoms and contact endpoints. Distances use Å; charge uses e.
- Inferred connections do not imply calculated bonds; orbital colors mean wavefunction sign.

## Implementation constraints
- React 19, TypeScript, 3Dmol 2.5.5 and existing CSS; no new dependencies.
- Retain Python API/calculations, project schema, cache/label batching and scientific defaults.
- Preserve atom model 0, fit-cell model 1, source identity, picking and saved camera semantics.
- Export restores camera, size, background and overlays, including after an error.
- Cube surfaces use their supplied grid. Camera sync does not imply crystal registration.
- Run frontend build/typecheck/tests, Python tests/lint and real-browser project/viewer regressions.
- Capture both languages and narrow layouts. Verify executables on Windows before publishing.

## Open questions
- None blocking. This release changes layout/presentation; molecular rendering defaults stay stable.
