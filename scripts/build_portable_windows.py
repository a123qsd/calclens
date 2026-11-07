"""Build an extract-once Windows folder ZIP from CPython and locked Windows wheels.

The build host needs Python, pip, packaging, and makensis. No Windows VM is
required to assemble the executable. Validation of a built executable is separate.
"""
from __future__ import annotations

import argparse
import base64
from hashlib import sha256
from email.parser import BytesParser
import json
from pathlib import Path, PurePosixPath
import re
import shutil
import stat
import struct
import subprocess
import sys
import tempfile
import tomllib
import urllib.request
from urllib.parse import unquote, urlsplit
import zipfile

from packaging.markers import default_environment
from packaging.requirements import Requirement
from packaging.specifiers import SpecifierSet
from packaging.tags import compatible_tags, cpython_tags
from packaging.utils import canonicalize_name, parse_wheel_filename
from packaging.version import Version

ROOT = Path(__file__).resolve().parents[1]
EMBED = 'https://www.python.org/ftp/python/3.13.17/python-3.13.17-embed-amd64.zip'
EMBED_SHA = base64.b64decode('njUxm//tq4s2rUTY83fLTxczvOwlegttBNlPAUht2zg=').hex()


def target_environment():
    return dict(default_environment(), sys_platform='win32', os_name='nt', platform_system='Windows',
                platform_machine='AMD64', platform_release='10', platform_version='10.0',
                implementation_name='cpython', implementation_version='3.13.17',
                platform_python_implementation='CPython', python_version='3.13',
                python_full_version='3.13.17', extra='')


def read_locks(root=ROOT):
    text = (root/'requirements.lock').read_text() + '\n' + (root/'packaging/desktop/requirements.lock').read_text()
    locks = {}
    for block in re.split(r'\n(?=[A-Za-z0-9_.-]+==)', text):
        match = re.search(r'^([A-Za-z0-9_.-]+)==([^\s;]+)([^\n]*)', block, re.M)
        if match:
            requirement = Requirement(match.group().rstrip(' \\'))
            if requirement.marker and not requirement.marker.evaluate(target_environment()):
                continue
            name = canonicalize_name(match[1])
            hashes = set(re.findall(r'--hash=sha256:([0-9a-f]{64})', block[match.end():]))
            record = {'version': Version(match[2]), 'hashes': hashes}
            if not hashes or (name in locks and record != locks[name]):
                raise ValueError(f'Missing/conflicting hash lock: {name}')
            locks[name] = record
    return locks


def locked_line(name, record):
    return f"{name}=={record['version']} " + ' '.join(
        '--hash=sha256:' + value for value in sorted(record['hashes']))


def compatible_wheel(path):
    try:
        name, version, _, tags = parse_wheel_filename(path.name)
    except ValueError:
        return None
    accepted = set(cpython_tags((3, 13), abis=['cp313'], platforms=['win_amd64']))
    accepted.update(compatible_tags((3, 13), interpreter='cp313', platforms=['win_amd64']))
    return (canonicalize_name(name), version) if tags & accepted else None


def choose_wheel(directory, name, lock):
    candidates = []
    for path in sorted(directory.glob('*.whl')):
        if compatible_wheel(path) != (name, lock['version']):
            continue
        if path.is_symlink() or sha256(path.read_bytes()).hexdigest() not in lock['hashes']:
            raise ValueError(f'Cached wheel failed repository hash lock: {path.name}')
        candidates.append(path)
    if len(candidates) > 1:
        raise ValueError(f'Ambiguous compatible cached wheels for {name}.')
    return candidates[0] if candidates else None


def resolve_wheels(cache, offline=False, root=ROOT):
    """Resolve from Windows wheel METADATA, never the host's installed metadata."""
    locks = read_locks(root)
    directory = cache/'wheels'
    directory.mkdir(exist_ok=True)
    pending = ['ase', 'numpy', 'pyside6-essentials', 'pillow']
    selected = {}
    while pending:
        name = canonicalize_name(pending.pop())
        if name in selected:
            continue
        if name not in locks:
            raise ValueError(f'Missing runtime package lock: {name}')
        path = choose_wheel(directory, name, locks[name])
        if path is None:
            if offline:
                raise ValueError(f'Missing verified offline Windows wheel: {name}')
            request = cache/'download-request.lock'
            request.write_text(locked_line(name, locks[name])+'\n')
            subprocess.run([sys.executable, '-m', 'pip', 'download', '--disable-pip-version-check',
                            '--no-deps', '--require-hashes', '--only-binary=:all:', '--platform',
                            'win_amd64', '--implementation', 'cp', '--python-version', '3.13',
                            '--abi', 'cp313', '--dest', str(directory), '-r', str(request)], check=True)
            path = choose_wheel(directory, name, locks[name])
            if path is None:
                raise ValueError(f'No compatible verified wheel: {name}')
        with zipfile.ZipFile(path) as archive:
            names = [n for n in archive.namelist() if n.endswith('.dist-info/METADATA')]
            if len(names) != 1:
                raise ValueError(f'No unique wheel METADATA: {path.name}')
            metadata = BytesParser().parsebytes(archive.read(names[0]))
        if compatible_wheel(path) != (canonicalize_name(metadata['Name']), Version(metadata['Version'])):
            raise ValueError('Wheel filename/METADATA identity mismatch.')
        if metadata.get('Requires-Python') and Version('3.13.17') not in SpecifierSet(metadata['Requires-Python']):
            raise ValueError(f'Wheel does not support the target Python version: {path.name}')
        selected[name] = path
        for text in metadata.get_all('Requires-Dist', []):
            requirement = Requirement(text)
            if requirement.marker and not requirement.marker.evaluate(target_environment()):
                continue
            dependency = canonicalize_name(requirement.name)
            if (requirement.extras or dependency not in locks
                    or locks[dependency]['version'] not in requirement.specifier):
                raise ValueError(f'Unsupported or unsatisfied locked dependency: {text}')
            pending.append(dependency)
    (cache/'windows-runtime.lock').write_text('\n'.join(
        locked_line(name, locks[name]) for name in sorted(selected))+'\n')
    return [selected[name] for name in sorted(selected)]


def pe_architecture(path):
    data = path.read_bytes()
    if len(data) < 64 or data[:2] != b'MZ':
        raise ValueError('Not a PE executable.')
    offset = struct.unpack_from('<I', data, 60)[0]
    if len(data) < offset+6 or data[offset:offset+4] != b'PE\0\0':
        raise ValueError('Invalid PE executable.')
    return {0x8664: 'AMD64', 0x14c: 'I386', 0xaa64: 'ARM64'}.get(
        struct.unpack_from('<H', data, offset+4)[0], 'unknown')


def extract_archive(path, destination, wheel=False):
    with zipfile.ZipFile(path) as archive:
        seen = set()
        for entry in archive.infolist():
            name = entry.orig_filename
            member = PurePosixPath(name)
            parts = member.parts
            if (not parts or member.is_absolute() or '..' in parts or '\\' in name
                    or ':' in name or '\0' in name or stat.S_ISLNK(entry.external_attr >> 16)):
                raise ValueError('Unsafe archive member.')
            if entry.is_dir():
                continue
            if wheel and parts[0].endswith('.data'):
                if len(parts) < 3 or parts[1] not in ('purelib', 'platlib'):
                    continue
                parts = parts[2:]
            key = '/'.join(parts).casefold()
            target = destination.joinpath(*parts)
            if key in seen or target.exists():
                raise ValueError('Duplicate/colliding archive destination.')
            seen.add(key)
            target.parent.mkdir(parents=True, exist_ok=True)
            with archive.open(entry) as source, target.open('wb') as output:
                shutil.copyfileobj(source, output)


def stage(cache: Path, offline=False) -> Path:
    cache.mkdir(parents=True, exist_ok=True)
    runtime = cache/'payload'
    if runtime.is_symlink():
        raise ValueError('Payload must not be a symlink.')
    embed = cache/'python-embed.zip'
    if not embed.is_file() or sha256(embed.read_bytes()).hexdigest() != EMBED_SHA:
        if offline:
            raise ValueError('Offline CPython archive is missing or has a bad hash.')
        with urllib.request.urlopen(EMBED, timeout=45) as src:
            binary = src.read(30_000_000)
        if sha256(binary).hexdigest() != EMBED_SHA:
            raise RuntimeError('Embedded runtime does not match official CPython release digest.')
        embed.write_bytes(binary)
    wheels = resolve_wheels(cache, offline=offline)
    with tempfile.TemporaryDirectory(prefix='.payload-', dir=cache) as temporary:
        fresh = Path(temporary)/'runtime'
        fresh.mkdir()
        extract_archive(embed, fresh)
        packages = fresh/'Lib'/'site-packages'
        packages.mkdir(parents=True)
        for item in wheels:
            extract_archive(item, packages, wheel=True)
        (fresh/'python313._pth').write_text('python313.zip\n.\nsrc\nLib/site-packages\nimport site\n')
        for name in ('python.exe', 'pythonw.exe', 'python313.dll'):
            if pe_architecture(fresh/name) != 'AMD64':
                raise ValueError('Bundled interpreter is not Windows AMD64.')
        identities = [{'wheel':item.name,'sha256':sha256(item.read_bytes()).hexdigest()} for item in wheels]
        (fresh/'DESKTOP-RUNTIME.json').write_text(json.dumps({
            'schema_version':2, 'python':EMBED, 'python_sha256':EMBED_SHA,
            'runtime_architecture':'AMD64', 'dependency_resolution':'Windows wheel METADATA',
            'locks':{str(p.relative_to(ROOT)):sha256(p.read_bytes()).hexdigest() for p in
                     [ROOT/'requirements.lock',ROOT/'packaging/desktop/requirements.lock']},
            'wheels':identities},indent=2))
        # Only the builder-owned payload is replaced; stale extracted files never survive.
        if runtime.exists():
            shutil.rmtree(runtime)
        fresh.rename(runtime)
    return runtime


def collect_documentation(runtime):
    """Keep root guides and their explicit image/verification references only."""
    source = ROOT/'docs'
    destination = runtime/'docs'
    if destination.exists():
        shutil.rmtree(destination)
    destination.mkdir()
    selected = {path.relative_to(source) for path in source.glob('*.md') if path.is_file()}
    for relative in tuple(selected):
        guide = source/relative
        if guide.is_symlink():
            raise ValueError('Bundled documentation must not contain symlinks.')
        for link in re.findall(r'\]\(([^)\n]+)\)', guide.read_text(encoding='utf-8')):
            link = link.strip()
            link = link[1:link.index('>')] if link.startswith('<') and '>' in link else link.split()[0]
            parsed = urlsplit(link)
            if parsed.scheme or parsed.netloc:
                continue
            target = Path(unquote(parsed.path))
            if not target.parts or target.parts[0] not in ('assets', 'verification'):
                continue
            expected = {'.png', '.jpg', '.jpeg', '.svg', '.gif', '.webm'} if target.parts[0] == 'assets' else {'.json', '.csv', '.md'}
            candidate = source/target
            try:
                resolved = candidate.resolve().relative_to(source.resolve())
            except ValueError:
                raise ValueError('Documentation reference escapes its source directory.') from None
            if (not resolved.parts or resolved.parts[0] != target.parts[0]
                    or candidate.suffix.lower() not in expected or not candidate.is_file()
                    or any(part.is_symlink() for part in [candidate, *candidate.parents]
                           if part != source.parent)):
                raise ValueError(f'Unsafe or missing documentation reference: {target}')
            selected.add(target)
    for relative in sorted(selected):
        target = destination/relative
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(source/relative, target)


def collect_source(runtime):
    for name in ('src/slab_preflight','examples'):
        dest = runtime/name
        # The staging directory belongs exclusively to this builder, never to an open project.
        if dest.is_dir():
            shutil.rmtree(dest)
        shutil.copytree(ROOT/name, dest, ignore=shutil.ignore_patterns('__pycache__','*.pyc','*.so','.DS_Store','calclens-metal-arm64'))
    for name in ('LICENSE','THIRD_PARTY_NOTICES.md'):
        shutil.copyfile(ROOT/name,runtime/name)
    shutil.copyfile(ROOT/'packaging/desktop/CalcLens.ico',runtime/'CalcLens.ico')
    shutil.copyfile(ROOT/'packaging/desktop/windows_bootstrap.py', runtime/'desktop_start.py')
    collect_documentation(runtime)
    (runtime/'WINDOWS-RUNTIME-NOTICES.txt').write_text(
        'CPython license: LICENSE.txt. Application: LICENSE and THIRD_PARTY_NOTICES.md.\n'
        'Unmodified wheel licenses remain in Lib/site-packages/*.dist-info/licenses.\n'
        'Qt/PySide6 libraries are dynamically loaded unmodified official wheels.\n'
        'Qt source/licenses: https://www.qt.io/licensing/ and https://download.qt.io/\n'
        'PySide6 source: https://code.qt.io/cgit/pyside/pyside-setup.git/\n'
        'Gaussian reference data: examples/research_cases/gaussian_reference/LICENSE.cclib.\n'
        'VASP reference data: examples/research_cases/vasp_reference/ASE-LICENSE.txt.\n'
        'Wine test system DLLs are not part of this distribution.\n')


def payload_files(runtime):
    return {p.relative_to(runtime).as_posix():sha256(p.read_bytes()).hexdigest()
            for p in sorted(runtime.rglob('*')) if p.is_file() and p.name!='DESKTOP-BUILD.json'
            and '__pycache__' not in p.parts and p.suffix!='.pyc'}


def package(cache, runtime, output, makensis, *, distribution='folder'):
    """Folder mode ships a tiny launcher beside runtime, never a runtime cache.

    Self-extracting mode is explicit for comparison/legacy use, not the default.
    """
    if distribution not in ('folder', 'self-extracting'):
        raise ValueError('Unknown Windows distribution format.')
    output = output.resolve()
    output.parent.mkdir(parents=True, exist_ok=True)
    files = payload_files(runtime)
    if any(Path(name).name.lower() in ('icuuc.dll','icuin.dll','icudt.dll') for name in files):
        raise ValueError('Test-prefix Windows system ICU DLLs must never enter the payload.')
    source_files = {name:value for name,value in files.items() if name.startswith(('src/','examples/','docs/'))}
    version = tomllib.loads((ROOT/'pyproject.toml').read_text())['project']['version']
    folder = distribution == 'folder'
    record = {'schema_version':2,'application_version':version,
              'runtime':json.loads((runtime/'DESKTOP-RUNTIME.json').read_bytes()),
              'distribution':distribution,
              'launcher':('NSIS Unicode x86 folder launcher; no per-launch runtime extraction'
                          if folder else 'NSIS Unicode x86 per-launch self-extractor'),
              'builder_sha256':sha256(Path(__file__).read_bytes()).hexdigest(),
              'makensis_sha256':sha256(makensis.read_bytes()).hexdigest(),
              'launcher_icon_sha256':sha256((runtime/'CalcLens.ico').read_bytes()).hexdigest(),
              'source_tree_sha256':sha256(json.dumps(source_files,sort_keys=True).encode()).hexdigest(),
              'files':files}
    (runtime/'DESKTOP-BUILD.json').write_text(json.dumps(record,indent=2,sort_keys=True)+'\n')
    def quoted(path):
        return str(path).replace('$','$$').replace('"','$\\"')
    launcher = cache/'CalcLens.exe' if folder else output
    location = '$EXEDIR\\runtime' if folder else '$PLUGINSDIR\\CalcLens'
    extraction = '' if folder else f'''  InitPluginsDir
  System::Call 'kernel32::GetTickCount() i.r2'
  SetOutPath "$PLUGINSDIR\\CalcLens"
  File /r "{quoted(runtime)}/*"
  System::Call 'kernel32::GetTickCount() i.r3'
  IntOp $3 $3 - $2
  System::Call 'kernel32::SetEnvironmentVariableW(w "CALCLENS_RUNTIME_UNPACK_MS", w r3)'
'''
    if folder:
        extraction = '''  System::Call 'kernel32::SetEnvironmentVariableW(w "CALCLENS_RUNTIME_UNPACK_MS", w "0")'
'''
    script = cache/'CalcLens-native.nsi'
    script.write_text(f'''Unicode true
RequestExecutionLevel user
Name "CalcLens"
Icon "{quoted(runtime/'CalcLens.ico')}"
OutFile "{quoted(launcher)}"
SetCompressor /SOLID lzma
SetCompressorDictSize 48
SilentInstall silent
AutoCloseWindow true
!include FileFunc.nsh
Section
  CreateDirectory "$LOCALAPPDATA\\CalcLens\\logs"
  System::Call 'kernel32::GetCurrentProcessId() i.r4'
  ClearErrors
  FileOpen $5 "$LOCALAPPDATA\\CalcLens\\logs\\launcher-$4.log" w
  IfErrors 0 log_opened
    CreateDirectory "$TEMP\\CalcLens-logs"
    FileOpen $5 "$TEMP\\CalcLens-logs\\launcher-$4.log" w
  log_opened:
    FileWrite $5 "CalcLens launcher started. Runtime format: {distribution}.$\\r$\\n"
{extraction}  IfFileExists "{location}\\pythonw.exe" 0 runtime_missing
  IfFileExists "{location}\\python313.dll" 0 runtime_missing
  IfFileExists "{location}\\python313.zip" 0 runtime_missing
  IfFileExists "{location}\\desktop_start.py" runtime_present runtime_missing
  runtime_missing:
    FileWrite $5 "A required runtime file is missing. Extract the complete ZIP.$\\r$\\n"
    FileClose $5
    MessageBox MB_ICONSTOP "CalcLens runtime is missing. Extract the entire ZIP before running CalcLens.exe.$\\r$\\nZIP 전체를 먼저 풀어 주세요."
    SetErrorLevel 1
    Quit
  runtime_present:
  ${{GetParameters}} $0
  ClearErrors
  ExecWait '"{location}\\pythonw.exe" -I -B "{location}\\desktop_start.py" $0' $1
  IfErrors runtime_failed runtime_finished
  runtime_failed:
    FileWrite $5 "Windows could not create the Python process.$\\r$\\n"
    MessageBox MB_ICONSTOP "CalcLens could not start Python. Extract the entire ZIP to a new folder.$\\r$\\nPython을 시작하지 못했습니다. ZIP 전체를 새 폴더에 다시 풀어 주세요."
    StrCpy $1 1
    Goto finished
  runtime_finished:
    FileWrite $5 "Python exited with code $1.$\\r$\\n"
    StrCmp $1 0 finished
    StrCmp $1 73 diagnostic_shown
    MessageBox MB_ICONSTOP "CalcLens stopped with error $1. Extract the complete ZIP to a new folder if runtime files are damaged.$\\r$\\nDiagnostics: $LOCALAPPDATA\\CalcLens\\logs (fallback: $TEMP\\CalcLens-logs)$\\r$\\n앱이 오류로 종료했습니다. 진단 폴더를 확인해 주세요."
    Goto finished
  diagnostic_shown:
    StrCpy $1 1
  finished:
    FileClose $5
  SetErrorLevel $1
SectionEnd
''',encoding='utf-8-sig')
    subprocess.run([str(makensis),'-V2',str(script)],check=True)
    if payload_files(runtime) != files:
        raise ValueError('Payload changed during packaging.')
    if folder:
        top = f'CalcLens-{version}-Windows-x64'
        with tempfile.TemporaryDirectory(prefix='.windows-zip-', dir=output.parent) as temporary:
            archive_path = Path(temporary)/output.name
            with zipfile.ZipFile(archive_path, 'w', zipfile.ZIP_DEFLATED, compresslevel=6) as archive:
                archive.write(launcher, f'{top}/CalcLens.exe')
                archive.writestr(f'{top}/START-HERE.txt',
                    'Extract the entire ZIP once, then open CalcLens.exe. Keep runtime next to it.\r\n'
                    'ZIP 전체를 한 번 풀고 CalcLens.exe를 실행하세요. runtime 폴더를 함께 보관하세요.\r\n'
                    'No administrator rights or separate Python install are needed.\r\n'
                    'Diagnostic logs: %LOCALAPPDATA%\\CalcLens\\logs\r\n')
                for path in sorted(runtime.rglob('*')):
                    if path.is_file() and '__pycache__' not in path.parts and path.suffix != '.pyc':
                        archive.write(path, f'{top}/runtime/{path.relative_to(runtime).as_posix()}')
            if payload_files(runtime) != files:
                raise ValueError('Payload changed during archive creation.')
            archive_path.replace(output)
    summary = {key:value for key,value in record.items() if key!='files'}
    summary.update(executable=output.name,sha256=sha256(output.read_bytes()).hexdigest(),
                   size_bytes=output.stat().st_size,launcher_pe_architecture=pe_architecture(launcher),
                   launcher_sha256=sha256(launcher.read_bytes()).hexdigest(),
                   payload_manifest_sha256=sha256((runtime/'DESKTOP-BUILD.json').read_bytes()).hexdigest(),
                   validation='Build integrity only; test the extracted exact launcher separately.')
    output.with_suffix(output.suffix+'.manifest.json').write_text(json.dumps(summary,indent=2,sort_keys=True)+'\n')
    print(json.dumps(summary,indent=2),flush=True)
    return summary


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--cache',type=Path,required=True)
    parser.add_argument('--stage-only',action='store_true')
    parser.add_argument('--use-staged-runtime',action='store_true',
                        help='Reconstruct cleanly from verified cached archives without network.')
    parser.add_argument('--output',type=Path)
    parser.add_argument('--makensis',type=Path)
    parser.add_argument('--format', choices=('folder', 'self-extracting'), default='folder',
                        help='Default folder ZIP is extracted once; legacy EXE unpacks every run.')
    args=parser.parse_args()
    cache=args.cache.resolve()
    runtime=stage(cache,offline=args.use_staged_runtime)
    collect_source(runtime)
    if not args.stage_only:
        if not args.output or not args.makensis:
            parser.error('--output and --makensis are required to build the executable')
        required_suffix = '.zip' if args.format == 'folder' else '.exe'
        if args.output.suffix.lower() != required_suffix:
            parser.error(f'--format {args.format} requires an {required_suffix} output')
        package(cache,runtime,args.output,args.makensis,distribution=args.format)


if __name__=='__main__':
    main()
