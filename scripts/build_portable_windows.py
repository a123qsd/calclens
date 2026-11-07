"""Build a self-contained x64 Windows GUI from official CPython and locked Windows wheels.

The build host needs Python, pip, packaging, and makensis. No Windows VM is
required to assemble the executable. Validation of a built executable is separate.
"""
from __future__ import annotations

import argparse
import base64
from hashlib import sha256
from email.parser import BytesParser
import json
from pathlib import Path
import re
import shutil
import stat
import struct
import subprocess
import sys
import tempfile
import urllib.request
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
            parts = Path(entry.filename).parts
            if ('..' in parts or Path(entry.filename).is_absolute() or '\\' in entry.filename
                    or ':' in entry.filename or stat.S_ISLNK(entry.external_attr >> 16)):
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
    (runtime/'desktop_start.py').write_text('from slab_preflight.desktop_entry import main\nraise SystemExit(main())\n')
    docs = runtime/'docs'
    if docs.exists():
        shutil.rmtree(docs)
    docs.mkdir()
    for path in (ROOT/'docs').glob('*.md'):
        shutil.copyfile(path,docs/path.name)
    (runtime/'WINDOWS-RUNTIME-NOTICES.txt').write_text(
        'CPython license: LICENSE.txt. Application: LICENSE and THIRD_PARTY_NOTICES.md.\n'
        'Unmodified wheel licenses remain in Lib/site-packages/*.dist-info/licenses.\n'
        'Qt/PySide6 libraries are dynamically loaded unmodified official wheels.\n'
        'Qt source/licenses: https://www.qt.io/licensing/ and https://download.qt.io/\n'
        'PySide6 source: https://code.qt.io/cgit/pyside/pyside-setup.git/\n'
        'Gaussian reference data: examples/research_cases/gaussian_reference/LICENSE.cclib.\n'
        'Wine test system DLLs are not part of this distribution.\n')


def payload_files(runtime):
    return {p.relative_to(runtime).as_posix():sha256(p.read_bytes()).hexdigest()
            for p in sorted(runtime.rglob('*')) if p.is_file() and p.name!='DESKTOP-BUILD.json'
            and '__pycache__' not in p.parts and p.suffix!='.pyc'}


def package(cache, runtime, output, makensis):
    output = output.resolve()
    output.parent.mkdir(parents=True, exist_ok=True)
    files = payload_files(runtime)
    if any(Path(name).name.lower() in ('icuuc.dll','icuin.dll','icudt.dll') for name in files):
        raise ValueError('Test-prefix Windows system ICU DLLs must never enter the payload.')
    source_files = {name:value for name,value in files.items() if name.startswith(('src/','examples/','docs/'))}
    record = {'schema_version':1,'application_version':'0.9.0',
              'runtime':json.loads((runtime/'DESKTOP-RUNTIME.json').read_bytes()),
              'launcher':'NSIS Unicode x86 self-extractor; application runtime AMD64',
              'builder_sha256':sha256(Path(__file__).read_bytes()).hexdigest(),
              'makensis_sha256':sha256(makensis.read_bytes()).hexdigest(),
              'launcher_icon_sha256':sha256((runtime/'CalcLens.ico').read_bytes()).hexdigest(),
              'source_tree_sha256':sha256(json.dumps(source_files,sort_keys=True).encode()).hexdigest(),
              'files':files}
    (runtime/'DESKTOP-BUILD.json').write_text(json.dumps(record,indent=2,sort_keys=True)+'\n')
    # NSIS inserts files under the program's own temporary directory. Every invocation
    # starts the bundled pythonw process and waits for its Qt event loop to finish.
    def quoted(path):
        return str(path).replace('$','$$').replace('"','$\\"')
    script = cache/'CalcLens-native.nsi'
    script.write_text(f'''Unicode true
RequestExecutionLevel user
Name "CalcLens"
Icon "{quoted(runtime/'CalcLens.ico')}"
OutFile "{quoted(output)}"
SetCompressor /SOLID lzma
SetCompressorDictSize 48
SilentInstall silent
AutoCloseWindow true
!include FileFunc.nsh
Section
  InitPluginsDir
  SetOutPath "$PLUGINSDIR\\CalcLens"
  File /r "{quoted(runtime)}/*"
  ${{GetParameters}} $0
  ClearErrors
  ExecWait '"$PLUGINSDIR\\CalcLens\\pythonw.exe" -I -B "$PLUGINSDIR\\CalcLens\\desktop_start.py" $0' $1
  IfErrors 0 +3
    MessageBox MB_ICONSTOP "CalcLens could not start its desktop runtime."
    StrCpy $1 1
  SetErrorLevel $1
SectionEnd
''',encoding='utf-8-sig')
    subprocess.run([str(makensis),'-V2',str(script)],check=True)
    if payload_files(runtime) != files:
        raise ValueError('Payload changed during packaging.')
    summary = {key:value for key,value in record.items() if key!='files'}
    summary.update(executable=output.name,sha256=sha256(output.read_bytes()).hexdigest(),
                   size_bytes=output.stat().st_size,launcher_pe_architecture=pe_architecture(output),
                   payload_manifest_sha256=sha256((runtime/'DESKTOP-BUILD.json').read_bytes()).hexdigest(),
                   validation='Build integrity only; native smoke must test this exact EXE separately.')
    output.with_suffix('.exe.manifest.json').write_text(json.dumps(summary,indent=2,sort_keys=True)+'\n')
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
    args=parser.parse_args()
    cache=args.cache.resolve()
    runtime=stage(cache,offline=args.use_staged_runtime)
    collect_source(runtime)
    if not args.stage_only:
        if not args.output or not args.makensis:
            parser.error('--output and --makensis are required to build the executable')
        package(cache,runtime,args.output,args.makensis)


if __name__=='__main__':
    main()
