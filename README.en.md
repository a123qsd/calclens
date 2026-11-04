# CalcLens

**Inspect the geometry of a 2D material CIF before setting up a calculation.**

View atoms and the cell, find short periodic contacts and duplicate sites, and
measure the span of nuclear positions and the largest empty interval along a
selected normal axis (a, b, or c).
The app runs locally after installation. No external API key or paid computation
service is required.

[Project home](https://github.com/a123qsd/calclens) · [한국어 안내](README.ko.md) · [English ZIP and installation](docs/DOWNLOADS.md#english) · [Methods and limits](docs/METHODS.md) · [Example provenance](docs/PROVENANCE.md) · [Development](docs/DEVELOPMENT.md) · [Validation record](docs/VALIDATION.md)

This guide covers **CalcLens v0.3.0**, including portable review projects,
per-file comparison settings and filters, session caching, source identity in
reports, and contact evidence preserved outside detail tables.

![CalcLens structure, nearest-pair and gap inspection](docs/assets/calclens-overview.png)

[Watch the short demo](docs/assets/calclens-demo.webm) ·
[Read the public graphite case](docs/CASE_STUDY.md)

> This tool does not establish structural stability or calculation accuracy.
> Its gap is a geometric measurement between nuclear positions.
> Vacuum sufficiency requires convergence tests in the intended calculation.

## Run locally

For an English-default ZIP, choose the English asset on the
[latest release](https://github.com/a123qsd/calclens/releases/latest) and follow
the [download instructions](docs/DOWNLOADS.md#english). A standalone
[English guide file](https://github.com/a123qsd/calclens/releases/download/v0.3.0/CalcLens-Guide.en.md)
is also available. Python 3.12 or 3.13 and dependency
installation are required; this is not a standalone executable.

To clone the source with Git instead, use the commands below. These installation
examples use Python 3.12.

```bash
git clone https://github.com/a123qsd/calclens.git
cd calclens
python3.12 -m venv .venv
source .venv/bin/activate
python -m pip install --require-hashes -r requirements.lock
python -m pip install --no-deps --no-build-isolation .
python run_app.py --language en
```

On Windows, create the environment with `py -3.12 -m venv .venv` and activate it
in PowerShell with `.venv\Scripts\Activate.ps1`.
Installing the packages initially requires an internet connection.

Open the local address shown in the terminal. Select an example or provide a
CIF file. Start with graphene, then compare `graphene_duplicate.cif` to see how
a duplicate site is reported. You can switch between English and Korean in the
interface. Use `python run_app.py` to start with a ZIP's default language.

Select a review check or contact pair to highlight the related sites and periodic image.
The **View nearest pair** button under the shortest-distance metric opens one
pair realizing that minimum, even when it is above the warning cutoff.
Inspect the gap along the selected axis, and download the criteria and results
as JSON or CSV. If a contact table reaches its 200-record limit, overlaps and
shorter distances take priority, with minimum-distance and self-image evidence
retained when below the cutoff. Exact issue counts and a representative pair
or image remain in the exports.

## Compare CIF files

1. Choose **Compare CIF files** in the input selector and upload up to 20 CIFs.
2. Set the axis and short-distance cutoff for each file. Every file starts at
   c and 1.0 Å; check the actual layer direction before interpreting its gap.
3. Read the comparison table and select a row to open that file's detailed
   structure view, findings, and JSON/CSV downloads. The first file opens initially.
4. Use **Export all comparison CSV** to save one summary row per file.

Each file is checked independently and keeps the 2 MiB and 400-site limits.
An unsupported file stays in the table with blank measurements; select its row
to read the reason. The other files are still checked. Status values are `unsupported`,
`review_required`, and `no_flags`. The last means that no screening warnings or
errors were found, not that the structure is valid. Warning/error columns count
findings, while distance-issue pair counts are in the detailed reports.

The comparison table and summary CSV follow the interface language. Detailed
JSON/CSV reports have the separate report-language setting described below.

## Save and continue a comparison

Each comparison entry keeps its own axis and cutoff as the file list changes.
When you edit conditions or reorder or remove other files, the detail view stays
on the selected file. Results are cached for the session by file content, axis,
and cutoff, so unchanged checks can be reused.

Use **All**, **Needs review**, or **Input errors** to filter the compact comparison
table. The comparison CSV still includes every file and its provenance; filtering
does not remove results from exports. Individual reports retain their results
and source identity.

To continue later, choose **Save project** on the comparison screen to download
a `.calclens.json` file. It stores the original CIF bytes, unique entry IDs,
per-file conditions, selected file, review focus and filter, notes, and reviewed
checkbox state. In the sidebar, choose **Open saved work**, upload that file,
and click **Open project**. The original CIF files are no longer needed.

Opening a project rejects corrupt or missing CIF payloads and SHA-256 mismatches.
If its saved engine version differs from the current engine, the app warns and
recomputes the reports with the current version. A project restores your work;
the JSON/CSV reports remain analysis exports and cannot be opened as projects.

## Command line

Run the same check from the command line and save a JSON report:

```bash
calclens examples/graphene.cif --normal-axis c --language en --json report.json
calclens examples/mos2_a_normal.cif --normal-axis a --language en --csv report.csv
```

Choose either `--json` or `--csv` per command. Both create a new file and refuse
to overwrite an existing one. CSV site numbers start at 1; JSON atom indices
start at 0. Exit codes
are `0` for no error-level findings (warnings may remain), `1` for a geometric
error such as overlapping sites, and `2` for unsupported input, read, argument,
or output errors.

## Report language

The report-language selector defaults to “Same as interface.” You can choose
English or Korean independently before downloading JSON or CSV. Downloads use
`_calclens_en` or `_calclens_ko` in the filename. The CLI uses English by default;
pass `--language ko` for Korean explanations or `--language en` for English.
The ZIP's default interface language does not change that CLI default.

JSON keeps canonical English field names, issue codes, severity values, units,
atom indices, and all numerical results unchanged. `report_language` identifies
the selected language. Human-readable issue messages, assumptions, and
limitations use that language. Korean JSON also preserves the original English
text in `message_en`, `assumptions_en`, and `limitations_en` fields.

CSV headings and explanation text follow the chosen language. Technical values
such as issue codes, record types, severity, and units remain stable identifiers
for comparison and automated processing. Korean CSV files from the app and CLI
use UTF-8 with a BOM for spreadsheet compatibility; JSON uses UTF-8 without a BOM.
Changing language does not change the scientific criteria or results.

## Source identity and contact evidence

App and CLI JSON/CSV reports include the original filename, the SHA-256 of the
exact file bytes, the CalcLens package version, and the ASE version. The hash is
computed before decoding or newline conversion, so a line-ending change produces
a different file identity even if the measured geometry stays the same.

JSON stores these fields in `provenance`. CSV uses `provenance` rows and keeps a
`minimum_pair` row with site numbers, elements, distance, and periodic image shift,
including when the short-contact list is empty. Distance findings retain exact
`contact_count` values and a `representative_contact`; CSV exports the representative
as an `issue_contact` row. These are screening records, not a complete neighbor list.

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

CalcLens inspects CIF geometry. Gaussian or ORCA logs, calculation execution,
SCF convergence, optimization results, and vibrational frequencies are outside
its scope. See [METHODS.md](docs/METHODS.md) for tolerances and equations.

## Examples and verification

The [examples](examples/README.md) include idealized graphene, h-BN, and MoS₂
models, plus deliberately altered structures with overlaps, short contacts,
and a layer crossing the cell boundary. They were generated for this repository;
they are neither experimental structures nor relaxed research results.

The separate [public graphite case](docs/CASE_STUDY.md) starts from a published
Crystallography Open Database record and documents its conversion and limitations.

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
