"""Exercise release argument expansion through the actual PowerShell runtime."""

import json
import os
from pathlib import Path
import shutil
import subprocess
import sys

import pytest


@pytest.mark.parametrize("legacy", [False, True])
def test_release_workflow_passes_complete_optional_flag(legacy):
    powershell = shutil.which("pwsh")
    if powershell is None:
        pytest.skip("PowerShell is exercised by Windows CI")
    workflow = Path(__file__).resolve().parents[1] / ".github/workflows/windows-release.yml"
    assignments = [line.strip() for line in workflow.read_text(encoding="utf-8").splitlines()
                   if line.strip().startswith("$legacyFlags =")]
    assert assignments, "Release workflow must expose its optional arguments"
    executable = sys.executable.replace("'", "''")
    echo_arguments = (f"& '{executable}' -c "
                      "'import json, sys; print(json.dumps(sys.argv[1:]))' @legacyFlags")
    script = "\n".join(f"{assignment}\n{echo_arguments}" for assignment in assignments)
    result = subprocess.run(
        [powershell, "-NoProfile", "-NonInteractive", "-Command", script],
        env={**os.environ, "CALCLENS_INCLUDE_LEGACY_UI": "1" if legacy else "0"},
        capture_output=True, text=True, check=True, timeout=30,
    )
    received = [json.loads(line) for line in result.stdout.splitlines() if line.strip()]
    expected = ["--include-legacy-ui"] if legacy else []
    assert received == [expected] * len(assignments)


def test_native_builder_receives_compiler_path_with_spaces_as_one_argument():
    powershell = shutil.which("pwsh")
    if powershell is None:
        pytest.skip("PowerShell is exercised by Windows CI")
    workflow = Path(__file__).resolve().parents[1] / ".github/workflows/windows-release.yml"
    line = next(line.strip() for line in workflow.read_text().splitlines()
                if line.strip().startswith("python scripts/build_portable_windows.py "))
    executable = sys.executable.replace("'", "''")
    command = line.replace("python ", f"& '{executable}' -c 'import json, sys; print(json.dumps(sys.argv[1:]))' ", 1)
    result = subprocess.run(
        [powershell, "-NoProfile", "-NonInteractive", "-Command", command],
        env={**os.environ, "CALCLENS_VERSION": "0.9.1",
             "CALCLENS_NSIS": r"C:\Program Files (x86)\NSIS\makensis.exe"},
        capture_output=True, text=True, check=True, timeout=30,
    )
    assert json.loads(result.stdout) == [
        "scripts/build_portable_windows.py", "--cache", "build/native-folder",
        "--output", "dist/CalcLens-0.9.1-Windows-x64-folder.zip", "--makensis",
        r"C:\Program Files (x86)\NSIS\makensis.exe",
    ]


def test_published_release_and_manual_build_share_the_folder_verifier():
    workflow = Path(__file__).resolve().parents[1] / ".github/workflows/windows-release.yml"
    text = workflow.read_text()
    published = text.split("  test-published-exe:", 1)[1].split("  build:", 1)[0]
    assert 'CalcLens-$version-Windows-x64-folder.zip' in published
    assert 'Invoke-WebRequest "$base/$file.manifest.json"' in published
    assert "--checksums SHA256SUMS.txt --version $version" in published
    assert 'Start-Process -FilePath "$env:CALCLENS_EXE"' in published
    assert "Windows-x64.exe" not in published
    assert text.count("python .github/scripts/verify_windows_folder.py") == 2
    assert "dist/CalcLens-${{ env.CALCLENS_VERSION }}-Windows-x64-folder.zip.manifest.json" in text
