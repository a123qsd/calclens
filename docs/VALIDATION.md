# Validation record

Date: 2026-11-04. Local environment: macOS arm64, Python 3.12.16.

CalcLens v0.1 passed **149 tests** with the dependency versions in
`requirements.lock`. This covers the geometry core, unsupported inputs,
command-line report delivery, CSV criteria and units, and Streamlit interactions.

```bash
python -m pip install --require-hashes -r requirements.lock
python -m pip install --no-deps --no-build-isolation .
python -m pytest -q
python -m ruff check .
python scripts/generate_examples.py --check
```

Observed results: 149 tests passed; Ruff passed; all **16 generated CIF examples**
matched their committed text. Package dependencies were also checked with
`python -m pip check`, with no broken requirements.

Tests cover independently enumerated periodic images, analytic distances/gaps,
periodic duplicates and self-images, translations, skew in-plane cells,
a/b/c normal selection, rejected modulation/superspace and contradictory
symmetry declarations, no-overwrite CLI behavior, report conventions, and
bilingual example flows. The display is checked against the true periodic image
coordinates and the cyclic gap intervals; screen highlighting does not change
measurements. Threshold equality and language/status changes have regressions.

## Browser verification

The real local Streamlit interface was exercised in the in-app browser:

- Selected periodic duplicate sites and confirmed the highlighted sites and
  contact information appeared in the 3D view and review panel.
- Uploaded `mos2_wrapped.cif`: minimum distance 2.409 Å, nuclei-span thickness
  3.120 Å, and nuclei gap 16.880 Å were displayed.
- Selected the normal gap and verified the highlighted cell region and profile.
- Switched Korean to English and back while retaining the uploaded file,
  geometric result, and visibly selected source/review controls.
- Downloaded the periodic-duplicate CSV and inspected its 38 rows: measurements,
  criteria, element pairs, image shifts, units, assumptions, and limitations.
- Corrected sidebar input contrast and checked the desktop layout against the
  supplied design reference. No browser console errors were reported.

The browser checks complement Streamlit's test harness. No claim is made that
all browsers, mobile devices, or arbitrary CIF dialects have been validated.

## Continuous integration

The repository includes a read-only-permission GitHub Actions workflow running
installation, pytest, Ruff, and fixture checks on Ubuntu with Python 3.12.
The [Actions page](https://github.com/a123qsd/calclens/actions/workflows/tests.yml)
records the outcome for each published commit; consult it for the current result.

## Scientific scope

This verifies software behavior and geometric measurements, not a material,
quantum-chemistry calculation, stability, or vacuum sufficiency. Gaussian/ORCA
log parsing, SCF status, optimization status, and frequency interpretation are
outside this version's scope. See [METHODS.md](METHODS.md) for supported inputs,
measurement definitions, thresholds, and known limitations.
