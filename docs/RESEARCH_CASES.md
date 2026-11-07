# Research cases and bounded interpretation

CalcLens now separates three kinds of evidence: original program output,
an interpretation of that output, and a comparison of calculations made under
matching conditions. Every bundled case is local and can be checked without
a network connection, Gaussian, or PySCF. None is a human researcher trial.

## Gaussian text logs

```python
from slab_preflight.research import parse_log

original = path.read_bytes()
report = parse_log(original, source_name=path.name, source_url=None)
```

`parse_log(bytes)` returns a JSON-compatible report. It never rewrites the
input. Save the original bytes alongside the interpretation; the report is
not a substitute for the original output. `provenance` records the exact byte
SHA-256, size, source name and optional source URL. Extracted energies,
frequencies, routes, state declarations and convergence rows retain 1-based
source line references. `sources` links to the relevant program/parser guidance.

For Gaussian inputs the supported interpretation covers molecular text logs
for molecular SCF HF/KS single points, geometry optimizations and harmonic
frequencies. It records:

- Gaussian generation and printed revision, when present.
- Echoed route, requested method/basis, printed standard basis, charge,
  multiplicity and atom count. Missing data stay null; checkpoint inheritance
  and a custom/general basis are not reconstructed.
- Each printed `SCF Done` energy in hartree, its method label, cycles and source
  line, plus an explicitly labelled eV conversion. Adopted conversion:
  1 hartree = 27.211386245988 eV (CODATA 2018). This differs from cclib's usual
  choice of eV for `scfenergies`; values must be compared with units attached.
- SCF convergence/failure markers, optimization completion/stoppage markers
  and the reported force/displacement convergence table.
- Reported frequencies in cm⁻¹, their source lines and negative-mode count.

Whole-file and per-step execution statuses are `normal`, `failure`,
`truncated` or `unknown`. Missing termination is `truncated`, which also covers
a still-running output. An unrecognized file is `unknown`. Explicit Link1
boundaries and subsequent echoed routes are kept as separate job steps.
A normal first step cannot hide a failed or incomplete later step. Callers
must choose a step before interpreting multiple jobs as one result.

A printed SCF energy does not establish a completed optimization. A normal
termination does not establish a minimum, full vibrational-mode coverage,
electronic accuracy or stability. `minimum_certified` is always false. A
negative-frequency count is a count of reported values, not a diagnosis of
the stationary point. Correlated, excited-state, ONIOM, scan, dynamics and
other unsupported route types are flagged; their SCF values may be retained
as explicitly labelled intermediate observations, never as their final
correlated/excited-state energies. Thermochemistry, archive records, orbital
populations, excited states, periodic Gaussian input mapping and custom
checkpoint data are outside this parser's scope.

Original reference logs are in
[`gaussian_reference`](../examples/research_cases/gaussian_reference).
They are pinned, unchanged files from
[cclib/cclib](https://github.com/cclib/cclib/tree/0c6e08e0a0d04b308201666793030ef3b77b2973/data/Gaussian/basicGaussian16),
commit `0c6e08e0a0d04b308201666793030ef3b77b2973`.
The upstream root BSD-3-Clause license is retained in `LICENSE.cclib`;
`sources.json` lists the original raw URLs, exact sizes and hashes. No
local Gaussian execution is claimed. These reference outputs exercise an
actual single point (`dvb_dispersion_bp86_d3zero.out`), optimization
(`dvb_gopt.out`, five SCF energies) and harmonic frequencies (`dvb_ir.out`,
54 reported modes). Failure/truncation/Link1 edge tests use labelled synthetic
snippets, not invented program runs or research results.

The data fields were checked against the
[cclib attribute notes](https://cclib.github.io/data_notes.html) and upstream
original outputs. Gaussian's primary
[SCF](https://gaussian.com/scf/), [optimization](https://gaussian.com/opt/)
and [frequency](https://gaussian.com/freq/) references remain linked in reports;
their web server returned HTTP 502 during this implementation, so no claim
is made that their current page contents were retrieved.

## VASP output

The native research panel also reads VASP OUTCAR files. The bundled Ni reference includes 18 sites and a final TOTEN of −68.22868532 eV. Energy without entropy and the sigma-to-zero energy are retained under their own names. The parser tracks the execution footer, electronic convergence marker and ionic convergence separately. Original output text and the selected job's source lines are available when comparing structures. [Reference data and checksum](../examples/research_cases/vasp_reference/sources.json) · [OUTCAR format](https://vasp.at/wiki/OUTCAR)

## Vacuum-series contract

```python
from pathlib import Path
from slab_preflight.research import compare_convergence_series

report = compare_convergence_series(
    Path("examples/research_cases/hbn_vacuum/series.json")
)
```

The selected manifest and every referenced artifact must stay inside one
bundle directory. Absolute paths, `..`, Windows drive/backslash syntax,
escaping symlinks, duplicate JSON keys, non-finite numbers, unknown units and
hash mismatches are rejected. Limits are 64 cases, 4 MiB per JSON, 2 MiB per
CIF, 32 MiB per original log and 128 MiB of referenced data per ingestion.
No file is fetched or executed during ingestion.

The manifest's minimal shape is:

```json
{
  "schema_version": 1,
  "kind": "vacuum_convergence_series",
  "name": "Explicitly described series",
  "source_cif": {
    "path": "source.cif",
    "sha256": "64 lowercase hex characters",
    "origin": "Source and preparation description",
    "license": "Reuse conditions"
  },
  "fixed_conditions": {
    "program": "PySCF", "program_version": "2.12.0", "method": "RKS",
    "basis": "gth-szv", "charge": 0, "multiplicity": 1,
    "kpoint_grid": [1, 1, 1], "periodic_dimensions": 3,
    "energy_quantity": "electronic_total"
  },
  "variable": {"name": "vacuum_angstrom", "normal_axis": "c"},
  "tolerance": {"value": 1.0, "unit": "meV/atom", "minimum_successful_cases": 3},
  "cases": [{
    "id": "sample", "vacuum_angstrom": 12,
    "cif": {"path": "sample.cif", "sha256": "..."},
    "output": {"path": "sample.log", "sha256": "...", "kind": "pyscf_log"},
    "result": {"path": "sample.json", "sha256": "..."}
  }]
}
```

The bundled manifest includes further fixed conditions: functional,
pseudopotential, grids, Coulomb boundary, solver tolerances and thread count.
Each result is `schema_version: 1`, `kind: calclens_calculation_result` and
contains its own fixed conditions, `status`, `scf_converged`, exact
`input_cif_sha256`/`output_sha256`, and an `energy` object with `value`, `unit`
and `quantity: electronic_total`. Energy ingestion accepts explicitly labelled
hartree/Eh/a.u., eV, meV, kJ/mol or kcal/mol, then normalizes before computing
meV/atom. Per-atom input units are rejected to avoid double normalization.

Version one requires the controlled periodic-input snapshot written by
`prepare_convergence_case.py` into the original PySCF log. Conditions, cell,
elements and coordinates must match this snapshot, and the result energy
must match the original final converged SCF line. A molecular output with a
plausible energy line cannot become a periodic slab result by changing its
metadata. Generic PySCF output formats and periodic Gaussian input mapping
are not inferred. Gaussian logs can be interpreted separately; they are
excluded from a periodic series until such input mapping is supported.

Source/derived structures must be explicit full-occupancy P1 CIFs with an
explicit perpendicular normal axis. The ordered elements, both in-plane
vectors, normal direction and relative Cartesian coordinates must match
within 10⁻⁶ Å. Before comparing coordinates, atoms are unwrapped across the
largest cyclic normal gap. This preserves a wrapped MoS₂ layer with relative
normal offsets `[0, +1.56, -1.56]` Å when the normal repeat changes; keeping its
fractional z coordinates fixed would incorrectly stretch the layer.
`build_vacuum_cif` creates a derived CIF without modifying the source, merging
sites or relaxing geometry. Ambiguous equal normal gaps require explicit
preparation. The measured vacuum is a nuclei gap, not a density-free boundary.

Valid comparisons return `accepted`, `not_converged`, `insufficient_data` or
`incomparable`, plus every case, its eligibility/exclusion reasons, normalized
energies and source/output provenance. Failed, incomplete and unconfirmed runs
remain visible but never set the energy reference. Changed conditions or
geometry make the series `incomparable`. The reference is the largest
successful vacuum; the suggested sampled value is the start of a consecutive
tail, including at least two settings, whose energy differences all meet the
chosen tolerance. The complete series must contain the configured minimum
number of successful distinct settings. This sampled criterion does not prove
asymptotic convergence. Malformed/unsafe bundles raise `ResearchError`.

## Actual periodic h-BN example

The source is the repository's original idealized h-BN geometry, with
`a = b = 2.5 Å`, γ = 120°, two atoms and a planar layer. Only the normal cell
repeat and a common centering translation change. It is neither experimental
nor relaxed. The actual jobs use PySCF 2.12.0, 3D periodic supercells, Gamma-only
RKS/LDA,VWN, gth-szv/gth-pade, eight valence electrons, eight basis functions,
fixed FFT/xc meshes `[15, 15, 151]`, one configured thread, SCF energy tolerance
10⁻⁹ hartree and gradient tolerance 10⁻⁶. There is no truncated Coulomb kernel,
geometry optimization or smearing. The reproducible input is explicitly
recorded at the top of each original output.

| Nuclei gap (Å) | Total electronic energy (hartree/cell) | Difference from 16 Å (meV/atom) |
| --- | ---: | ---: |
| 8 | −12.558956805705 | 0.539451 |
| 12 | −12.559014710620 | 0.248386 |
| 16 | −12.558996454595 | 0 |

All three SCFs converged. The selected 1 meV/atom criterion is met across these
samples; a stricter 0.1 meV/atom criterion is not. The sequence is nonmonotonic.
The small basis, single k-point and fixed point counts are intentionally
inexpensive and have not been independently converged. In particular, fixing
the z point count while changing cell height changes the real-space grid
spacing, so the measured differences include discretization effects. This is
a workflow demonstration, not a recommended production setting or a claim
that 8 Å is sufficient for h-BN in general. No force, band-gap, density-tail,
basis, k-point or grid convergence is established.

Two local executions produced the displayed energies to the quoted digits.
Committed results retain the last actual execution's UTC start times and wall
times, not a predicted timing. `check_case` reconstructs the AO electron count
and the exported energy-component sum with NumPy. It shares PySCF integrals
and Coulomb/xc components and therefore does not independently validate the
electronic engine. Primary implementation references:
[periodic cell setup](https://pyscf.org/user/pbcgto.html),
[FFT density fitting](https://pyscf.org/user/pbc/df.html),
[periodic DFT settings](https://pyscf.org/user/pbc/dft-settings.html).

```sh
# Optional: separate environment with PySCF 2.12.0, NumPy and ASE installed.
python scripts/prepare_convergence_case.py --run

# Normal CalcLens environment; reads the committed results without PySCF.
python scripts/prepare_convergence_case.py --check
python scripts/verify_research_cases.py
PYTHONPATH=src python -m pytest tests/test_research_logs.py tests/test_research_convergence.py
```

## Controlled CIF coverage

[`cif_cases/cases.json`](../examples/research_cases/cif_cases/cases.json)
records origin, reuse conditions, exact hash, explicit expected geometry and
expected rejection for ten fixtures. These are controlled developer cases,
not literature predictions or human trial data.

| Class | Case | Explicit geometry or expected behavior |
| --- | --- | --- |
| Planar | h-BN | 2 atoms; thickness 0 Å; nuclei gap 20 Å |
| Buckled | constructed silicene | 2 Si; a = 3.86 Å; normal offsets ±0.23 Å |
| Multilayer | constructed AA graphene bilayer | 4 C; layer separation 3.35 Å |
| Adsorbate | constructed H above h-BN | H 1.2 Å above B; no bonding/stability claim |
| Defect | constructed 2×2 graphene vacancy | 7 C after removing one of eight ordered sites; no relaxation |
| Wrapped boundary | MoS₂ | thickness 3.12 Å split across fractional z = 0 |
| Periodic overlap | graphene boundary duplicate | retain all 3 records; detect zero-distance overlap |
| Rejection | partial occupancy | reject occupancy below one |
| Rejection | unexpanded non-P1 symmetry | require explicit preparation |
| Rejection | modulated metadata | reject unsupported modulation rather than use an average structure |

`verify_research_cases.py` uses its own restricted literal-table reader for
these fixtures, constructs their perpendicular c-normal cells directly and
enumerates every site-pair/image vector in `[-2, 2]³`. It does not call the
CalcLens MIC, reduction or distance routines. Analytic geometry, brute-force
distances/gaps and CalcLens results agree within 10⁻⁸ Å; the recorded maximum
metric discrepancy is below 3×10⁻¹⁵ Å. The limited table reader and finite
image shell are appropriate only to these small controlled cells; they are
not offered as a general CIF/nearest-image algorithm. Duplicate rows remain
visible instead of being silently merged by a high-level structure reader.

The separate [public graphite case](CASE_STUDY.md) retains the real deposited
[COD 9011577](https://www.crystallography.net/cod/9011577.html) source,
revision 291877, and its source attribution and CC0 reuse terms. Constructed
monolayers and controlled fixtures remain clearly distinguished from that
experimental bulk input. `verification.json` records the executed automated
checks and their stated limits.

## Optional browser figure annotations

The optional browser workspace keeps raw PNG export as the default. Selecting
“Include sources and displayed-data legend” appends a white footer with the
current input formula, normal, original filename and exact SHA-256. Charge
quantity, color range, units, method/source and unknown-value swatches appear
only while that charge dataset colors the atoms. Volume units, source and
signed isovalues come from the enabled rendered surface, including only the
signs actually created; unapplied isovalue edits and hidden datasets are
omitted. The filename records the complete image's dimensions after the
footer is added. The original rendered region retains its size/background.

An executed Chromium download check compared a 1600×661 transparent raw
image with the cropped upper region of its 1600×1386 annotated export:
all RGBA channels matched exactly. The 725-pixel white footer contained the
full source identity, displayed charge information and both actual orbital
isovalues. A second export with electronic displays disabled omitted their
metadata. These are automated synthetic display fixtures, not chemical
results or participant observations. The check also verified the original
1600-pixel white/3200-pixel transparent export paths and camera restoration
after successful and failed export attempts.
