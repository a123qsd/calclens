# Portable Windows desktop build

`scripts/build_portable_windows.py` assembles the Windows application from
the official CPython 3.13.17 embedded archive and repository hash-locked
Windows AMD64 wheels. Dependency discovery reads the selected wheels'
METADATA with Windows/Python 3.13 markers. It does not use the build host's
installed versions or copy its environment.

The builder checks cached archive hashes again, selects only the required
compatible wheels, verifies their dependency versions, and reconstructs a
clean payload. `--use-staged-runtime` reuses verified cached archives without
network access; it does not trust an old extracted payload. The selected
interpreter, Qt and scientific-library files run from the executable's own
temporary directory. `-I -B` preserves isolation from user Python packages and
prevents runtime bytecode-cache writes. No browser or external service is
needed for ordinary desktop startup.

Build with the normal development Python environment and NSIS:

```sh
NSISDIR=/path/to/nsis/share/nsis python scripts/build_portable_windows.py \
  --cache /path/to/builder-owned-cache \
  --output /path/to/CalcLens-0.9.0-Windows-x64.exe \
  --makensis /path/to/nsis/bin/makensis
```

Use `--stage-only` to prepare a runtime without compression. The cache's
`payload` directory belongs exclusively to this builder and is replaced;
never select a user project directory as the cache. A build records exact
source/runtime hashes in `DESKTOP-BUILD.json` inside the payload and an
`*.exe.manifest.json` sidecar. Every original wheel's license files remain
under `Lib/site-packages`, CPython's license is `LICENSE.txt`, and
`WINDOWS-RUNTIME-NOTICES.txt` describes the layout and source links.

NSIS's Unicode self-extractor is an I386 PE launcher; it starts the bundled
AMD64 interpreter/Qt application and waits for its exit status. The
application requires x64 Windows with the usual WOW64 support for that
launcher. It is not an application for 32-bit Windows or a native ARM64 build.
Record launcher and runtime architectures separately when inspecting a build.

## Isolated Wine validation

The Wine checks are a compatibility test on the actual Windows executable,
not a physical Windows-machine or Windows GPU-driver validation. The native
smoke creates a real Qt MainWindow, checks a CIF, tests save/readback, verifies
that no browser/socket listener is started, and writes JSON plus a screenshot:

```text
CalcLens-0.9.0-Windows-x64.exe --language en --native-smoke C:\test\result.json
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
