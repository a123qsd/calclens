# Optional independent researcher usability protocol

This is a proposed protocol, not a completed study. No participants have been
recruited, observed, scored or quoted. Recruitment, external file sharing and
collection of participant information require a separate authorized action.

The practical question is whether a researcher can identify the limits of a
slab preflight result, trace a displayed number to its input, and distinguish
an incomplete calculation from evidence of convergence.

## Participants and setup

Recruit three to five researchers who have used periodic electronic-structure
software, with varied familiarity with CIFs and slab calculations. Report
their experience in broad categories; do not collect institutional identities,
private research files, login details or unpublished results. Use only the
bundled controlled/public examples. Ask permission before recording a screen
or retaining a quotation. A participant can stop at any point.

Use a fresh launch of the exact distributable being evaluated. Record its
version, artifact SHA-256, operating system and display scale, along with the
test start/end times. Evaluate the native desktop application separately from
the optional browser workspace; do not combine their results. Automated tests
and developer observations must be reported separately from participant data.

## Tasks and observable success criteria

Give the task, then allow the participant to work without leading them to the
desired answer. Ask them to describe what they think the result means. Record
assistance only after the initial attempt.

| Task | Case | Observable success |
| --- | --- | --- |
| Identify the scope | Planar h-BN CIF | Explains that a nuclei gap does not establish density-free vacuum or calculation convergence. |
| Find a boundary issue | Wrapped MoS₂ and boundary-overlap CIFs | Distinguishes the intact wrapped layer from an actual overlapping site pair; finds atom/image evidence. |
| Recognize preparation limits | Partial occupancy or unexpanded symmetry | Identifies the rejection and does not interpret a rejected input as a successful scientific result. |
| Trace a result | One original Gaussian reference output | Locates method/basis, charge/multiplicity, exact original hash and the source line for the final SCF energy. |
| Separate execution from chemistry | Optimization/frequency reference plus labelled incomplete/failure fixture | Distinguishes normal termination, optimization completion and reported negative frequencies; does not claim stability from an energy alone. |
| Interpret a series | h-BN `series.json` | Identifies the fixed conditions, variable, largest successful reference and 1 meV/atom criterion; states the small-basis/Gamma/grid limitations. |
| Export a useful figure | A charge or volume display | Chooses the intended background/crop and checks the exported dimensions, displayed-data annotations, units and source. |
| Reopen provenance | A saved project/report with its original input | Confirms which source file the reopened measurements belong to. |

The observer may ask, “What does this number mean to you?” or “What evidence
would you check next?” Avoid teaching the intended interpretation before the
participant has explained their own understanding. Never ask participants to
upload an unpublished structure or use a paid/live calculation account.

## Recording and reporting

For each task, record completion without help, completion after help, failure,
or not attempted; elapsed time; where the participant hesitated; their stated
interpretation; and any resulting UI defect. Set a practical time limit before
the session and record it. Do not redefine success after seeing the outcome.

Use an empty row template until observations actually exist:

| Anonymous session | App/version/hash | Task | Outcome | Time | Assistance | Observed interpretation | Follow-up issue |
| --- | --- | --- | --- | --- | --- | --- | --- |
| — | — | — | — | — | — | — | — |

Summarize counts with denominators and retain contradictory observations.
Small exploratory sessions can reveal problems; they do not establish a
population-wide usability score or scientific validity. Link each implemented
repair to an observed issue and a fresh verification result. Keep identifying
data and optional recordings outside published reports, with the participant's
agreed retention/deletion terms.
