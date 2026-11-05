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
