# Portable Windows desktop build

The 0.9.1 Windows release is the [x64 folder ZIP](https://github.com/a123qsd/calclens/releases/download/v0.9.1/CalcLens-0.9.1-Windows-x64-folder.zip).
Check the downloaded ZIP against [SHA256SUMS.txt](https://github.com/a123qsd/calclens/releases/download/v0.9.1/SHA256SUMS.txt).

`scripts/build_portable_windows.py` assembles the Windows application from
the official CPython 3.13.17 embedded archive and repository hash-locked
Windows AMD64 wheels. Dependency discovery reads the selected wheels'
METADATA with Windows/Python 3.13 markers. It does not use the build host's
installed versions or copy its environment.

The builder checks cached archive hashes again, selects only the required
compatible wheels, verifies their dependency versions, and reconstructs a
clean payload. `--use-staged-runtime` reuses verified cached archives without
network access; it does not trust an old extracted payload.

The default deliverable is a folder ZIP. Extract the complete ZIP once and
open `CalcLens.exe` beside its `runtime` folder. Subsequent launches reuse
these files directly. There is no shared extraction cache, per-launch runtime
unpacking, installer or administrator requirement. Keep the complete extracted
folder together; moving only its EXE removes the required runtime.

`-I -B` isolates the embedded interpreter from user Python packages and
prevents runtime bytecode-cache writes. Ordinary desktop startup runs locally.

Build with the normal development Python environment and NSIS:

```sh
NSISDIR=/path/to/nsis/share/nsis python scripts/build_portable_windows.py \
  --cache /path/to/builder-owned-cache \
  --output /path/to/CalcLens-0.9.1-Windows-x64-folder.zip \
  --makensis /path/to/nsis/bin/makensis
```

Use `--stage-only` to prepare a runtime without compression. The cache's
`payload` directory belongs exclusively to this builder and is replaced;
never select a user project directory as the cache. A build records exact
source/runtime hashes in `DESKTOP-BUILD.json` inside the payload and an
`*.zip.manifest.json` sidecar. Every original wheel's license files remain
under `Lib/site-packages`, CPython's license is `LICENSE.txt`, and
`WINDOWS-RUNTIME-NOTICES.txt` describes the layout and source links.

NSIS compiles a small I386 PE folder launcher; it starts the bundled AMD64
interpreter/Qt application and waits for its exit status. The
application requires x64 Windows with the usual WOW64 support for that
launcher. It is not an application for 32-bit Windows or a native ARM64 build.
Record launcher and runtime architectures separately when inspecting a build.

The ZIP is written to a temporary sibling and replaced only after its complete
payload has been checked against the build manifest. Extract upgrades into a
new folder rather than merging runtime versions. Concurrent launches read the
same immutable runtime and write separate per-process diagnostic logs.

For a comparison with the previous solid-LZMA distribution, explicitly pass
`--format self-extracting --output /path/to/CalcLens-comparison.exe`. That
variant unpacks its runtime on every invocation. It measures that unpacking
step with `GetTickCount` and records `runtime_unpack_ms`. The folder variant
records zero runtime unpacking; this is a packaging property, not a claim
that total application startup takes zero milliseconds.

## Startup readiness and failure diagnostics

The default desktop shows its main window before creating the research panel
and completing its initial graphene analysis. The status bar reports progress
and any failure. Data validation remains part of the background analysis.
`--startup-trace TRACE.json` records Python entry, Qt/scientific imports, Qt
initialization, the actual main window, completed default analysis, and a
posted input response. A first window alone does not set `ready: true`.
`--startup-benchmark TRACE.json` closes after those readiness events. Import,
initialization and rendering durations are separate milestones.

The bootstrap installs diagnostic logging before importing Qt or scientific
packages. Logs are per process under `%LOCALAPPDATA%\CalcLens\logs`, with a
temporary-folder fallback if that directory cannot be created. Logs contain
error classes, frame locations and startup phases, without project contents,
command-line arguments, exception argument values or remote tokens. Startup
errors show a Windows error dialog even if Qt cannot initialize. The launcher
also writes its own process/exit-status log before Python starts, checks the
required interpreter/standard-library/bootstrap files, and reports failure to
start Python or an unexpected nonzero exit. This covers interpreter failures
that cannot execute Python's diagnostic handler.

Run repeated measurements on the same Windows device and desktop settings:

```powershell
python scripts/benchmark_desktop_startup.py `
  --exe C:\CalcLens\CalcLens.exe --runs 3 --output C:\timings\folder
```

The first run is labelled `first_observed`; OS disk caches are not cleared, so
it is not labelled a cold-boot result. Later runs are labelled `repeat`. On
Windows, a parent monotonic timestamp includes launcher/Python startup in the
trace. `process_wall_ms` also includes orderly shutdown, which is distinct
from readiness. For an old EXE without instrumentation, `--legacy-smoke`
measures the complete native smoke only; that total cannot be presented as a
first-window or first-input timing. Use `--runner /path/to/wine` for explicitly
labelled Wine compatibility measurements. Wine timings do not establish
Windows-machine performance or Windows GPU behavior. The parent also observes
trace updates every 25 ms; those receipt times are upper bounds affected by
host scheduling. The input milestone is a posted Qt F24 probe after default
analysis, not a physical keyboard or mouse hardware measurement.

## Isolated Wine validation

The Wine checks are a compatibility test on the actual Windows executable,
not a physical Windows-machine or Windows GPU-driver validation. The native
smoke creates a real Qt MainWindow, checks a CIF, tests save/readback, verifies
that no browser/socket listener is started, and writes JSON plus a screenshot:

```text
C:\CalcLens\CalcLens.exe --language en --native-smoke C:\test\result.json
```

Use a new disposable Wine prefix. Qt 6.12 expects ICU services supplied by
modern Windows, while this Wine build lacks their implementation. The
`windows-wine-icu.json` fixture pins two AMD64 system DLLs from Microsoft's
symbol server by URL, exact size and SHA-256. Their discovery index is noted
separately. `windows-prepare-wine.py` installs them only in an existing Wine
prefix; it refuses a directory without Wine's `system.reg` and system tree.
These system files are never placed in, or shipped with, the CalcLens payload.
The builder explicitly rejects their presence there.

```sh
python packaging/desktop/windows-prepare-wine.py \
  --prefix /path/to/disposable-wine-prefix \
  --wine /path/to/wine \
  --font-directory /path/to/payload/Lib/site-packages/matplotlib/mpl-data/fonts/ttf
```

The font option copies two unchanged, hash-checked DejaVu fonts from the
locked Matplotlib wheel into this prefix's Fonts directory. The helper sets
`QT_QPA_PLATFORM=offscreen` and `QT_QPA_FONTDIR=C:\windows\Fonts` in the prefix's
Windows environment because some macOS Wine launchers discard Unix `QT_*`
variables. Without this setup the offscreen font database is empty, even
though the application runs; a screenshot full of missing glyphs must not
be presented as readable UI validation. The font setup supports the English
smoke; it does not establish Korean font coverage.

For the test only, set the same prefix and the bounded Wine overrides:
`WINEDEBUG=-all`, `MVK_CONFIG_LOG_LEVEL=0`, and
`WINEDLLOVERRIDES=winemenubuilder.exe=d;mscoree=d;mshtml=d;icuuc,icuin=n,b`.
Record the exact EXE hash after the smoke finishes, retain its JSON/screenshot,
and distinguish this equivalent-runtime check from an interactive physical
Windows test. This process does not read or change any installed virtual
machine or its settings.
