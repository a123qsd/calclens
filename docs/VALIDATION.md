# Validation record

Date: 2026-11-04. Local environment: macOS arm64, Python 3.12.16.

Before the 0.2.0 changes, the v0.1.1 baseline passed **210 tests** with the
dependency versions in `requirements.lock`. This covers the geometry core, unsupported inputs,
command-line report delivery, CSV criteria and units, and Streamlit interactions.

```bash
python -m pip install --require-hashes -r requirements.lock
python -m pip install --no-deps --no-build-isolation .
python -m pytest -q
python -m ruff check .
python scripts/generate_examples.py --check
```

Baseline results: 210 tests passed; Ruff passed; all **16 generated CIF examples**
matched their committed text. Package dependencies were also checked with
`python -m pip check`, with no broken requirements.

Tests cover independently enumerated periodic images, analytic distances/gaps,
periodic duplicates and self-images, translations, skew in-plane cells,
a/b/c normal selection, rejected modulation/superspace and contradictory
symmetry declarations, no-overwrite CLI behavior, report conventions, and
bilingual example flows. The display is checked against the true periodic image
coordinates and the cyclic gap intervals; screen highlighting does not change
measurements. Threshold equality and language/status changes have regressions.

## 0.2.0 source update

The current source adds bounded contact sampling that prioritizes overlaps and
shorter distances while preserving minimum-distance and self-image evidence.
Distance findings retain exact counts and a representative contact independently
of the sample. Regression cases include a late-index duplicate after the first
200 contacts, crowded overlaps with self-images, and a minimum pair above the
warning cutoff.

Report tests cover original-byte SHA-256, CRLF input, Unicode filenames,
CalcLens/ASE versions, English/Korean JSON and CSV, inert spreadsheet text, and
minimum-pair/issue evidence outside the contact table. Batch cases cover mixed
supported and unsupported inputs, per-file axes and cutoffs, source order and
identity, duplicate filenames, and the 20-file limit. Every file still uses the
single-file 2 MiB and 400-site limits.

The installed 0.2.0 package passed **259 tests** after a normal rebuild and
reinstall on macOS arm64 with Python 3.12.16. The run reported three ASE/NumPy
deprecation warnings. Ruff, all 16 generated-fixture comparisons, the public
case check, and `git diff --check` passed. A real-browser comparison was also
exercised with three uploaded files.

The [overview image](assets/calclens-overview.png) and
[short demo](assets/calclens-demo.webm) accompany the current interface.
The [public COD graphite case](CASE_STUDY.md) provides source attribution,
conversion details, and a bulk example whose interlayer gaps are not slab vacuum.

0.2.0 소스에서는 접촉 표의 생략 여부와 관계없이 정확한 개수와 대표 근거를 보존하고,
경고 기준 밖의 최소 원자쌍도 확인합니다. 원본 해시·버전 정보와 파일별 조건을 담는
최대 20개 CIF 비교를 추가했습니다. macOS arm64·Python 3.12.16에서 패키지를 다시
설치한 뒤 259개 테스트가 통과했고, ASE·NumPy 사용 경로에서 사용 중단 예정 경고 3개가
보고됐습니다. 실제 브라우저에서도 업로드한 파일 3개로 비교를 확인했습니다.
아래의 기존 브라우저 기록은 v0.1.1 기준입니다.

## Baseline browser verification (v0.1.1)

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
hash-locked dependency installation, package installation, installed-CLI smoke
checks (English JSON and Korean CSV), pytest, Ruff, and fixture checks on
**Ubuntu and Windows, each with Python 3.12 and 3.13**. The workflow enables
UTF-8 mode for consistent bilingual text handling. This matrix is configured;
its expanded remote jobs have not been verified during this local update.
The [Actions page](https://github.com/a123qsd/calclens/actions/workflows/tests.yml)
records the outcome for each published commit; consult it for the current result.

## Bilingual release checks

The v0.1.1 update adds English/Korean source packages, guides, and result exports.
Locale tests verify that measurements, criteria, atom indices, image shifts, and
diagnostic codes are unchanged. English-to-Korean-to-English report conversion
restores the English descriptions, and Korean output retains the original text.
Crowded examples verify that translated pair counts remain correct when the
contact detail list is truncated. Both CLI formats were also exercised through
the installed package using the wrapped MoS2 example.

Browser checks downloaded `graphene_calclens_ko.csv` and
`graphene_calclens_en.json`. The Korean CSV had a UTF-8 BOM and Korean headings;
all CSV measurements matched the English JSON. Interface and report language
were selected independently. Translated dropdowns were checked after switching
languages, including the example name and “Same as interface” option. Mandatory
selectors have no clear button, and defensive empty-value handling is tested.

Distribution tests verify language defaults and overrides, a loopback-only
launcher, reproducible ZIP bytes, identical calculation code in both packages,
and rejection of dirty trees, unsafe paths, symlinks, and sensitive file names.
Standalone guide links refer to the packaged source commit. These checks do not
claim that dependency installation and app launch were exercised on Windows.
The observed local runtime validation used macOS; the expanded Ubuntu/Windows
CI matrix requires its own run results.

## Scientific scope

This verifies software behavior and geometric measurements, not a material,
quantum-chemistry calculation, stability, or vacuum sufficiency. Gaussian/ORCA
log parsing, SCF status, optimization status, and frequency interpretation are
outside this version's scope. See [METHODS.md](METHODS.md) for supported inputs,
measurement definitions, thresholds, and known limitations.
