# CalcLens for Windows

CalcLens 0.3.0 runs on Windows 10 or 11, x64. The Windows executable includes
Python and its required packages. You do not need to install Python.

1. Open the [CalcLens release page](https://github.com/a123qsd/calclens/releases/tag/v0.3.0).
2. Download `CalcLens-0.3.0-windows-x64-en.exe` for English or
   `CalcLens-0.3.0-windows-x64-ko.exe` for Korean.
3. Double-click the file. A console opens, followed by a tab in your default
   browser. The executable unpacks its included files at startup; this can take
   several seconds. If the browser does not open, use the local address printed
   in the console.
4. Keep the console open while using CalcLens. Close it, or press `Ctrl+C` there,
   to stop the app. Closing the browser tab alone does not stop it.

The app listens only on `127.0.0.1`. Your CIF files are processed on your own
computer; this executable does not run a service for other computers. External
guide and GitHub links open their respective websites when you choose them.
You can change the interface language inside the app.

CalcLens checks CIF geometry. It does not establish chemical stability,
electronic structure, or vacuum convergence. Read the method notes in the app
and the [English guide](https://github.com/a123qsd/calclens/blob/main/README.en.md)
before interpreting a report.

## File checks and Windows warnings

These executables are unsigned and have no publisher certificate. Windows may
show an unknown-publisher or Microsoft Defender SmartScreen warning. Check the
release owner, source, and file checksum before deciding whether to run a file.
Do not disable Windows protections to use CalcLens. A matching checksum confirms
that your file matches the release checksum; it is not a publisher certificate
or a guarantee about the program.

Download `WINDOWS-SHA256SUMS.txt` from the same release. In PowerShell, compare
the value below with the entry for your downloaded file:

```powershell
Get-FileHash .\CalcLens-0.3.0-windows-x64-en.exe -Algorithm SHA256
```

## Notices, source, and rebuilding

The source ZIPs on the release page require a separate Python installation.
Use an `.exe` file above when you want to run CalcLens without installing Python.
`CalcLens-0.3.0-windows-support.zip` contains third-party notices, the exact ASE
source archive, dependency details, and the CalcLens source used for the build.
Keep that support ZIP with the executable when redistributing it. Its checksum
is listed in `WINDOWS-SHA256SUMS.txt`.

CalcLens's application license applies to its original code and documentation.
Bundled third-party components keep their own licenses. ASE is
LGPL-2.1-or-later: you may modify or replace ASE and rebuild CalcLens with it.
The application license preserves the rights needed to debug those changes.
The inventory records collected notices; it does not replace the license terms
or provide an exhaustive legal assessment.

To rebuild on Windows x64, install CPython 3.13 and extract the Windows support
ZIP. Open PowerShell in that extracted folder. The commands below read the
recorded source commit, extract the CalcLens source, and create a build
environment. They use its Python directly, so PowerShell activation is not
needed:

```powershell
$sourceCommit = (Get-Content .\DEPENDENCIES.json -Raw | ConvertFrom-Json).source_commit
Expand-Archive .\CalcLens-windows-source.zip .
Set-Location .\calclens-source
py -3.13 -m venv .venv
.\.venv\Scripts\python.exe -m pip install --require-hashes -r requirements.lock
.\.venv\Scripts\python.exe -m pip install --require-hashes -r packaging/windows/build-requirements.lock
.\.venv\Scripts\python.exe -m pip install --no-deps --no-build-isolation .
.\.venv\Scripts\python.exe scripts/build_windows.py --language ko --mode onefile --output dist/windows --source-commit $sourceCommit
.\.venv\Scripts\python.exe scripts/build_windows.py --language en --mode onefile --output dist/windows --source-commit $sourceCommit
```

For an ASE modification, unpack `sources/ase-3.29.0.tar.gz` from the support ZIP
and edit that source. After installing the pinned dependencies above, install
your modified ASE with
`.\.venv\Scripts\python.exe -m pip install --no-deps PATH_TO_MODIFIED_ASE`,
then run the two build commands again. Record your modification and retain its
license notices. Python is needed for rebuilding, not for using the supplied
executables. The dependency versions and source commit are recorded in
`DEPENDENCIES.json`; changing a component changes the build.
