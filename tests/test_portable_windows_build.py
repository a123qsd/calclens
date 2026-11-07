"""Verify cross-build inputs without running or downloading a Windows runtime."""
from hashlib import sha256
import importlib.util
import json
from pathlib import Path
import struct
import tomllib
import zipfile

import pytest
from packaging.version import Version

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location('portable', ROOT/'scripts/build_portable_windows.py')
BUILD = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(BUILD)


def fake_pe(machine=0x8664):
    data = bytearray(128)
    data[:2] = b'MZ'
    struct.pack_into('<I',data,60,64)
    data[64:68] = b'PE\0\0'
    struct.pack_into('<H',data,68,machine)
    return bytes(data)


def wheel(tmp_path, name='example-1.0-cp313-cp313-win_amd64.whl', entries=None):
    path = tmp_path/name
    with zipfile.ZipFile(path,'w') as archive:
        for key,value in (entries or {'example.py':b'value = 1\n'}).items():
            info = zipfile.ZipInfo(key)
            # Keep malformed names verbatim even when the test runs on Windows.
            info.filename = key
            archive.writestr(info,value)
    return path


def test_windows_marker_environment_is_independent_of_build_host():
    environment = BUILD.target_environment()
    assert environment['sys_platform']=='win32'
    assert environment['platform_machine']=='AMD64'
    assert environment['python_full_version']=='3.13.17'
    assert environment['implementation_name']=='cpython'


@pytest.mark.parametrize('name,expected',[
    ('example-1.0-cp313-cp313-win_amd64.whl',True),
    ('example-1.0-cp310-abi3-win_amd64.whl',True),
    ('example-1.0-py3-none-any.whl',True),
    ('example-1.0-cp313-cp313-win32.whl',False),
    ('example-1.0-cp313-cp313-macosx_14_0_arm64.whl',False),
    ('example-1.0-cp313-cp313-manylinux_2_28_x86_64.whl',False),
])
def test_target_tags_accept_only_windows_amd64_or_pure_python(name,expected):
    assert (BUILD.compatible_wheel(Path(name)) is not None)==expected


def test_cached_wheel_is_rehashed_and_old_other_platform_files_are_ignored(tmp_path):
    valid=wheel(tmp_path)
    wheel(tmp_path,'example-0.9-py3-none-any.whl')
    wheel(tmp_path,'example-1.0-cp313-cp313-macosx_14_0_arm64.whl')
    lock={'version':Version('1.0'),'hashes':{sha256(valid.read_bytes()).hexdigest()}}
    assert BUILD.choose_wheel(tmp_path,'example',lock)==valid
    valid.write_bytes(valid.read_bytes()+b'changed')
    with pytest.raises(ValueError,match='hash lock'):
        BUILD.choose_wheel(tmp_path,'example',lock)


@pytest.mark.parametrize('member',['../outside.py','/outside.py','C:/outside.py','nested\\outside.py'])
def test_archive_paths_cannot_escape_payload(tmp_path,member):
    archive=wheel(tmp_path,entries={member:b'bad'})
    with pytest.raises(ValueError,match='Unsafe'):
        BUILD.extract_archive(archive,tmp_path/'payload')
    assert not (tmp_path/'outside.py').exists()


def test_archive_keeps_license_and_maps_purelib_without_console_scripts(tmp_path):
    archive=wheel(tmp_path,entries={'example.py':b'code',
        'example-1.0.dist-info/licenses/LICENSE':b'license',
        'example-1.0.data/purelib/data.py':b'data',
        'example-1.0.data/scripts/unused.exe':b'unused'})
    destination=tmp_path/'payload'
    BUILD.extract_archive(archive,destination,wheel=True)
    assert (destination/'example-1.0.dist-info/licenses/LICENSE').read_bytes()==b'license'
    assert (destination/'data.py').read_bytes()==b'data'
    assert not list(destination.rglob('*.exe'))


def test_case_collisions_and_symlinks_are_not_silently_overwritten(tmp_path):
    archive=wheel(tmp_path,entries={'same.py':b'first','SAME.py':b'second'})
    with pytest.raises(ValueError,match='colliding'):
        BUILD.extract_archive(archive,tmp_path/'payload')
    link=tmp_path/'link.whl'
    with zipfile.ZipFile(link,'w') as stream:
        item=zipfile.ZipInfo('link')
        item.external_attr=0o120777<<16
        stream.writestr(item,'outside')
    with pytest.raises(ValueError,match='Unsafe'):
        BUILD.extract_archive(link,tmp_path/'second')


@pytest.mark.parametrize('machine,expected',[(0x8664,'AMD64'),(0x14c,'I386'),(0xaa64,'ARM64')])
def test_pe_architecture_is_observed_instead_of_inferred_from_filename(tmp_path,machine,expected):
    path=tmp_path/'misleading-x64.exe'
    path.write_bytes(fake_pe(machine))
    assert BUILD.pe_architecture(path)==expected


def test_stale_extracted_runtime_is_replaced_from_verified_archives(tmp_path,monkeypatch):
    embed=tmp_path/'python-embed.zip'
    with zipfile.ZipFile(embed,'w') as archive:
        for name in ('python.exe','pythonw.exe','python313.dll'):
            archive.writestr(name,fake_pe())
    monkeypatch.setattr(BUILD,'EMBED_SHA',sha256(embed.read_bytes()).hexdigest())
    monkeypatch.setattr(BUILD,'resolve_wheels',lambda *a,**k:[])
    old=tmp_path/'payload'
    old.mkdir()
    (old/'stale-unlocked.dll').write_bytes(b'stale')
    result=BUILD.stage(tmp_path,offline=True)
    assert not (result/'stale-unlocked.dll').exists()
    assert BUILD.pe_architecture(result/'python.exe')=='AMD64'
    assert 'import site' in (result/'python313._pth').read_text()


def test_offline_build_refuses_changed_embed_archive(tmp_path):
    (tmp_path/'python-embed.zip').write_bytes(b'not the official runtime')
    with pytest.raises(ValueError,match='CPython'):
        BUILD.stage(tmp_path,offline=True)


def test_runtime_lock_has_all_native_roots_and_no_host_metadata_dependency():
    locks=BUILD.read_locks()
    assert {'ase','numpy','pyside6-essentials','pillow'}<=locks.keys()
    assert all(locks[name]['hashes'] for name in locks)
    source=(ROOT/'scripts/build_portable_windows.py').read_text()
    assert 'from importlib import metadata' not in source


def test_dependency_closure_comes_from_target_wheel_metadata_and_windows_markers(tmp_path,monkeypatch):
    directory=tmp_path/'wheels'
    directory.mkdir()
    locks={}
    for name in ('ase','numpy','pyside6-essentials','pillow','windows-only'):
        filename=name.replace('-','_')+'-1.0-py3-none-any.whl'
        metadata=f'Name: {name}\nVersion: 1.0\n'
        if name=='ase':
            metadata+='Requires-Dist: windows-only>=1; sys_platform == "win32"\n'
            metadata+='Requires-Dist: missing-macos-package; sys_platform == "darwin"\n'
        path=wheel(directory,filename,{name.replace('-','_')+'-1.0.dist-info/METADATA':metadata})
        locks[name]={'version':Version('1.0'),'hashes':{sha256(path.read_bytes()).hexdigest()}}
    monkeypatch.setattr(BUILD,'read_locks',lambda root:locks)
    resolved=BUILD.resolve_wheels(tmp_path,offline=True)
    assert len(resolved)==5
    assert any(path.name.startswith('windows_only') for path in resolved)
    assert not any('macos' in path.name for path in resolved)


def test_test_prefix_system_libraries_are_excluded_from_distribution(tmp_path):
    (tmp_path/'icuuc.dll').write_bytes(b'system test DLL')
    with pytest.raises(ValueError,match='never enter'):
        BUILD.package(tmp_path,tmp_path,tmp_path/'app.exe',tmp_path/'makensis')


def test_generated_launcher_wires_approved_icon_and_isolated_runtime_with_manifest(tmp_path,monkeypatch):
    runtime=tmp_path/'payload'
    runtime.mkdir()
    (runtime/'CalcLens.ico').write_bytes(b'synthetic icon fixture')
    (runtime/'DESKTOP-RUNTIME.json').write_text('{"runtime_architecture":"AMD64"}')
    compiler=tmp_path/'makensis'
    compiler.write_bytes(b'synthetic compiler fixture')
    output=tmp_path/'app.exe'
    monkeypatch.setattr(BUILD.subprocess,'run',lambda *a,**k:output.write_bytes(fake_pe(0x14c)))
    result=BUILD.package(tmp_path,runtime,output,compiler,distribution='self-extracting')
    text=(tmp_path/'CalcLens-native.nsi').read_text(encoding='utf-8-sig')
    icon_path = runtime / 'CalcLens.ico'
    assert f'Icon "{icon_path}"' in text
    assert '-I -B' in text and 'ExecWait' in text
    assert result['launcher_pe_architecture']=='I386'
    assert result['runtime']['runtime_architecture']=='AMD64'
    manifest=json.loads(output.with_suffix('.exe.manifest.json').read_bytes())
    assert manifest['sha256']==sha256(output.read_bytes()).hexdigest()
    assert manifest['launcher_icon_sha256']==sha256((runtime/'CalcLens.ico').read_bytes()).hexdigest()


def test_folder_launcher_never_extracts_runtime_and_archive_keeps_complete_layout(tmp_path,monkeypatch):
    runtime=tmp_path/'payload'
    runtime.mkdir()
    (runtime/'CalcLens.ico').write_bytes(b'synthetic icon fixture')
    (runtime/'pythonw.exe').write_bytes(fake_pe())
    (runtime/'desktop_start.py').write_text('print("fixture")\n')
    (runtime/'DESKTOP-RUNTIME.json').write_text('{"runtime_architecture":"AMD64"}')
    compiler=tmp_path/'makensis'
    compiler.write_bytes(b'synthetic compiler fixture')
    output=tmp_path/'CalcLens-folder.zip'
    monkeypatch.setattr(BUILD.subprocess,'run',lambda *a,**k:(tmp_path/'CalcLens.exe').write_bytes(fake_pe(0x14c)))
    result=BUILD.package(tmp_path,runtime,output,compiler)
    text=(tmp_path/'CalcLens-native.nsi').read_text(encoding='utf-8-sig')
    assert 'File /r' not in text and '$PLUGINSDIR\\CalcLens' not in text
    assert '$EXEDIR\\runtime\\pythonw.exe' in text
    assert 'ExecWait' in text and 'RequestExecutionLevel user' in text
    assert 'runtime_finished:' in text and 'StrCmp $1 0 finished' in text
    assert 'launcher-$4.log' in text and 'Python exited with code $1.' in text
    assert 'python313.zip' in text and 'FileWrite $5' in text
    assert 'FileWrite $5 "$0' not in text
    with zipfile.ZipFile(output) as archive:
        version=tomllib.loads((ROOT/'pyproject.toml').read_text())['project']['version']
        prefix=f'CalcLens-{version}-Windows-x64/'
        assert archive.read(prefix+'CalcLens.exe')==fake_pe(0x14c)
        assert archive.read(prefix+'runtime/pythonw.exe')==fake_pe()
        build=json.loads(archive.read(prefix+'runtime/DESKTOP-BUILD.json'))
        assert build['files']['desktop_start.py']==sha256((runtime/'desktop_start.py').read_bytes()).hexdigest()
        assert archive.testzip() is None
    assert result['distribution']=='folder'
    assert result['sha256']==sha256(output.read_bytes()).hexdigest()


def test_source_collection_keeps_images_referenced_by_bundled_documentation(tmp_path,monkeypatch):
    source=tmp_path/'source'
    for name,content in {
        'src/slab_preflight/__init__.py':b'__version__="fixture"',
        'examples/graphene.cif':b'CIF fixture', 'LICENSE':b'license',
        'THIRD_PARTY_NOTICES.md':b'notices', 'packaging/desktop/CalcLens.ico':b'icon',
        'packaging/desktop/windows_bootstrap.py':b'# bootstrap fixture',
        'docs/DESKTOP.md':b'![Actual screen](assets/report.png) [Verification](verification/report.json)',
        'docs/assets/report.png':b'PNG fixture',
        'docs/verification/report.json':b'{"status":"fixture"}',
        'docs/assets/unrelated.png':b'not referenced',
        'docs/design/private.md':b'not a desktop guide',
        'docs/.env':b'not distributable',
    }.items():
        path=source/name
        path.parent.mkdir(parents=True,exist_ok=True)
        path.write_bytes(content)
    runtime=tmp_path/'payload'
    runtime.mkdir()
    monkeypatch.setattr(BUILD,'ROOT',source)
    BUILD.collect_source(runtime)
    assert (runtime/'docs/assets/report.png').read_bytes()==b'PNG fixture'
    assert (runtime/'docs/verification/report.json').read_bytes()==b'{"status":"fixture"}'
    assert not (runtime/'docs/assets/unrelated.png').exists()
    assert not (runtime/'docs/design').exists() and not (runtime/'docs/.env').exists()


@pytest.mark.parametrize('escape', [False,True])
def test_documentation_collection_rejects_symlinks_and_escaping_references(tmp_path,monkeypatch,escape):
    source=tmp_path/'source'
    (source/'docs/assets').mkdir(parents=True)
    (source/'private.png').write_bytes(b'outside guide tree')
    if escape:
        link='assets/../../private.png'
    else:
        link='assets/image.png'
        try:
            (source/'docs/assets/image.png').symlink_to(source/'private.png')
        except OSError:
            pytest.skip('This Windows account cannot create symlinks')
    (source/'docs/DESKTOP.md').write_text(f'![Screen]({link})')
    runtime=tmp_path/'payload'
    runtime.mkdir()
    monkeypatch.setattr(BUILD,'ROOT',source)
    with pytest.raises(ValueError,match='escapes|Unsafe'):
        BUILD.collect_documentation(runtime)
