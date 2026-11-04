# Developing CalcLens

CalcLens is a local CIF geometry inspection tool. The public package and CLI
are named `calclens`; the internal Python module remains `slab_preflight`.
This naming difference does not indicate a second application.

## Local workflow

Use Python 3.12 and install the pinned runtime, build, and test dependencies:

```bash
python -m pip install --require-hashes -r requirements.lock
python -m pip install --no-deps --no-build-isolation .
python -m pytest
python -m ruff check .
python run_app.py --language en
```

The installation command builds and installs the current source tree. After
changing package files, reinstall with the same command before testing the
installed CLI or launching the app. The repository's pytest configuration is the
source of truth for how tests locate the code.

## Current responsibilities

| Component | Responsibility |
| --- | --- |
| `src/slab_preflight/core.py` | Input validation, periodic distances, gap/span measurements, and structured findings |
| `src/slab_preflight/cli.py` | Bounded file reading, options, JSON/CSV output, and exit status |
| `src/slab_preflight/reporting.py` | English/Korean report descriptions and CSV export with criteria, units, findings, and numbering conventions |
| `src/slab_preflight/plotting.py` | Visual representation of the report, including selected sites and periodic images |
| `streamlit_app.py` | Korean/English interaction, example selection, uploaded CIFs, review messages, and downloads |
| `scripts/generate_examples.py` | Reproducible analytical fixtures; no remote data retrieval |
| `run_app.py` | Local launch and initial interface language |
| `scripts/build_release.py` | Reproducible language-specific source packages from a clean committed tree |
| `tests/` | Analytical, periodic-image, input-scope, CLI, and interface checks |

Keep scientific definitions in the core and reuse its output in the interface.
Changing the display must not change whether a file is accepted or how its
geometry is calculated. Explain unsupported cases without deleting, merging,
or repairing input sites automatically.

A new accepted input condition needs a test that exposes the assumption it
introduces. For geometry changes, use an analytical case or an independent
reference calculation, including periodic boundaries. Update
[METHODS.md](METHODS.md) and any affected example expectations together.

## Reports and compatibility

The JSON report contains a schema version, units, normal-axis choice, geometric
criteria, findings, and limitations. Treat the selected axis and screening
cutoff as part of the result: a bare number without its convention is insufficient.
CSV is a readable export, while JSON retains the structured report. A future
incompatible change to a field's meaning needs an explicit schema migration.

Localize report descriptions in the reporting layer, not the geometry core.
JSON keys, diagnostic codes, units, measurements, and indices stay canonical.
The selected report language must not change criteria, findings, or exit codes.
Keep English originals alongside Korean descriptions so that the evidence can
be inspected in either language. Korean CSV headings are intended for readers;
use JSON or the default English CSV for stable programmatic field names.

## Source release packages

After testing and committing the complete release, run:

```bash
python scripts/build_release.py
```

The builder requires a clean working tree and packages the committed source.
It produces English and Korean source ZIPs, standalone language guides, and
`SHA256SUMS.txt` under `dist/`. Both packages contain the same calculation code
and dependency lockfiles. Their initial language and entry guide differ.
They require Python and dependency installation; they are not bundled executables.
See [DOWNLOADS.md](DOWNLOADS.md) for setup instructions.

The internal module name may be changed later, but public CLI behavior and report
semantics need a deliberate compatibility decision. Do not silently change a
legacy field from a c-axis measurement to a measurement along some other axis.

## Boundary for future calculation-log support

Gaussian/ORCA output, SCF convergence, geometry-optimization histories, and
vibrational frequencies are not implemented. A CIF supplies structural data;
it cannot establish whether an electronic calculation converged, whether an
optimization finished, or whether imaginary frequencies were present.

If log support is added, keep it separate from the CIF report and parser. Start
with one named program and documented output versions, preserve units and the
source of every extracted value, and distinguish a completed calculation from
an incomplete or unrecognized log. Use a separate schema for calculation events
and results. Connect it to a structure only when the input supplies an explicit,
checkable relationship.

That extension requires its own public fixtures, licensing/provenance review,
and tests for failed, interrupted, concatenated, and partially written outputs.
Do not make a generic “calculation passed” badge from missing error strings or
from a CIF geometry report. No log framework or execution service is needed to
maintain the current tool.

## 한국어 개발 메모

현재 범위는 CIF 기하 검사입니다. 계산 로그를 추가할 때는 지원 프로그램과 출력
버전을 먼저 정하고, CIF 보고서와 별도의 파서·스키마·테스트로 구현해야 합니다.
CIF만 보고 SCF 수렴, 최적화 완료, 허수 진동수 유무를 추정해서는 안 됩니다.
입력을 자동으로 고쳐 통과시키는 대신, 판단할 수 없는 이유를 남기는 원칙을 유지합니다.
