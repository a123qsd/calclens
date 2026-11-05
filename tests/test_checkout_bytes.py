"""Source provenance must survive Git's Windows-style checkout conversion."""
from hashlib import sha256
import json
from pathlib import Path
import subprocess

ROOT = Path(__file__).resolve().parents[1]


def test_public_case_bytes_survive_autocrlf_checkout(tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir()

    def git(*args):
        return subprocess.run(["git", "-C", str(repo), *args], check=True,
                              capture_output=True)

    git("init", "-q")
    git("config", "core.autocrlf", "true")
    git("config", "core.safecrlf", "false")
    (repo / ".gitattributes").write_bytes((ROOT / ".gitattributes").read_bytes())
    # This control proves CRLF conversion was actually enabled by the fixture.
    (repo / "control.txt").write_bytes(b"checkout control\n")
    paths = [
        "examples/public_case/source/9011577-rev291877.cif",
        "examples/public_case/graphite_p1.cif",
        "examples/public_case/graphene_from_graphite_p1.cif",
        "examples/public_case/case_results.json",
    ]
    electronic = json.loads((ROOT / "examples/electronic_case/manifest.json").read_bytes())
    paths.extend(f"examples/electronic_case/{name}" for name in electronic["sha256"])
    paths.extend(["examples/electronic_case/manifest.json", electronic["preparation_script"]])
    reference_root = "examples/electronic_case/independent_viewer"
    reference = json.loads((ROOT / reference_root / "manifest.json").read_bytes())
    paths.extend(f"{reference_root}/{name}" for name in reference["sha256"])
    paths.extend([f"{reference_root}/manifest.json", reference["script"]])
    for name in paths:
        target = repo / name
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes((ROOT / name).read_bytes())
    git("add", ".")
    checkout = tmp_path / "checkout"
    checkout.mkdir()
    git("checkout-index", "--all", "--force", f"--prefix={checkout.as_posix()}/")
    assert (checkout / "control.txt").read_bytes() == b"checkout control\r\n"
    for name in paths:
        assert (checkout / name).read_bytes() == (ROOT / name).read_bytes()
    assert sha256((checkout / paths[0]).read_bytes()).hexdigest() == (
        "35d1661c3131acc9b1c33dad65358d094b93105d6aae711465ac4352ae809748"
    )
