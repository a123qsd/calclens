# Methods and scientific limits / 계산 방법과 과학적 한계

CalcLens checks a deliberately narrow geometric model: explicitly listed,
fully occupied atomic sites in a P1 cell, periodic in all three directions,
with a user-selected normal axis (a, b, or c) perpendicular to the other two
cell vectors. It performs no relaxation, force,
energy, phonon, charge, or electronic-structure calculation.

이 도구는 P1 셀에 명시된 원자핵 위치를 검사합니다. 물질의 안정성, 결합의 적절성,
계산 설정의 정확성을 판정하지 않으며 구조를 자동으로 고치지 않습니다.

## Input contract

| Input | Accepted values |
| --- | --- |
| Format | CIF 1.x, exactly one data block |
| Sites | 1–400 explicit fractional-coordinate sites |
| File size | At most 2 MiB (2,097,152 bytes) |
| Elements | Standard element symbols; no mixed species or placeholder sites |
| Occupancy | 1 within 0.00000001 for every site; omitted occupancy is interpreted as 1 with an informational note |
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
partial result. In particular, the program does not expand non-P1 symmetry,
choose a dominant species for mixed occupancy, guess a slab normal, or select
one block from a multi-structure file. A symmetry-expanded P1 export must contain
all required atoms. First review occupancy and disorder in a suitable structure
tool; then export fully expanded P1 if that representation is appropriate.
Changing only the space-group label does not make a file valid.

Symmetry-related records and alternative partially occupied sites in a general
CIF are not automatically accidental duplicates. The P1/full-occupancy boundary
prevents CalcLens from silently conflating those cases with repeated explicit
sites. Unsupported input is not repaired by discarding atoms.

## Parsing without losing duplicates

[ASE's CIF parser](https://docs.ase-lib.org/ase/io/formatoptions.html#cif) handles
CIF syntax. CalcLens reads the explicit site loop and constructs the
geometry from those rows. It avoids a symmetry-expansion path that might merge
equivalent positions before duplicate-site checking. Two rows at the same
periodic position therefore remain two sites and can be reported as an overlap.

Only the geometry and supported site fields are analyzed. Chemical oxidation
states, magnetic order, occupancies below one, and structural disorder are outside
the model. Nontrivial disorder groups, site multiplicity other than 1, a
nonstandard space-group setting, magnetic symmetry, modulated, superspace, or
composite structure declarations, and Cartesian-coordinate site fields are
rejected. Declared modulation metadata is conservatively unsupported even when
its value is zero or unknown; an average structure cannot substitute for the
full model without a separate scientific decision. Repeated tags and ASE parser warnings also stop
analysis because their interpretation may be ambiguous. A parsable file is
not necessarily an appropriate simulation input.

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

Use the broader libraries or a suitable structure editor when symmetry expansion,
disorder, a normal that is not a supported cell axis, chemical bonding, or advanced analysis is
required. Check their own method assumptions before using the result for research.

Gaussian/ORCA log parsing, SCF convergence, optimization histories, and frequency
analysis are outside the current scope. A CIF geometry report supplies no
evidence that any of those calculations ran or converged. See [DEVELOPMENT.md](DEVELOPMENT.md) for
the boundary of a possible future log feature.
