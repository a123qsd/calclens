# CalcLens

**Inspect the geometry of a 2D material CIF before setting up a calculation.**

View atoms and the cell, find short periodic contacts and duplicate sites, and
measure the span of nuclear positions and the largest empty interval along a
selected normal axis (a, b, or c).
The app runs locally after installation. No external API key or paid computation
service is required.

[한국어 안내](README.md) · [Methods and limits](docs/METHODS.md) · [Example provenance](docs/PROVENANCE.md) · [Development](docs/DEVELOPMENT.md) · [Validation record](docs/VALIDATION.md)

> This tool does not establish structural stability or calculation accuracy.
> Its gap is a geometric measurement between nuclear positions.
> Vacuum sufficiency requires convergence tests in the intended calculation.

## Run locally

Use Python 3.12:

```bash
git clone https://github.com/a123qsd/calclens.git
cd calclens
python3.12 -m venv .venv
source .venv/bin/activate
python -m pip install --require-hashes -r requirements.lock
python -m pip install --no-deps --no-build-isolation .
python -m streamlit run streamlit_app.py
```

On Windows, create the environment with `py -3.12 -m venv .venv` and activate it
in PowerShell with `.venv\Scripts\Activate.ps1`.
Installing the packages initially requires an internet connection.

Open the local address shown in the terminal. Select an example or provide a
CIF file. Start with graphene, then compare `graphene_duplicate.cif` to see how
a duplicate site is reported. Korean and English guidance is available.

Select a review check or contact pair to highlight the related sites and periodic image.
Inspect the gap along the selected axis, and download the criteria and results
as JSON or CSV.

Run the same check from the command line and save a JSON report:

```bash
calclens examples/graphene.cif --normal-axis c --json report.json
calclens examples/mos2_a_normal.cif --normal-axis a --csv report.csv
```

Choose either `--json` or `--csv` per command. Both create a new file and refuse
to overwrite an existing one. CSV site numbers start at 1; JSON atom indices
start at 0. Exit codes
are `0` for no error-level findings (warnings may remain), `1` for a geometric
error such as overlapping sites, and `2` for unsupported input, read, argument,
or output errors.

## Read the results

| Result | Meaning |
| --- | --- |
| Structure and cell | Positions and element identities, with highlights for selected atoms, contacts, and periodic images. Marker size is not an atomic radius. |
| Minimum periodic distance | Closest nuclear separation across cell boundaries, including an atom's nonzero periodic self-images. |
| Short contacts and overlaps | Distances below 1.0 Å are flagged by default. This configurable threshold is not an element-specific bond criterion. |
| Nuclei-span thickness | The selected-normal range of nuclear positions after removing the largest empty cyclic interval. It is not a physical material thickness. |
| Nuclei gap | Largest interval without a nucleus along a cyclic traverse of the selected normal axis. It is not an electron-density-free vacuum width. |
| Review notes | Unsupported input is distinguished from ambiguous geometry. An absence of warnings does not validate a calculation. |

A single atomic plane has a nuclei-span thickness of `0 Å`.
This does not imply that graphene has zero physical thickness.

## Supported input

- One **CIF 1.x P1 data block**, with every site explicitly listed
- Fractional coordinates, standard element symbols, and fully occupied sites
- A selected layer-normal axis (a, b, or c) perpendicular to the other two cell vectors
- At most 2 MiB and 1–400 sites per file

Non-P1 symmetry, partial or mixed occupancy, modulated, superspace, or composite
structures, a selected axis tilted relative to the other two vectors, and
multiple data blocks are unsupported. General CIF files can use symmetry-equivalent
positions or occupancy alternatives; treating these as accidental duplicates and
deleting them would be unsafe. CalcLens stops with an explanation instead.

Review occupancy separately in a suitable structure tool, then export a fully
expanded P1 structure if appropriate. Do not simply relabel a symmetry-reduced
CIF as P1 or delete sites to make it pass. Check the converted coordinates and
whether the selected axis is the intended slab normal.

For multiple layers or bulk-like structures, the largest empty interval may not
be the intended vacuum. Warnings catch some ambiguous cases using explicit
heuristics; they do not detect every multilayer or bulk structure.
Ambiguous results are marked for review.

CalcLens v0.1 inspects CIF geometry. Gaussian or ORCA logs, calculation execution,
SCF convergence, optimization results, and vibrational frequencies are outside
its scope. See [METHODS.md](docs/METHODS.md) for tolerances and equations.

## Examples and verification

The [examples](examples/README.md) include idealized graphene, h-BN, and MoS₂
models, plus deliberately altered structures with overlaps, short contacts,
and a layer crossing the cell boundary. They were generated for this repository;
they are neither experimental structures nor relaxed research results.

```bash
python scripts/generate_examples.py --check
python -m pytest
```

Tests cover analytical distances and gaps, an independently enumerated periodic
image reference, translation invariance, duplicates across a cell boundary,
units, and unsupported inputs. The scope is geometric and software verification.
No energy, force, or electronic-structure calculation is performed.

## Tools used

[ASE](https://docs.ase-lib.org/) supplies CIF parsing and periodic geometry.
Streamlit and Plotly provide the interface.
[pymatgen](https://pymatgen.org/) also supports CIF and materials analysis.
CalcLens adds a narrow input contract and beginner-facing explanations to
existing tools; it does not replace general materials analysis or simulation software.

## Files and privacy

The app has no feature that sends a CIF to an external AI or analysis API.
In a local session, the browser sends the file to the Streamlit server on the
same computer. If someone hosts the app remotely, that server receives the file;
check its operating environment before supplying unpublished research data.
Use only shareable, minimal examples in public bug reports.

## License

Personal, educational, academic, and internal organizational or business use
is free. Modification and free redistribution are permitted under the license.
Selling the program, charging for its use or access, or offering its functionality
as a paid service requires the copyright holder's prior written permission.
Genuinely free inclusion alongside an unrelated paid product is permitted when
no consideration is for the program itself, its use, or access.
These restrictions do not apply to research results, figures, reports, or other outputs.

This is **source-available software**, not OSI-approved open source, because sale
and paid services are restricted. [LICENSE](LICENSE) contains the governing terms.
Dependencies retain their own licenses; see [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md).
