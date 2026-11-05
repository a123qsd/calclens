# Validation record

## v0.6.0 local viewer verification — 2026-11-05

The expanded viewer retains the tungsten and model-reuse corrections below.
Local checks passed **39 frontend tests**, TypeScript checking, the production
build, **547 Python tests** and Ruff. After reinstalling the rebuilt package,
all 22 web-API tests passed again. The existing 11 ASE/NumPy deprecation warnings
remain. No new project dependency was added.

Real Chromium/WebGL checks passed three suites: eight existing workspace groups,
nine incremental-viewer groups and nine new feature groups. The new feature
suite recorded zero page or console errors. The workspace suite's two intentional
HTTP 409 conflicts remained the only expected errors in that suite.

- Korean and English overview layouts passed at 390, 820, 1100 and 1584 pixels,
  with long filenames and no horizontal overflow or overlapping sample controls.
  Comparison controls also stayed within their own viewer containers at all
  four widths.
- All three representations and graphics-quality levels retained the atoms and
  camera without replacing the atom model. Top/side presets, projections,
  fullscreen focus, review-panel collapse and repeat changes were exercised.
  Comparison rotation and zoom synchronized while retaining each center and pan;
  unlinking restored independent camera control.
- A 400-site structure displayed 3,600 atoms. Across the 17 measured toolbar,
  report and highlight changes, whole-model rebuilding remained at zero. Label
  priority updated after review selection even when labels were already enabled.
  The 180-label and 8,000-connection truncation notices matched actual limits.
  This single-sample regression run is not a cross-hardware performance claim.
- Four charge kinds retained their own scientific meaning, source and method.
  Missing values, explicit zero and signed values had distinct colors. Wrong CIF
  identity, element mapping, missing metadata and invalid integer charges were
  rejected without replacing valid data. Selection highlights were checked using
  3Dmol's resolved color function, including restoration after selection changes.
- A synthetic 125-point orbital fixture produced both signed surfaces. Hiding
  and showing surfaces, or changing only opacity, reused their meshes. Coordinate,
  unit and negative-density mismatches were rejected. Parser tests also cover
  numeric underflow and grid collapse after float32 conversion; a separate test
  rejects surface complexity above 25,000 intersected cells before allocation.
- Downloaded PNGs were **1600 × 736** and **3200 × 1472** pixels. The white
  image's corner was opaque white; the High-quality/AO transparent image's corner
  had alpha zero. Camera, canvas dimensions, background and labels were restored
  after both successful export and an injected export failure.
- Auxiliary data survived switching back to the same CIF in the session,
  stayed isolated from other structures, and was invalidated by source-byte
  replacement. It is intentionally excluded from saved projects.

Electronic fixtures above test data handling and rendering, not physical accuracy.
CalcLens does not compute electronic structure; the existing fully occupied P1
CIF input contract remains. See [VIEWER_DATA.md](VIEWER_DATA.md) for accepted
formats and bounds. These are local macOS/Chromium results; remote CI and native
Windows outcomes are recorded with the published release rather than inferred
from the presence of workflow steps.

## Viewer update verification (unreleased) — 2026-11-05

Compared with source `7e97deff51eede207f73cf1c61c97fe3c1dd296e`, the local
viewer update adds the Cordero/ASE tungsten covalent radius (1.62 Å) and reuses
atom models and inferred connectivity when only presentation changes.
W–S (2.42 Å) and W–Se (2.53 Å) regressions failed before the radius correction
and passed afterwards, in both atom orders. The overlap exclusion, unknown
element handling and 2.6 Å display-connection cap remain unchanged. These are
display estimates; the scientific geometry engine and CIF input contract are
unchanged.

The browser comparison used the same synthetic 400-carbon-site fixture,
3×3 repetition (3,600 displayed atoms), viewport and headless Chromium
156.0.8078.4/WebGL 2 environment on macOS. Each operation was measured three
times, from dispatch to two animation frames later; the table reports medians.
It includes browser scheduling and is not a cold-load or frame-rate benchmark.

| Operation | Before | After |
| --- | ---: | ---: |
| Start rotation | 158.4 ms | 16.2 ms |
| Show 180 atom labels | 5,308.7 ms | 63.8 ms |
| Show unit cell | 229.7 ms | 68.1 ms |
| Highlight an atom and its repeated copies | 170.9 ms | 32.5 ms |
| Receive an equivalent report object | 169.1 ms | 26.7 ms |

Across 17 toolbar/report/highlight operations repeated three times, whole-model
removal fell from 51 calls to zero. Label display drew the scene twice instead
of 184 times by batching label additions. Style changes still invalidate
3Dmol's rendered molecular geometry; this change does not eliminate all GPU
mesh work. Actual geometry, element, repeat-range or extra contact-atom changes
still update the model. Timings are specific to this local fixture and browser;
Windows hardware performance has not been measured for this patch.

`scripts/smoke_viewer_updates.py` uses the actual React viewer in StrictMode,
checks model identity and atom additions, and verifies camera preservation,
highlight clearing, contact endpoints outside the repeat range and real atom
picking after style updates. Element-only changes refresh atom identities and
connections; gap-only changes refresh boundary geometry, labels and the
corner model while retaining the atom model. It starts and stops a temporary
Vite server when no URL is supplied:

```bash
python scripts/smoke_viewer_updates.py --samples 3 --output build/viewer-updates
```

`--mode baseline` records the same operations without requiring model reuse.
The verification mode fails on the old viewer as expected. CI runs the new
regression harness with one sample; it asserts behavior and redraw counts,
without imposing machine-dependent timing thresholds.

Local validation passed 14 frontend geometry tests, TypeScript checking,
the production build, 547 Python tests and Ruff. The existing 11 ASE/NumPy
deprecation warnings and upstream 3Dmol build advisories remain. The rebuilt
production workspace also passed all eight existing Chromium regression
groups, including camera controls, real repeated-atom clicks, source/input
selection reset, gap inspection, concurrent-tab conflicts and bilingual UI.
The only HTTP/console errors were the two intentional conflict responses.
No release or remote CI run is claimed by this local verification.

## v0.5.0 native Windows release verification — 2026-11-05

Release source: [`84f6444`](https://github.com/a123qsd/calclens/commit/84f6444ee04f3193646ff6c6f1ec45d991738f28).
[Source CI run 41931805193](https://github.com/a123qsd/calclens/actions/runs/41931805193)
passed on Ubuntu and Windows with Python 3.12 and 3.13: **547 tests per
environment**, 11 existing ASE/NumPy deprecation warnings, the frontend build
and 10 frontend tests. The Ubuntu/Python 3.12 job also passed the focused real
Chromium regression harness. The initial Windows attempt exposed two tests
that assumed POSIX signals; the corrected tests exercise both POSIX and Windows
shutdown paths on every platform. The launcher behavior was unchanged.

[Windows run 41931807986](https://github.com/a123qsd/calclens/actions/runs/41931807986)
passed both language jobs. Each built and exercised a directory bundle and a
standalone EXE, then checked an extracted folder ZIP. All four smoke reports
identify version 0.5.0, the source above, the expected language/build mode and
frozen Windows execution. The checks cover:

- A real launch-manager window, automatic port selection, requested browser
  URL capture, graceful manager close, closed server port, removed readiness
  marker and no remaining PyInstaller extraction directories.
- Korean and space-containing paths, with external Python removed from PATH.
- Actual WebGL 2 drawing and offscreen buffers, three CIF uploads, language
  switching, saved atom pairs, comparison, unsupported inputs and schema-2
  project export/import/export. Embedded original CIF bytes and hashes match.
- The legacy Streamlit interface and its graceful console shutdown; both
  extracted folder archives also pass their frozen self-tests.

The four workspace event logs contain no console errors, JavaScript exceptions,
failed requests, HTTP errors or external requests. Legacy browser logs contain
only Canvas2D/GPU performance warnings. Default-browser URL dispatch is tested
with a capture hook; browser interactions use Chromium, so this does not verify
every Windows default-browser association or hardware/OS combination.

One default-launch readiness measurement per Windows CI build, after its
self-tests, was:

| Distribution | Korean | English |
| --- | ---: | ---: |
| Folder | 1.700 s | 1.714 s |
| Standalone EXE | 8.050 s | 8.022 s |

These are single measurements on the hosted Windows runner, not cold-start
benchmarks, averages or complete browser-page load times. They support offering
the folder distribution for repeated use without promising these times on a
user's PC.

The downloaded EXEs match their build-metadata SHA-256 and sizes. Both folder
ZIPs carry the expected source/version/locale metadata and exact browser asset
hashes. The support ZIP's dependency manifest matches the tested commit; its
source archive matches `git archive` of that commit with the Windows
`core.autocrlf=true` conversion, including unchanged binary and `-text` data.
The [release validation record](https://github.com/a123qsd/calclens/releases/download/v0.5.0/VALIDATION-0.5.0.json)
records the four distributions and seven Windows asset hashes.

The local-only record below predates this native verification and remains as
historical evidence for its stated environment.

## v0.5.0 local verification — 2026-11-05

The final Python source passed **545 tests** on macOS arm64 with Python 3.12.
The existing 11 ASE/NumPy deprecation warnings remain. Ruff, dependency
consistency, all 16 generated CIFs, the public graphite source/hash and
independent geometry check, and `git diff --check` passed. The frontend passed
TypeScript checking, its production build and **10 geometry/viewer tests**.

The new local API has 22 tests covering canonical projects, atomic mutations,
bounded requests, Host/Origin/token checks, stale revisions, exports and offline
asset delivery. A measurement request carries the workspace revision, so a
stale tab cannot measure replacement coordinates against an old display.

The real Chromium/WebGL browser smoke passed separately in English and Korean:
three CIF uploads, per-file axis/cutoff/note changes, review completion, pair
measurement and saving, exact project export/import/export, two-view comparison,
report downloads, language round trips and unsupported-input presentation.
Both runs reported zero page errors, console errors, failed HTTP requests or
external requests. Rendering used a nonzero WebGL 2 drawing buffer.

The focused browser regression harness passed eight groups: camera fit/reset,
actual repeated-image atom picking and integer validation, diagnostic and gap
selection, stale measurements, note conflicts, independent report language,
390-pixel layout and browser event health. It also verifies that a cutoff-only
change or replacement with identical coordinates but different source bytes
clears the old atom selection. The two deliberate conflicts returned HTTP 409;
there were no unexpected browser/network errors and no external requests.
Unsaved note drafts survive conflicts and require explicit reapplication.

The [workspace screenshot](assets/calclens-workspace.png) shows the actual
graphene fixture at 1584 × 992. An independent review scored the approved
reference match 91/100 before the final picker/toolbar spacing polish. The
layout retains the navy sidebar, three metric cards, white structure/review
cards and records table. Its values describe CIF geometry, not the mockup's
SCF/optimization/frequency concepts. Display bonds remain optional estimates.

A rebuilt 0.5.0 wheel was installed, its offline browser assets and license
notices were checked, and the installed English JSON/Korean CSV CLI and source
launcher self-test passed. End users do not need Node or a CDN. The frontend
build still reports an upstream 3Dmol `eval` warning and a bundle-size advisory.
CalcLens does not use that autoload callback path; its Content Security Policy
does not enable `unsafe-eval`, and the browser flows above passed under it.

**Native Windows EXE building, manager-window execution, normal shutdown,
temporary extraction cleanup and comparative startup timings were not run in
this macOS session.** The Windows workflow includes those checks for both
languages and both directory/one-file distributions, with browser assets
included. The new remote CI jobs have not been executed or published by this
local verification. Earlier Windows results below apply only to their named
commits.

## v0.4.0 local verification — 2026-11-05

The baseline at `0219f84` passed 444 tests before edits. The updated source
passed **518 tests** on macOS arm64 with Python 3.12. The existing 11 ASE/NumPy
deprecation warnings remain. Ruff, dependency consistency, all 16 generated
CIFs, the public graphite source/hash/independent-geometry check and
`git diff --check` passed.

New regressions cover cached single/example results and errors; review stamps
across byte, condition, analysis-revision and ASE changes; schema-1 migration;
atomic project add/replace/remove; independent human-progress filtering;
chosen atom/image selections and their saved-work round trip; optional
side-by-side views; and inherited launcher URL prefixes. The distance rewrite
was also compared with the old implementation over 90 randomized cases with
identical results.

A seven-repeat local distance-engine benchmark for 400 graphene atoms
(79,800 unordered pairs) measured median times of 0.032215 s for the update
and 0.051209 s for `0219f84`, about 1.59 times faster. This measures the distance
kernel on one machine, not complete CIF parsing, browser rendering or Windows
startup. The public 400-site limit remains unchanged. Reproduce with
`python scripts/benchmark_distances.py --atoms 400 --repeats 7 --compare-ref 0219f84`.

The real local browser opened a two-CIF project, displayed both 3D structures,
saved a chosen pair and downloaded a schema-2 project containing the expected
originals, selection and pair definition. Single-example measurement persistence
and language changes were also covered by the Streamlit test harness.

Windows-only checks have been added for the native manager window, graceful
WM_CLOSE and console shutdown, closed server ports, Korean/space paths,
isolated PyInstaller extraction cleanup, folder-ZIP extraction and startup
timings. **The updated Windows EXEs have not been built or run in this local
macOS verification.** These checks require the Windows workflow. Browser URL
capture proves the requested URL, not Windows default-browser integration.

The older records below describe their named versions.

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

## v0.2.0

Version 0.2.0 adds bounded contact sampling that prioritizes overlaps and
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

The installed 0.2.0 package passed **265 tests** after a normal rebuild and
reinstall on macOS arm64 with Python 3.12.16. The run reported 11 ASE/NumPy
deprecation warnings. Ruff, all 16 generated-fixture comparisons, the public
case check, and `git diff --check` passed. A real-browser comparison was also
exercised with three uploaded files.

The [overview image](assets/calclens-overview.png) and
[short demo](assets/calclens-demo.webm) accompany the current interface.
The [public COD graphite case](CASE_STUDY.md) provides source attribution,
conversion details, and a bulk example whose interlayer gaps are not slab vacuum.

0.2.0에서는 접촉 표의 생략 여부와 관계없이 정확한 개수와 대표 근거를 보존하고,
경고 기준 밖의 최소 원자쌍도 확인합니다. 원본 해시·버전 정보와 파일별 조건을 담는
최대 20개 CIF 비교를 추가했습니다. macOS arm64·Python 3.12.16에서 패키지를 다시
설치한 뒤 265개 테스트가 통과했고, ASE·NumPy 사용 경로에서 사용 중단 예정 경고 11개가
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
UTF-8 mode for consistent bilingual text handling. The first expanded run passed
on both Ubuntu versions and exposed Git's
automatic CRLF conversion of the hashed public source on Windows. Explicit
checkout rules and byte-preserving regeneration now protect source and derived
file hashes. Six additional regressions cover this boundary; the local suite
passed all 265 tests after the fix.

All four jobs then passed for commit
[`5977de71c45c319e011fd8e211b37749e8b51737`](https://github.com/a123qsd/calclens/commit/5977de71c45c319e011fd8e211b37749e8b51737)
in [Actions run 41827746986](https://github.com/a123qsd/calclens/actions/runs/41827746986).
This verifies dependency/package installation, CLI smoke checks, tests, lint,
and fixture checks on Ubuntu and Windows with both Python versions.

커밋 `5977de71c45c319e011fd8e211b37749e8b51737`의
[Actions 실행 41827746986](https://github.com/a123qsd/calclens/actions/runs/41827746986)에서
Ubuntu·Windows와 Python 3.12·3.13 조합 4개가 모두 통과했습니다.
의존성·패키지 설치와 명령행 점검, 테스트, 린트, 예제 검증을 포함합니다.

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
Standalone guide links refer to the packaged source commit. CI verified
dependency installation and CLI execution on Windows and Ubuntu. Interactive
browser verification was performed on macOS; it does not establish that the
graphical app was exercised on Windows. The CI matrix records results
separately for every revision.

## Scientific scope

This verifies software behavior and geometric measurements, not a material,
quantum-chemistry calculation, stability, or vacuum sufficiency. Gaussian/ORCA
log parsing, SCF status, optimization status, and frequency interpretation are
outside this version's scope. See [METHODS.md](METHODS.md) for supported inputs,
measurement definitions, thresholds, and known limitations.
