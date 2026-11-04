# Methods and scientific limits / 계산 방법과 과학적 한계

Slab Preflight checks a deliberately narrow geometric model: explicitly listed,
fully occupied atomic sites in a P1 cell, periodic in all three directions,
with c perpendicular to the ab plane. It performs no relaxation, force,
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
| Cell angles | α and β within 0.00001° of 90°; 0° < γ < 180° |
| Conditioning | Cell condition number at most 10,000 |
| Fractional coordinates | Finite, absolute value at most 1,000,000 |

Coordinates outside `[0, 1)` are wrapped periodically. Distances are in ångströms
(Å); CIF cell angles are degrees. The file must use the standard CIF length
convention. The program cannot detect a file whose numerical lengths have been
mislabeled, for example nanometre values written in ångström fields.

Unsupported input stops analysis with a reason instead of yielding a reassuring
partial result. In particular, the program does not expand non-P1 symmetry,
choose a dominant species for mixed occupancy, guess a slab normal, or select
one block from a multi-structure file. A symmetry-expanded P1 export must contain
all required atoms. Changing only the space-group label does not make a file valid.

## Parsing without losing duplicates

[ASE's CIF parser](https://docs.ase-lib.org/ase/io/formatoptions.html#cif) handles
CIF syntax. Slab Preflight reads the explicit site loop and constructs the
geometry from those rows. It avoids a symmetry-expansion path that might merge
equivalent positions before duplicate-site checking. Two rows at the same
periodic position therefore remain two sites and can be reported as an overlap.

Only the geometry and supported site fields are analyzed. Chemical oxidation
states, magnetic order, occupancies below one, and structural disorder are outside
the model. Nontrivial disorder groups, site multiplicity other than 1, a
nonstandard space-group setting, magnetic symmetry, modulated or superspace
structure declarations, and Cartesian-coordinate
site fields are rejected. Repeated tags and ASE parser warnings also stop
analysis because their interpretation may be ambiguous. A parsable file is
not necessarily an appropriate simulation input.

## Periodic distances

For sites `i` and `j`, with Cartesian positions `r_i`, `r_j` and cell row vectors
`a`, `b`, `c`, the distance is

```text
d(i, j) = min over n ∈ Z³ of |r_j − r_i + n₁a + n₂b + n₃c|.
```

ASE's [minimum-image geometry](https://docs.ase-lib.org/ase/geometry.html#ase.geometry.find_mic)
is used so that a skewed ab cell is handled as a lattice. Rounding each
fractional-coordinate difference independently is not sufficient for a general
skewed cell. All three directions are periodic, including across the vacuum. The lattice is Minkowski-reduced before applying
the minimum-image operation; the shortest self-image is a minimum-length vector
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
neighbor or bond list. At most 200 contact records are displayed in the report;
the total count and truncation status are retained. Tied nearest images need not
all be listed. Records are retained in site order, not sorted by severity.
Report indices `i` and `j` are zero-based. The integer `shift` is expressed in
the original cell basis, so the contact vector is
`r_j + shift @ cell − r_i`.

## Thickness and the largest cyclic gap

Let `z_i` be each fractional c coordinate wrapped to `[0, 1)`, sorted in
ascending order, and let `H = |c|`. Define consecutive fractional gaps, including
the interval from the last site back to the first site in the next cell:

```text
g_i = z_(i+1) − z_i                 for i < N
g_N = z_1 + 1 − z_N
G   = H × max(g_i)                 largest nuclei gap
T   = H − G                       nuclei-span thickness
```

Removing the largest cyclic gap gives the smallest interval along c that
contains all nuclear positions. The calculation does not depend on where the
cell boundary cuts the slab. A rigid translation followed by wrapping therefore
preserves `G` and `T` within floating-point tolerance.

Because c is required to be perpendicular to ab, `H` is the repeat height along
the slab normal. A tilted c vector is rejected rather than using its length as
an incorrect perpendicular height.

`T` includes the full occupied span, including internal gaps in a multilayer
structure. It is not a per-layer thickness. A single atomic plane has `T = 0`
and `G = H`. Neither value includes atomic radii or electron-density tails.

원자핵 기준 두께는 가장 큰 빈 간격을 제외하고 남은 원자핵 위치의 범위입니다.
단일 원자 평면의 값이 0 Å여도 물질의 물리적 두께가 0이라는 뜻은 아닙니다.
표시된 빈 간격에는 전자 밀도나 원자 반지름을 반영하지 않습니다.

## Ambiguous geometry

The app reports geometric values even when their slab interpretation needs review:

- `AMBIGUOUS_SLAB`: the largest gap is below 3 Å, or occupies at most half of c.
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
conditions, and corrections. Slab Preflight cannot perform or replace that test.

**3 Å는 권장 진공 두께가 아닙니다.** 실제 계산에서 진공 간격을 바꾸면서 관심 물성의
수렴을 확인해야 합니다. 경고가 없더라도 안정성이나 계산 정확성이 보장되지 않습니다.

## Verification scope

The repository's tests compare simple examples with analytical geometry and an
independent finite enumeration of periodic images. They exercise boundary
wrapping, translations, skewed ab cells, duplicate rows, self-images, units, and
unsupported input. Deliberately malformed examples verify failure messages.

These checks establish behavior for the tested cases. They are not a
cross-validation against experimental measurements, a DFT benchmark, a proof for
all possible CIF syntax, or an independent materials-science certification.

## Why ASE, and when to use another tool

ASE provides the parsing and periodic-geometry operations needed here in an
established atomistic Python library. [pymatgen](https://pymatgen.org/) provides
broader materials objects, symmetry, and analysis workflows. Slab Preflight's
narrow P1 contract keeps its duplicate handling and slab convention inspectable;
it deliberately exposes fewer capabilities than either library.

Use the broader libraries or a suitable structure editor when symmetry expansion,
disorder, arbitrary slab orientation, chemical bonding, or advanced analysis is
required. Check their own method assumptions before using the result for research.
