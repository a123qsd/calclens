# Local validation record

Date: 2026-11-04. Environment: macOS arm64, Python 3.12.16.

The current CIF geometry implementation passed **91 tests** with the dependency
versions in `requirements.lock`. This covers the geometry core, unsupported input,
command-line report delivery, and Streamlit example/plot interactions.

```bash
python -m pip install --require-hashes -r requirements.lock
python -m pip install --no-deps --no-build-isolation .
python -m pytest -q
python -m ruff check .
python scripts/generate_examples.py --check
```

Observed results: 91 tests passed; Ruff passed; all 14 generated CIF examples
matched their committed text. Tests include independent periodic-image
enumeration, analytic distances/gaps, periodic duplicates, self-images,
coordinate translation, skew cells, rejected modulation/superspace metadata,
contradictory symmetry, CLI no-overwrite behavior, and bilingual example flows.

The Streamlit tests exercise its test harness, not a real browser rendering.
Final visual review and remote CI have not yet been performed. The interface
is being adapted to the CalcLens design reference. Calculation-log parsing,
SCF status, optimization status, and frequency interpretation are not features
of this CIF implementation.

This record verifies software behavior and geometric measurements. It is not
a validation of a material, a quantum-chemistry calculation, or vacuum sufficiency.
