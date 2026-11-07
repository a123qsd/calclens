# CalcLens 0.9.1 for Windows

1. Download the [Windows x64 folder ZIP](https://github.com/a123qsd/calclens/releases/download/v0.9.1/CalcLens-0.9.1-Windows-x64-folder.zip).
2. Extract the complete ZIP into a new folder. Keep all extracted files together.
3. Open `CalcLens.exe` beside the `runtime` folder. Later launches use these files directly.
4. Once the graphene structure appears, choose **Open CIF** or drag a CIF into the window. Use the language selector to switch between English and Korean.

The folder includes Python and Qt. Extract upgrades into a separate folder. Local work runs offline. Closing the app lets you save your changes. The launcher has no publisher signature. To verify your download, compare this PowerShell command's output to the [SHA-256 checksums](https://github.com/a123qsd/calclens/releases/download/v0.9.1/SHA256SUMS.txt).

```powershell
Get-FileHash .\CalcLens-0.9.1-Windows-x64-folder.zip -Algorithm SHA256
```

[Desktop guide](../../docs/DESKTOP.md) · [Release source](https://github.com/a123qsd/calclens/archive/refs/tags/v0.9.1.zip) · [Windows build instructions](../desktop/windows-portable-build.md) · [Notices](../../THIRD_PARTY_NOTICES.md) · [Version 0.8.0 browser guide](https://github.com/a123qsd/calclens/blob/v0.8.0/packaging/windows/README.en.md)
