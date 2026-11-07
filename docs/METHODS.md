# Methods and scientific limits / 계산 방법과 과학적 한계

CalcLens directly analyzes a deliberately narrow geometric model: fully expanded,
explicitly listed sites in an ordered, fully occupied P1 cell, periodic in all
three directions,
with a user-selected normal axis (a, b, or c) perpendicular to the other two
cell vectors. It performs no relaxation, force,
energy, phonon, charge, or electronic-structure calculation.

직접 분석은 대칭 전개를 마친 P1 셀의 완전 점유·질서 구조에 명시된 원자핵 위치를
검사합니다. 물질의 안정성, 결합의 적절성, 계산 설정의 정확성을 판정하지 않으며
구조를 자동으로 고치지 않습니다.

The optional viewer can display externally supplied charge assignments and Cube
density/orbital grids. Those displays do not change these calculations or relax
the CIF input contract. Source/coordinate checks establish a display mapping,
not the correctness of the external calculation. Unknown charges are not zero,
oxidation states are not partial charges, and orbital colors denote wavefunction
sign rather than positive/negative electron charges. See [Imported viewer
data](VIEWER_DATA.md) for the separate display-data contract. Imported sources,
drafts and viewer settings can be retained by manually saving a project ZIP;
see [Workspace save](WORKSPACE_SAVE.md). Desktop sessions also keep local automatic recovery snapshots. The optional browser workspace requires a manual project save.

가져온 전하·전자 표면은 표시용 보조 자료이며 기하 분석이나 입력 제한을 바꾸지 않습니다.
표면의 기준값은 그래픽 품질과 별개이고, 원자핵 기준 두께·간격은 전자 표면을 반영하지 않습니다.
가져온 원본·초안·뷰어 설정은 작업 ZIP에 수동으로 저장할 수 있습니다.
데스크톱은 저장 전 변경 사항의 로컬 복구본을 만듭니다. 이전 브라우저 화면에서는 작업 ZIP을 직접 저장해야 합니다.

## Direct-analysis input contract

| Input | Accepted values |
| --- | --- |
| Format | CIF 1.x, exactly one data block |
| Sites | 1–400 fully expanded, explicit fractional-coordinate sites in an ordered structure |
| File size | At most 2 MiB (2,097,152 bytes) |
| Elements | Standard element symbols; no mixed species or placeholder sites |
| Occupancy | 1 within 0.00000001 for every site; an absent occupancy field defaults to 1 with an informational note; explicit `?` or `.` is rejected |
| Symmetry | Explicit P1 declaration; symmetry operations, if supplied, must be identity only |
| Cell lengths | Finite, between 0.001 and 10,000 Å |
| Cell angles | Angles between the selected normal vector and each other vector within 0.00001° of 90°; the remaining angle strictly between 0° and 180° |
| Conditioning | Cell condition number at most 10,000 |
| Fractional coordinates | Finite, absolute value at most 1,000,000 |

The normal axis defaults to c. Choosing a requires β and γ to be 90°; choosing b
requires α and γ to be 90°; choosing c requires α and β to be 90°, within the
tolerance above. This is a choice among cell axes, not arbitrary-vector or
automatic layer-normal detection.

The app can compare up to 20 files. Every file must independently satisfy this
contract, including its 2 MiB and 400-site limits; a batch does not become a
larger combined structure. Axis and cutoff are set per file, initially c and
1.0 Å. An unsupported entry retains its filename, hash, settings, and reason,
with blank measurements, while the other entries are still analyzed.

앱에서 최대 20개 파일을 비교해도 파일당 2 MiB·400개 원자 제한은 같습니다.
파일마다 축과 짧은 거리 기준을 정하며, 지원하지 않는 파일은 사유를 남기고 나머지를 검사합니다.

Coordinates outside `[0, 1)` are wrapped periodically. Distances are in ångströms
(Å); CIF cell angles are degrees. The file must use the standard CIF length
convention. The program cannot detect a file whose numerical lengths have been
mislabeled, for example nanometre values written in ångström fields.

Unsupported input stops analysis with a reason instead of yielding a reassuring
partial result. Direct analysis does not expand non-P1 symmetry. The separate
[P1 preparation step](WORKSPACE_SAVE.md#p1-preparation) can expand supported,
ordered, fully occupied structures in a validated standard setting. Applying a
preview retains the original bytes, hashes and preparation history in the project;
the resulting explicit P1 structure must satisfy the input contract above.
Neither path chooses a dominant species for mixed occupancy, guesses a slab
normal, or selects one block from a multi-structure file. Changing only the
space-group label does not make a file valid.

직접 분석은 비 P1 대칭을 전개하지 않습니다. 별도의 **P1 구조 준비** 단계에서
지원되는 완전 점유·질서 구조를 검증한 뒤 대칭 전개할 수 있습니다. 적용 후에도
원본 바이트·해시·준비 이력을 프로젝트에 보관하며, 전개한 구조는 위 입력 조건을
충족해야 합니다. 공간군 이름만 P1으로 바꾸는 것은 유효한 변환이 아닙니다.

Symmetry-related records and alternative partially occupied sites in a general
CIF are not automatically accidental duplicates. The P1/full-occupancy boundary
prevents CalcLens from silently conflating those cases with repeated explicit
sites. Unsupported input is not repaired by discarding atoms.

## Parsing without losing duplicates

[ASE's CIF parser](https://docs.ase-lib.org/ase/io/formatoptions.html#cif) handles
CIF syntax. CalcLens reads the explicit site loop and constructs the
geometry from those rows. Direct analysis avoids a symmetry-expansion path that
might merge equivalent positions before duplicate-site checking. Two rows at the same
periodic position therefore remain two sites and can be reported as an overlap.

Only the geometry and supported site fields are analyzed. Chemical oxidation
states, magnetic order, occupancies below one, and structural disorder are outside
the model. Direct analysis rejects nontrivial disorder groups, site multiplicity
other than 1, a nonstandard space-group setting, magnetic symmetry, modulated,
superspace, or composite structure declarations, and Cartesian-coordinate site
fields. Declared modulation metadata is conservatively unsupported even when
its value is zero or unknown; an average structure cannot substitute for the
full model without a separate scientific decision. Repeated tags and ASE parser warnings also stop
analysis because their interpretation may be ambiguous. A parsable file is
not necessarily an appropriate simulation input.

### CIF field aliases and site values

Both direct analysis and P1 preparation accept an explicit list of known
underscore and dotted aliases, such as `_atom_site_occupancy` and
`_atom_site.occupancy`. The four multiplicity spellings
`_atom_site_symmetry_multiplicity`, `_atom_site.symmetry_multiplicity`,
`_atom_site_site_symmetry_multiplicity` and `_atom_site.site_symmetry_multiplicity`
refer to one field. Repeating a semantic field through any of its aliases is
rejected even when the values agree. Other dotted names are not automatically
converted to underscore names.

Explicit occupancy, disorder and multiplicity values must be site-loop columns
with one value per atom. Both paths require occupancy 1 within `1e-8`. Only an
absent occupancy field receives the default 1 and an informational note; explicit
`?` and `.` values never receive that default. Direct P1 analysis requires site
multiplicity 1. P1 preparation instead checks each declared multiplicity against
the number of distinct sites generated for that source atom by symmetry.
Occupancy uncertainty and refinement metadata remain annotations and do not
replace occupancy values.

직접 분석과 P1 구조 준비는 명시적으로 지원하는 밑줄·점 표기를 같은 항목으로
읽습니다. 예를 들어 `_atom_site_occupancy`와 `_atom_site.occupancy`는 같습니다.
위의 다중도 표기 네 가지도 하나의 항목이며, 값이 같아도 같은 항목을 여러 표기로
중복 선언하면 거부합니다. 모든 점 표기를 밑줄로 일괄 변환하지는 않습니다.

점유율·무질서·다중도를 명시하면 원자마다 값이 하나씩 있는 원자 목록의 열이어야
합니다. 두 경로 모두 점유율 1을 `1e-8` 오차 범위에서 허용합니다. 점유율 항목이
없을 때만 안내와 함께 1을 적용하며, `?`나 `.`을 명시한 값에는 적용하지 않습니다.
직접 P1 분석의 다중도는 1이어야 합니다. P1 구조 준비에서는 각 원본 원자를 대칭
전개해 얻은 서로 다른 위치 수와 선언된 다중도가 일치하는지 확인합니다.
점유율 불확도와 정밀화 메타데이터는 주석이며 점유율 값을 대신하지 않습니다.

## Periodic distances

For sites `i` and `j`, with Cartesian positions `r_i`, `r_j` and cell row vectors
`a`, `b`, `c`, the distance is

```text
d(i, j) = min over n ∈ Z³ of |r_j − r_i + n₁a + n₂b + n₃c|.
```

ASE's [minimum-image geometry](https://docs.ase-lib.org/ase/geometry.html#ase.geometry.find_mic)
is used so that skewed cell vectors in the selected layer plane are handled
as a lattice. Rounding each
fractional-coordinate difference independently is not sufficient for a general
skewed cell. All three directions are periodic, including across the vacuum.
The lattice is Minkowski-reduced before applying the minimum-image operation; the shortest self-image is a minimum-length vector
of the reduced basis.

The zero translation is excluded for a site's contact with itself. Its closest
nonzero periodic image is checked separately using a reduced lattice. This
catches a cell that is too short even when it contains only one site.

| Rule | Meaning |
| --- | --- |
| Distance ≤ 0.00001 Å | `OVERLAPPING_SITES`: distinct rows occupy effectively the same periodic point; error-level finding |
| Distance below the selected cutoff | `SHORT_DISTANCE`: review the contact; default cutoff 1.0 Å, allowed range 0.1–3.0 Å |
| Short nonzero self-image distance | `SELF_IMAGE_CONTACT`: review the cell and its periodic repetition |

The cutoff is a user-controlled visual screening rule. It is not a universal
bond length, a covalent-radius test, or a criterion for chemical validity. A
legitimate short bond can trigger it; an incorrect longer bond can escape it.

The contact list records one nearest image per unordered pair of distinct sites
and one shortest self-image per site when relevant. It is not an exhaustive
neighbor or bond list. At most 200 contact records are retained, prioritizing
overlaps, then shorter distances, with stable site/image ordering for ties.
The bounded list also reserves representative minimum-distance, distinct-pair,
and self-image evidence when those distances are below the cutoff. Exact total
counts and truncation status are retained even when details are omitted.
Tied nearest images need not all be listed.

Distance findings carry `contact_count` and `representative_contact` independently
of that bounded list. `OVERLAPPING_SITES` counts distinct overlapping pairs;
`SHORT_DISTANCE` counts distinct pairs below the cutoff, including overlaps;
`SELF_IMAGE_CONTACT` counts one shortest self-image per site. These counts are
not coordination numbers. `metrics.minimum_pair` always preserves one pair/image
realizing the global minimum, even when no distance is below the cutoff. The
app's **View nearest pair** button opens that evidence directly.

접촉 상세는 최대 200개이며, 겹침과 더 짧은 거리를 우선합니다. 표에서 생략되어도
진단별 전체 개수와 대표 원자쌍·이미지는 보존합니다. 최소 거리의 원자쌍은 경고 기준과
관계없이 남기므로, 경고가 없는 구조에서도 **원자쌍 보기**로 확인할 수 있습니다.

Report indices `i` and `j` are zero-based. The integer `shift` is expressed in
the original cell basis, so the contact vector is
`r_j + shift @ cell − r_i`.

## Thickness and the largest cyclic gap

Let `q_i` be each fractional coordinate along the selected normal axis, wrapped
to `[0, 1)` and sorted in ascending order. Let `v_n` be that cell vector and
`v_u`, `v_v` the other two vectors. The perpendicular repeat height is

```text
H = |v_n · (v_u × v_v)| / |v_u × v_v|.
```

Define consecutive fractional gaps, including the interval from the last site
back to the first site in the next cell:

```text
g_i = q_(i+1) − q_i                 for i < N
g_N = q_1 + 1 − q_N
G   = H × max(g_i)                 largest nuclei gap
T   = H − G                       nuclei-span thickness
```

Removing the largest cyclic gap gives the smallest interval along the selected
normal that contains all nuclear positions. The calculation does not depend on
where the cell boundary cuts the slab. A rigid translation followed by wrapping
therefore preserves `G` and `T` within floating-point tolerance.

The selected vector must be perpendicular to the other two within the stated
angle tolerance. A tilted choice is rejected; CalcLens does not infer an
arbitrary normal or silently substitute a different axis. The same distance
screening still considers all three periodic directions.

`T` includes the full occupied span, including internal gaps in a multilayer
structure. It is not a per-layer thickness. A single atomic plane has `T = 0`
and `G = H`. Neither value includes atomic radii or electron-density tails.

원자핵 기준 두께는 가장 큰 빈 간격을 제외하고 남은 원자핵 위치의 범위입니다.
단일 원자 평면의 값이 0 Å여도 물질의 물리적 두께가 0이라는 뜻은 아닙니다.
표시된 빈 간격에는 전자 밀도나 원자 반지름을 반영하지 않습니다.

## Ambiguous geometry

The app labels ambiguous slab interpretation as review needed. Numerical
geometry is still reported, with these warning criteria:

- `AMBIGUOUS_SLAB`: the largest gap is below 3 Å, or occupies at most half of the selected repeat height.
- `MULTIPLE_LARGE_GAPS`: the second-largest gap is at least 3 Å and at least half
  the largest gap. Several separated occupied regions may be present.

These are presentation heuristics, not a dimensionality classifier. They can
flag a valid structure and can miss an unsuitable one. Atomic planes within one
MoS₂ sandwich are not automatically treated as separate physical layers. No
warning proves that a slab contains exactly one layer, and a large gap does not
prove that the structure is a 2D material.

**The 3 Å rule is not a recommended vacuum width.** Vacuum sufficiency depends on
the intended calculation and observable. Increase the repeat separation and
check the relevant quantities for convergence with the chosen method, boundary
conditions, and corrections. CalcLens cannot perform or replace that test.

**3 Å는 권장 진공 두께가 아닙니다.** 실제 계산에서 진공 간격을 바꾸면서 관심 물성의
수렴을 확인해야 합니다. 경고가 없더라도 안정성이나 계산 정확성이 보장되지 않습니다.

## Report and export conventions

JSON schema `1.1` records `normal_axis`, `normal_axis_index`, and `in_plane_axes`.
`metrics.normal_height_angstrom` is the repeat height for the selected axis.
The legacy `metrics.c_height_angstrom` retains its c-axis meaning: the projection
of c onto the normal of ab, regardless of the selected axis. Use `normal_height_angstrom`
when interpreting the reported gap and thickness.

`gap_start_fraction`, `gap_end_fraction`, `gap_fraction`, the second-largest gap,
and the nuclei gap/span all follow the selected axis. A gap crossing the cell
boundary may have an end fraction smaller than its start fraction. The gap is
cyclic; a single atomic plane can have equal start/end fractions and a full-cell
gap. Use `gap_fraction` to distinguish that case from a zero-length interval.

`criteria` preserves the distance cutoff, overlap tolerance, perpendicular-angle
tolerance, and gap-review thresholds. Findings retain a severity and stable code;
site-related findings carry `atom_indices`, and gap-related findings identify
`normal_gap`. These fields support visual highlighting without changing the
scientific calculation.

`gap_review_required` and `applicability.review_required` describe **gap
interpretation only**. The top-level `review_required` is true if any warning or
error is present, including overlaps or short contacts. A false value is still
not physical validation. `geometric_candidate` is not a validation or convergence status.

The CSV export contains measurements, criteria, findings, short-contact details,
assumptions, and limitations as labeled rows. CSV site numbers start at 1;
JSON `i`, `j`, and `atom_indices` start at 0. The contact count and truncation
status remain explicit. A `minimum_pair` metric row preserves site/element IDs,
distance, and image shift even when `short_contacts` is empty. Issue rows carry
exact `contact_count` values in `value`, using `pairs` or `sites` units; their
representatives appear as `issue_contact` rows with the same issue code.
JSON preserves the full structured geometry report;
CSV is a readable summary, not a lossless replacement for the CIF or JSON.

Reports delivered by the app and CLI include `provenance.original_filename`,
`provenance.sha256`, `provenance.calclens_version`, and `provenance.ase_version`.
SHA-256 covers the exact original bytes before text decoding or newline
normalization. It identifies the input file, not just its geometry: different
line endings can produce the same measurements and different hashes. CSV
preserves these fields as `provenance` rows. The package version identifies the
software release; schema `1.1` identifies the report format.

The comparison CSV contains one row per input with its identity, selected axis
and cutoff, formula, site count, minimum distance, thickness, gap, finding
counts, and any input-error reason. Successful rows also carry package versions.
Failed measurements and finding counts stay blank. `no_flags` means no warning
or error findings; it does not establish scientific validity. Its warning/error
counts refer to findings, while per-issue contact counts remain in the detailed
reports. The summary follows the interface language; individual reports follow
their own language selector.

## Verification scope

The repository's tests compare simple examples with analytical geometry and an
independent finite enumeration of periodic images. They exercise boundary
wrapping, translations, selectable normal axes, skewed layer-plane cells,
duplicate rows, self-images, units, and
unsupported input. Deliberately malformed examples verify failure messages.

These checks establish behavior for the tested cases. They are not a
cross-validation against experimental measurements, a DFT benchmark, a proof for
all possible CIF syntax, or an independent materials-science certification.

## Why ASE, and when to use another tool

ASE provides the parsing and periodic-geometry operations needed here in an
established atomistic Python library. [pymatgen](https://pymatgen.org/) provides
broader materials objects, symmetry, and analysis workflows. CalcLens's
narrow P1 contract keeps its duplicate handling and slab convention inspectable;
it deliberately exposes fewer capabilities than either library.

Use the broader libraries or a suitable structure editor when the validated P1
preparation does not support the required symmetry expansion, or when disorder,
a normal that is not a supported cell axis, chemical bonding, or advanced analysis
is required. Check their own method assumptions before using the result for research.

The desktop's separate Gaussian reader reports supported SCF energies, optimization steps, frequencies and termination records with their original line numbers. ORCA output is outside this parser's scope. A CIF geometry report alone cannot establish that an electronic calculation ran or converged. See the [research cases](RESEARCH_CASES.md) for the Gaussian and periodic convergence contracts and [compute methods](COMPUTE.md) for external-field post-processing.
