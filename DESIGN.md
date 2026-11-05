# Design

## Source of truth
- Status: Active. Last refreshed: 2026-11-05.
- Surfaces: local bilingual overview, atomic viewer, comparison, review and method notes.
- Evidence: `docs/design/REFERENCE.md`, existing React/CSS, two user-supplied feedback documents,
  and the verified viewer-reuse change at `4c5ef36`.

## Brand
- Calm, precise scientific workspace: navy navigation, warm white cards, teal actions.
- Trust comes from actual coordinates, visible units, provenance and explicit missing data.
- Avoid decorative electron orbits, simulated charges and claims of material stability.

## Product goals
- Make periodic structures legible, controls responsive, and export useful figures.
- Add optional externally supplied charge and volume displays without changing geometry analysis.
- Success: no unnecessary atom-model recreation, no overlapping controls, clear legends,
  verifiable high-resolution images, and rejected mismatched auxiliary data.
- Non-goals: quantum calculations, automatic disorder interpretation, metallic PBR materials,
  or an unmeasured automatic quality policy.

## Personas and jobs
- Students and researchers inspect prepared CIFs, measure periodic contacts and compare structures.
- They need readable overview/detail views, bilingual labels and reproducible data interpretation.

## Information architecture
- Preserve existing navigation and project workflows.
- Keep fit, reset, rotation and repeat accessible; group advanced display/export settings.
- Separate representation, color meaning, graphics quality and electronic isovalue.
- Auxiliary files are local display data for the current source; clearly disclose session-only
  lifetime and exclusion from saved CIF projects. Switching back to a source retains its data
  within the session; replacing source bytes cannot reuse it silently.

## Design principles
- Preserve coordinates and atom identity across every display mode.
- Missing charge is unknown, never zero; nuclear charge, ionic charge, oxidation state and
  partial charge have distinct labels. Orbital colors mean wavefunction sign.
- Reuse scientific data and viewer models; high quality must not change measurements.
- Bound external data size and validate identity, coordinates, units and field kind before display.

## Visual language
- Extend existing CSS tokens, sans-serif typography, 10 px corners and 16–24 px spacing.
- Neutral transparent canvas over the existing subtle CSS gradient; restrained carbon color.
- Element legend and a distinct selected-atom highlight remain visible in every color mode.
- Motion is opt-in; honor reduced-motion preferences.

## Components
- Reuse `MolecularViewer`, native inputs/details, cards and existing icons.
- Add grouped display controls, element/charge legends, import details and image export options.
- Viewer owns its presentation and camera; App owns per-source auxiliary data and comparison links.
- Shared validated data contracts are declared in `viewerData.ts`; do not add dependencies.

## Accessibility
- Aim for WCAG 2.2 AA controls: visible focus, labels, keyboard access and readable contrast.
- Color is supplemented by text and units. Import failures and export status are announced.
- Native fullscreen must restore focus; use a usable expanded view if fullscreen is unavailable.

## Responsive behavior
- Test 390, 820, 1100 and 1584 px widths, narrow comparison cards, long filenames and enlarged text.
- Use viewer-container sizing for its controls rather than global viewport assumptions.
- Topbar controls wrap without negative margins; review panel can collapse.

## Interaction states
- Loading: bounded file parsing/surface building and image-export state.
- Empty: unavailable electronic modes explain which data is required.
- Error: preserve the last valid auxiliary dataset; show the import rejection reason.
- Success: show filename/source/method and the active scientific meaning.
- Offline: all code and data remain local; no remote fetch is needed by the app.

## Content voice
- Concise Korean/English. Use “원자 구조 / Atomic structure”.
- Display counts distinguish original sites, repeated atoms and added contact endpoints.
- Disclose label/connection caps. Distances use Å; charge uses e; oxidation state is dimensionless.

## Implementation constraints
- React 19, TypeScript, 3Dmol 2.5.5, existing CSS; no new project dependencies.
- Preserve model 0 for atoms and model 1 for fit-cell helpers and existing picking semantics.
- Keep the prior cache/label batching fixes and regression tests.
- Quality uses supported renderer controls only. PNG export re-renders at the requested resolution
  and restores the interactive camera, size, background and overlays even on failure.
- Cube surfaces belong to their supplied coordinate grid, not automatically repeated images.
- Compare synchronization means camera orientation/zoom, not automatic crystal registration.

## Open questions
- None blocking this implementation. Persistent auxiliary-data project storage and automatic
  performance-based quality selection are separate future extensions.
