# Imported viewer data

CalcLens can display externally supplied atomic charge assignments and multiple
electron-density or orbital Cube grids, with one selected volume per viewer. These files do not change the CIF,
geometric measurements, review results or scientific input limits. CalcLens does
not calculate electronic structure from nuclear positions.

전하 JSON·Cube 원본과 선택한 자료·표시 설정은 `.calclens.zip`에 함께 저장합니다.
[작업 저장 안내](WORKSPACE_SAVE.md)를 참고하세요. 원본 CIF가 교체되면 이전 자료를
새 구조에 자동으로 연결하지 않습니다.

## Charge and oxidation-state JSON

Download a template for the selected structure, then fill in the method, source
and values from an actual calculation or assignment. The template binds to the
SHA-256 of the original CIF bytes and uses **one-based** original atom indices.
It does not contain guessed zero charges: all initial values are `null`.

```json
{
  "schema_version": 1,
  "structure_sha256": "the 64-character SHA-256 from the downloaded template",
  "kind": "partial_charge",
  "method": "Hirshfeld; specify calculation and settings",
  "source": "Name or identifier of the source calculation",
  "atoms": [
    {"index": 1, "element": "C", "value": null},
    {"index": 2, "element": "H", "value": 0.12}
  ]
}
```

The values above illustrate the file format; they are not a physical result.
The actual file must list every atom from its template exactly once. Rows may
be reordered because `index` establishes the mapping, but duplicate/missing
indices and mismatched elements are rejected. Values must be finite numbers or
`null`; a missing field or a numeric string is not accepted. Files are limited
to 1 MiB. The original CIF hash must match even when two CIF files describe
identical coordinates but have different bytes.

| `kind` | Meaning | Display unit |
| --- | --- | --- |
| `partial_charge` | Atomic partial charge from the named partitioning method | e |
| `formal_charge` | Formal charge from an explicit electron-bookkeeping assignment | e |
| `ionic_charge` | Integer net charge of an explicitly identified atom/ion | e |
| `oxidation_state` | Oxidation-state assignment; supplied fractional averages are retained | Dimensionless |

Method and source are required for every kind. Partial charge depends on the
chosen partitioning method; it is not automatically an oxidation state.
Formal charge and ionic net charge are stored separately and are not relabeled
as each other. Both require integer values. `null` means **unknown**, while
`0` is an explicitly supplied zero. Nuclear
charge, shown separately as `+Ze`, is determined by the element and does not
determine the atom's net ionic charge.

산화수·부분전하·이온 전하는 서로 다른 항목입니다. 자료가 없는 원자를 중성으로
표시하지 않으며, Cube의 원자 행에 들어 있는 핵전하도 부분전하로 가져오지 않습니다.

## Cube density and orbital grids

Select the actual field kind, scalar units and source when loading a `.cube`
file. Filename or comments alone cannot establish whether a field is density,
an orbital, electrostatic potential or some other quantity.

| Field kind | Accepted scalar units | Interpretation |
| --- | --- | --- |
| Electron density | `e/bohr^3`, `e/angstrom^3` | Nonnegative total electron density |
| Orbital | `bohr^-3/2`, `angstrom^-3/2`, `arbitrary` | A single real orbital amplitude; colors distinguish signs |

Orbital colors describe the sign of the wavefunction, **not positive and
negative electron charges**. A supplied density with negative values is
rejected; spin density, difference density and potentials are not accepted as
total electron density. Scalar values retain the selected units: changing the
spatial coordinate representation does not rescale or normalize the values.
The initial isovalue is 15% of the largest absolute grid value, a display
starting point rather than a recommended physical threshold.

### Supported spatial convention

Gaussian/VMD Cube documentation describes atomic-unit coordinates. Other Cube
implementations use negative voxel counts to signal ångströms. To make this
choice explicit and match the installed 3Dmol 2.5.5 parser, CalcLens accepts:

- **All three voxel counts positive:** origin, vectors and atom positions in
  Bohr, converted with 1 Bohr = 0.529177210903 Å (CODATA 2018).
- **All three voxel counts negative:** origin, vectors and atom positions in
  Å, the 3Dmol convention. Mixed signs are rejected.

This is an explicit compatibility convention, not a claim that every Cube
producer writes that convention. Verify your producer's output. CalcLens does
not infer spatial units from the scalar-unit selector or try both units until
one happens to match.

The atom count, atomic numbers, ordering and Cartesian coordinates must match
the selected CIF. The allowed positional difference is **0.01 Å per atom in
Euclidean distance**. No automatic rotation, translation, wrapping, atom
permutation or crystal registration is performed. A correctly rejected file
may need an explicit, reviewed alignment/export step in its source software.

### Bounds and format checks

- At most 32 MiB and 1,000,000 grid points; at least two points per axis.
- Finite, nondegenerate three-dimensional grid vectors. Skew grids are allowed.
- Origin, positions and supported grid extents within ±1,000,000 Å.
- Exactly one scalar per voxel, in Cube order (z changes fastest).
- `NVAL`, when present, must equal 1. A negative atom count may provide a single
  dataset identifier; multiple orbitals/datasets must be exported separately.
- Decimal numbers and `E`/`D` exponent notation are accepted. Extra, missing,
  malformed and non-finite scalars are rejected, as are values that overflow or
  underflow the viewer's float32 representation.

Before rendering, CalcLens rewrites the validated spatial coordinates in Å
using the negative-count convention. It retains scalar order and values,
including their sign, and removes an optional single-orbital identifier header
from this internal display copy. This avoids 3Dmol's shorter Bohr conversion
factor and its permissive handling of malformed scalar tokens. The imported
volume occupies its supplied grid; it is **not automatically replicated** for
each periodic atom image.

Changing the isovalue requires **Apply**. Hiding a surface or changing only its
opacity reuses its mesh. Before mesh allocation, the viewer limits the total
number of grid cells intersected by the requested positive/negative surfaces to
25,000. A noisier or more complex field can therefore be accepted as a file but
rejected at a particular isovalue. CalcLens does not silently downsample the
scientific grid to fit this limit.

## Element categories

Atomic numbers use standard element-symbol order through Og (118). “Metal
elements” highlights alkali/alkaline-earth elements, the transition elements
through Cn, lanthanides, actinides, and Al/Ga/In/Sn/Tl/Pb/Bi. Metalloids,
borderline Po and predicted post-Cn categories are not included in this display
list. This category never asserts that the complete material is metallic;
for example, Na in NaCl does not make NaCl a metallic material.

## References and verification

- [3Dmol Cube parser](https://github.com/3dmol/3Dmol.js/blob/2.5.5/src/parsers/CUBE.ts)
  and [VolumeData parser](https://github.com/3dmol/3Dmol.js/blob/2.5.5/src/VolumeData.ts).
- [VMD Cube format documentation](https://www.ks.uiuc.edu/Research/vmd/plugins/molfile/cubeplugin.html)
  for atom/grid records and single/multiple-orbital layout.
- [IUPAC partial atomic charges](https://goldbook.iupac.org/terms/view/11482)
  for the distinction between partitioning methods.

`frontend/src/viewerData.test.ts` checks missing-vs-zero values, source identity,
atom mapping, spatial conversion, skew grids, scalar units, dataset counts,
malformed inputs and size limits. Test fixtures are synthetic format examples,
not computed density or orbital results and not evidence of chemical accuracy.

## Multiple datasets and portable projects

Each import adds a named dataset with a distinct ID. Up to 16 datasets and
64 MiB of original text may be attached to one CIF. Saved files are reparsed
and matched to the recalculated structure before the workspace is replaced.
Compare supports individual, shared and manual negative/positive charge ranges
when both sides display the same quantity. Method and source remain visible.
The [H2O example](ELECTRONIC_CASE.md) contains actual calculated electronic files;
the format unit tests described above remain synthetic.
