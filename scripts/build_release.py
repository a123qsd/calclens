"""Build reproducible English/Korean source ZIPs from a clean, committed HEAD.

No dependency download, execution of repository code, or GitHub mutation occurs.
Ignored local files are never considered. Untracked, nonignored files and tracked
changes block release generation. The archive contains only regular tracked files
read by immutable Git object IDs, plus deterministic release metadata.
"""

from __future__ import annotations

import argparse
import hashlib
import io
import json
from pathlib import Path, PurePosixPath
import posixpath
import re
import subprocess
import tempfile
import tomllib
from urllib.parse import quote, urlsplit, urlunsplit
import zipfile


class ReleaseError(ValueError):
    """A release precondition failed; no assets should be published."""


FORBIDDEN_PARTS = {
    ".git", ".hg", ".svn", ".venv", "venv", "env", ".aws", ".ssh", ".gnupg",
    "uploads", "__pycache__", "node_modules", ".pytest_cache", ".ruff_cache",
}
FORBIDDEN_FILES = {
    "secrets.toml", "credentials", "credentials.json", "id_rsa", "id_ed25519",
    ".netrc", ".npmrc", "report.json", "report.csv",
}
RESERVED_FILES = {"DEFAULT_LANGUAGE.txt", "BUILD_INFO.json", "START_HERE.md"}
REQUIRED_FILES = {
    "pyproject.toml", "requirements.lock", "uv.lock", "LICENSE", "THIRD_PARTY_NOTICES.md",
    "README.en.md", "README.ko.md", "streamlit_app.py", "run_app.py",
}


def _git(repo: Path, *args: str) -> bytes:
    result = subprocess.run(
        ["git", "-C", str(repo), *args], check=False,
        stdout=subprocess.PIPE, stderr=subprocess.PIPE,
    )
    if result.returncode:
        raise ReleaseError(f"Git operation failed ({' '.join(args[:2])}): "
                           + result.stderr.decode("utf-8", errors="replace").strip())
    return result.stdout


def _safe_path(path: str) -> None:
    parts = path.split("/")
    if (not path or path.startswith("/") or "\\" in path or ":" in path
            or any(part in ("", ".", "..") for part in parts)
            or any(part.endswith((" ", ".")) for part in parts)
            or any(ord(char) < 32 or ord(char) == 127 for char in path)):
        raise ReleaseError(f"Unsafe archive path: {path!r}")
    lowered = [part.lower() for part in parts]
    reserved_windows = {"con", "prn", "aux", "nul"} | {f"{prefix}{n}" for prefix in ("com", "lpt") for n in range(1, 10)}
    if any(part.split(".", 1)[0] in reserved_windows for part in lowered):
        raise ReleaseError(f"Unsafe archive path on Windows: {path!r}")
    filename = lowered[-1]
    if (any(part in FORBIDDEN_PARTS or part.startswith(".env") for part in lowered)
            or filename in FORBIDDEN_FILES
            or PurePosixPath(filename).suffix in (".pem", ".key", ".p12", ".pfx", ".jks")):
        raise ReleaseError(f"Private, generated, or environment path cannot be released: {path}")


def _clean(repo: Path) -> None:
    status = _git(repo, "status", "--porcelain=v1", "--untracked-files=all", "--ignored=no", "-z")
    if status:
        raise ReleaseError("Release requires a clean tracked tree and no nonignored untracked files. "
                           "Commit intended source changes; keep local data ignored and untracked.")


def committed_files(repo: Path) -> tuple[str, dict[str, tuple[bytes, int]]]:
    """Return bytes and Git modes from one immutable commit, never working files."""
    root = Path(_git(repo, "rev-parse", "--show-toplevel").decode().strip()).resolve()
    if root != repo.resolve():
        raise ReleaseError("Build from the repository root, not a nested directory.")
    _clean(repo)
    commit = _git(repo, "rev-parse", "--verify", "HEAD^{commit}").decode().strip()
    files: dict[str, tuple[bytes, int]] = {}
    casefolded: set[str] = set()
    for record in _git(repo, "ls-tree", "-rz", "--full-tree", commit).split(b"\x00"):
        if not record:
            continue
        metadata, raw_path = record.split(b"\t", 1)
        mode, kind, object_id = metadata.decode("ascii").split()
        try:
            path = raw_path.decode("utf-8")
        except UnicodeDecodeError:
            raise ReleaseError("Archive paths must be UTF-8 text.") from None
        _safe_path(path)
        if kind != "blob" or mode not in ("100644", "100755"):
            raise ReleaseError(f"Only regular files can be released; symlinks/submodules rejected: {path}")
        if path.casefold() in casefolded:
            raise ReleaseError(f"Case-insensitive filename collision: {path}")
        casefolded.add(path.casefold())
        if path in RESERVED_FILES:
            raise ReleaseError(f"Release-generated metadata must not be tracked: {path}")
        files[path] = (_git(repo, "cat-file", "blob", object_id), int(mode, 8))
    missing = REQUIRED_FILES - files.keys()
    if missing:
        raise ReleaseError("Missing release files: " + ", ".join(sorted(missing)))
    _clean(repo)
    if _git(repo, "rev-parse", "HEAD").decode().strip() != commit:
        raise ReleaseError("HEAD changed during the build; retry against a stable commit.")
    return commit, files


def absolute_guide_links(markdown: str, repository_url: str, commit: str) -> str:
    """Make repository-local Markdown links work in a standalone guide download."""
    def target_url(target: str) -> str:
        angle_wrapped = target.startswith("<") and target.endswith(">")
        value = target[1:-1] if angle_wrapped else target
        parsed = urlsplit(value)
        if parsed.scheme or parsed.netloc or value.startswith("#"):
            return target
        path = posixpath.normpath(parsed.path.lstrip("/"))
        if path in ("", ".") or path == ".." or path.startswith("../"):
            raise ReleaseError(f"Guide link escapes the repository: {value}")
        absolute = urlunsplit((
            "https", "github.com",
            urlsplit(repository_url).path.rstrip("/") + "/blob/" + commit + "/" + quote(path, safe="/%"),
            parsed.query, parsed.fragment,
        ))
        return f"<{absolute}>" if angle_wrapped else absolute

    # Inline links/images, including optional quoted titles.
    markdown = re.sub(
        r"(!?\[[^\]\n]*\]\()(<[^>\n]+>|[^\s)]+)([^)\n]*\))",
        lambda match: match.group(1) + target_url(match.group(2)) + match.group(3),
        markdown,
    )
    # Reference-style link definitions.
    return re.sub(
        r"(?m)^(\s{0,3}\[[^\]\n]+\]:\s*)(<[^>\n]+>|\S+)(.*)$",
        lambda match: match.group(1) + target_url(match.group(2)) + match.group(3),
        markdown,
    )


def _start_here(language: str) -> bytes:
    if language == "en":
        text = """# Start CalcLens

This source package starts in English. It requires Python 3.12 or 3.13 and installed
dependencies; it is not a standalone executable.
Installation command examples in the guide use Python 3.12.

1. Read [the English guide](README.en.md) for installation and scientific limits.
2. After installing its dependencies, run `python run_app.py` from this folder.
3. Open the local address printed in the terminal. The server listens only on
   `127.0.0.1`. Use `python run_app.py --language ko` to override this default.

The same calculation code is included in both language packages. Your uploaded
CIF stays on the machine running the app. Stability and vacuum convergence are
not established by a geometric report. See [the license](LICENSE) before reuse.
"""
    else:
        text = """# CalcLens 시작하기

이 소스 패키지는 한국어로 시작합니다. Python 3.12 또는 3.13과 의존성 설치가 필요하며,
독립 실행 파일이 아닙니다.
안내 문서의 설치 명령 예시는 Python 3.12를 사용합니다.

1. [한국어 안내](README.ko.md)에서 설치 순서와 과학적 한계를 확인하세요.
2. 의존성을 설치한 다음 이 폴더에서 `python run_app.py`를 실행하세요.
3. 터미널에 표시된 로컬 주소를 여세요. 서버는 `127.0.0.1`에서만 연결을 받습니다.
   영어로 시작하려면 `python run_app.py --language en`을 사용하세요.

두 언어 패키지는 같은 계산 코드를 사용합니다. 입력한 CIF는 앱을 실행하는
컴퓨터에서 처리됩니다. 기하 검사로 구조 안정성이나 진공 수렴을 판단할 수 없습니다.
재사용 전에 [라이선스](LICENSE)를 확인하세요.
"""
    return text.encode("utf-8")


def _zip_bytes(folder: str, files: dict[str, tuple[bytes, int]]) -> bytes:
    output = io.BytesIO()
    with zipfile.ZipFile(output, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=9) as archive:
        for path in sorted(files):
            content, mode = files[path]
            info = zipfile.ZipInfo(f"{folder}/{path}", date_time=(1980, 1, 1, 0, 0, 0))
            info.create_system = 3
            info.external_attr = mode << 16
            info.compress_type = zipfile.ZIP_DEFLATED
            archive.writestr(info, content, compresslevel=9)
    return output.getvalue()


def build_release(repo: Path, output: Path | None = None) -> list[Path]:
    """Write language assets only after all committed-source checks succeed."""
    repo = repo.resolve()
    commit, files = committed_files(repo)
    try:
        metadata = tomllib.loads(files["pyproject.toml"][0].decode("utf-8"))["project"]
        version = metadata["version"]
        repository_url = metadata["urls"]["Repository"]
    except (KeyError, TypeError, UnicodeError, tomllib.TOMLDecodeError):
        raise ReleaseError("pyproject.toml must declare project.version and project.urls.Repository.") from None
    if not isinstance(version, str) or not re.fullmatch(r"\d+\.\d+\.\d+(?:[-+][A-Za-z0-9.-]+)?", version):
        raise ReleaseError("Version must be a safe major.minor.patch release identifier.")
    if isinstance(repository_url, str):
        repository_url = repository_url.rstrip("/")
    if not isinstance(repository_url, str) or not re.fullmatch(r"https://github\.com/[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+", repository_url):
        raise ReleaseError("Repository must be an HTTPS GitHub owner/repository URL.")
    artifacts: dict[str, bytes] = {}
    for language in ("en", "ko"):
        folder = f"calclens-{version}-{language}"
        localized = dict(files)
        localized["README.md"] = files[f"README.{language}.md"]
        localized["DEFAULT_LANGUAGE.txt"] = ((language + "\n").encode("ascii"), 0o100644)
        localized["START_HERE.md"] = (_start_here(language), 0o100644)
        info = {"version": version, "source_commit": commit, "language": language}
        localized["BUILD_INFO.json"] = ((json.dumps(info, indent=2, sort_keys=True) + "\n").encode(), 0o100644)
        artifacts[folder + ".zip"] = _zip_bytes(folder, localized)
        guide = files[f"README.{language}.md"][0].decode("utf-8")
        artifacts[f"CalcLens-Guide.{language}.md"] = absolute_guide_links(guide, repository_url, commit).encode("utf-8")
    checksums = "".join(f"{hashlib.sha256(content).hexdigest()}  {name}\n" for name, content in sorted(artifacts.items()))
    artifacts["SHA256SUMS.txt"] = checksums.encode("ascii")
    destination = (output or repo / "dist").resolve()
    if destination == repo or repo in destination.parents and ".git" in destination.relative_to(repo).parts:
        raise ReleaseError("Output must be a distribution directory, not the repository root or .git.")
    destination.mkdir(parents=True, exist_ok=True)
    for name in artifacts:
        path = destination / name
        if path.is_symlink() or path.exists() and not path.is_file():
            raise ReleaseError(f"Refusing to replace a symlink or non-file output: {path}")
    paths = []
    for name, content in sorted(artifacts.items()):
        path = destination / name
        with tempfile.NamedTemporaryFile(dir=destination, prefix=".calclens-", delete=False) as handle:
            temporary = Path(handle.name)
            handle.write(content)
        try:
            temporary.replace(path)
        finally:
            temporary.unlink(missing_ok=True)
        paths.append(path)
    return paths


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, help="Output directory (default: dist/).")
    args = parser.parse_args(argv)
    try:
        paths = build_release(Path(__file__).resolve().parents[1], args.output)
    except (ReleaseError, OSError) as error:
        parser.exit(1, f"Release not built: {error}\n")
    for path in paths:
        print(path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
