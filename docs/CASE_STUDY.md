# Public CIF case: graphite and a derived basal sheet

This case starts with a published graphite structure and follows its conversion
into CalcLens-compatible input. The expanded bulk cell also demonstrates why a
large geometric gap does not establish that a structure contains vacuum.

## Source and reuse

The source is [Crystallography Open Database (COD) entry 9011577](https://www.crystallography.net/cod/9011577.html),
revision **291877**, for natural graphite crystals. Its original publication is
P. Trucano and R. Chen, “Structure of graphite by neutron diffraction,”
*Nature* **258** (1975), 136–137,
[doi:10.1038/258136a0](https://doi.org/10.1038/258136a0).
COD identifies the upstream American Mineralogist Crystal Structure Database
record as **0014675**. Bibliographic details and structural values here come
from the COD record; this case does not claim a new refinement of the paper.

COD's [entry page](https://www.crystallography.net/cod/9011577.html) dedicates its
data to the public domain under [CC0 1.0](https://creativecommons.org/publicdomain/zero/1.0/)
and requests acknowledgement of the original authors. The downloaded CIF and
both derived CIFs retain that attribution. These structural data retain their
CC0 status separately from the CalcLens software license.

The unmodified download is
[`examples/public_case/source/9011577-rev291877.cif`](../examples/public_case/source/9011577-rev291877.cif).
It was retrieved on **2026-11-04** from the
[official CIF endpoint](https://www.crystallography.net/cod/9011577.cif);
its header states revision 291877. COD also provides a
[revision-specific URL](https://www.crystallography.net/cod/9011577.cif@291877).
The bundled bytes, rather than a future response from the current-record URL,
are the reproducibility input. Their SHA-256 is:

```text
35d1661c3131acc9b1c33dad65358d094b93105d6aae711465ac4352ae809748
```

## Preparation and direction checks

The source declares space group **P 63/m m c, No. 194**, with
**a = b = 2.464 Å, c = 6.711 Å**, and **α = β = 90°, γ = 120°**.
It contains two asymmetric carbon rows and 24 symmetry operations.
CalcLens requires an explicitly expanded P1 structure, so the original CIF is
expected to be rejected by CalcLens until it has been prepared.

[`scripts/prepare_public_case.py`](../scripts/prepare_public_case.py) performs
these steps using the existing ASE dependency:

1. Verify the source SHA-256 and restrict the preparation to this record.
2. Check occupancy and disorder before expanding symmetry. The source omits
   `_atom_site_occupancy`; the script records and applies the
   [coreCIF default of 1.0](https://www.iucr.org/__data/iucr/cifdic_html/1/cif_core.dic/Iatom_site_occupancy.html).
   Explicit partial, unknown, or nonfinite occupancies and disordered groups
   are rejected. The default is a declared interpretation of the deposited
   model, not an independent experimental occupancy measurement.
3. Expand the conventional cell with
   [ASE's CIF reader](https://ase.gitlab.io/ase/ase/io/formatoptions.html#cif)
   and verify **four carbon sites**, with two at fractional **z = 0.25** and
   two at **z = 0.75**. The five-decimal source fractions are preserved.
4. Write [`graphite_p1.cif`](../examples/public_case/graphite_p1.cif) with four
   explicit sites, occupancy 1, and identity symmetry. This is still bulk
   graphite; its cell and coordinates have not been relaxed or given vacuum.
5. Select the two atoms at source z = 0.25, retain their fractional x/y and
   in-plane lattice, place both at z = 0.5, and set **c = 20 Å**. Write
   [`graphene_from_graphite_p1.cif`](../examples/public_case/graphene_from_graphite_p1.cif)
   as a two-site P1 cell with occupancy 1. This is an **unrelaxed constructed
   monolayer**, derived from the diffraction structure. The 20 Å repeat is a
   chosen model parameter.

For both inputs, **c** is the selected candidate normal and **a/b** span the
basal plane. The source's α = β = 90° supports that choice. Selecting a or b
as the normal fails the perpendicular-axis requirement because γ = 120°.
This check establishes the cell orientation used for screening; it does not
infer physical dimensionality from the structure.

## Independent comparison and measured results

The independent reference is a small standard-library calculation in the
preparation script. It uses the analytical hexagonal basis
**(a, 0, 0), (−a/2, √3a/2, 0), (0, 0, c)** and source-derived reference sites.
Those four sites follow from applying the source's identity operation and
**(−x, −x+y, z+1/2)** to its two asymmetric rows. The reference enumerates
all site pairs and translations from **[−2, 2]³**, excluding only the
zero-shift self-pair. This range includes the nearest periodic neighbours and
self-images for this specific wrapped hexagonal cell. It is not a general
reference algorithm for arbitrarily skewed cells.

The distance reference calls no CalcLens or ASE symmetry, minimum-image, or
distance routine. Gap and thickness references follow directly from the two
source planes separated by c/2, or the single constructed plane. This is an
independent numerical and analytical check of this case; it is not validation
by another simulation package or a DFT benchmark.

The committed
[`case_results.json`](../examples/public_case/case_results.json) records the
source hash, preparation, environment, both derived hashes, measured values,
reference values, errors, and issue codes. With ASE **3.29.0** and NumPy
**2.5.4**, using normal **c** and a short-contact threshold of **1.0 Å**:

| Observation | Expanded bulk graphite | Derived monolayer | Independent reference |
| --- | ---: | ---: | --- |
| Explicit sites | 4 | 2 | 2 planes × 2 sites; 1 plane × 2 sites |
| Shortest periodic distance (Å) | 1.422576837373 | 1.422576837373 | 1.422576837373 for both |
| Normal repeat height (Å) | 6.711 | 20 | source c; chosen slab c |
| Largest cyclic nuclei gap (Å) | 3.3555 | 20 | c/2; c |
| Nuclei-span thickness (Å) | 3.3555 | 0 | c/2; one plane |
| Second-largest nuclei gap (Å) | 3.3555 | 0 | second equal c/2 gap; no second interval |
| Short contacts below 1.0 Å | 0 | 0 | shortest distance exceeds threshold |

The largest absolute length discrepancy is **1.34 × 10⁻¹⁵ Å** when rounded
up; the script requires agreement within **10⁻⁹ Å**. For an exact honeycomb
lattice, the ideal nearest-neighbour expression **a/√3 = 1.422591063283 Å**
differs by about **1.423 × 10⁻⁵ Å**. That small difference follows from the
deposited five-decimal fractional coordinates, which the preparation does not
snap to exact thirds. The test allows **3 × 10⁻⁵ Å** for that ideal comparison.

The bulk report raises **AMBIGUOUS_SLAB** and **MULTIPLE_LARGE_GAPS**: its two
equal 3.3555 Å interlayer gaps do not identify a unique vacuum interval. The
derived monolayer has no gap-ambiguity warning under the current heuristic.
Both retain **GEOMETRY_ONLY** and **VACUUM_CONVERGENCE** information. Zero
monolayer thickness means zero span of the nuclear centres; the 20 Å gap
does not measure an electron-density vacuum boundary or demonstrate converged
vacuum, bonding, stability, forces, or electronic properties.

## Reproduce locally

From the repository root, using the environment installed from
`requirements.lock`:

```bash
PYTHONPATH=src .venv/bin/python scripts/prepare_public_case.py --check
PYTHONPATH=src .venv/bin/python -m pytest -q tests/test_public_case.py
```

The first command checks the bundled source hash, reproduces both prepared
CIFs and their measurements in memory, compares the independent reference,
and checks the committed artifacts without writing. To inspect newly written
artifacts in a separate directory:

```bash
PYTHONPATH=src .venv/bin/python scripts/prepare_public_case.py --output-dir work/public_case
PYTHONPATH=src .venv/bin/python -m slab_preflight.cli examples/public_case/graphite_p1.cif --normal-axis c
PYTHONPATH=src .venv/bin/python -m slab_preflight.cli examples/public_case/graphene_from_graphite_p1.cif --normal-axis c
```

No network request, added dependency, structure optimization, or external
calculation service is needed to reproduce the bundled case. Regenerating
with different dependency versions can change the recorded environment or
floating-point last digits; use the lockfile for the byte-for-byte `--check`.
