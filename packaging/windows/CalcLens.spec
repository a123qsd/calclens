# Windows-only bundle. Invoke through scripts/build_windows.py.
import os
from pathlib import Path

from PyInstaller.utils.hooks import collect_data_files, collect_submodules, copy_metadata

root = Path(SPECPATH).resolve().parents[1]
stage = Path(os.environ['CALCLENS_BUILD_STAGE'])
notices = Path(os.environ['CALCLENS_BUILD_NOTICES'])
mode = os.environ['CALCLENS_BUILD_MODE']
name = os.environ['CALCLENS_BUILD_NAME']

datas = [
    (str(root / 'streamlit_app.py'), '.'),
    (str(root / 'examples'), 'examples'),
    (str(root / '.streamlit' / 'config.toml'), '.streamlit'),
    (str(root / 'LICENSE'), '.'),
    (str(root / 'THIRD_PARTY_NOTICES.md'), '.'),
    (str(root / 'src' / 'slab_preflight' / 'web_assets'), 'slab_preflight/web_assets'),
    (str(stage / 'DEFAULT_LANGUAGE.txt'), '.'),
    (str(stage / 'WINDOWS_BUILD_INFO.json'), '.'),
]
# Sources are supplied separately in the Windows support ZIP, not extracted on
# every application launch. License texts are present inside each EXE as well.
for entry in notices.iterdir():
    if entry.name != 'sources':
        datas.append((str(entry), 'third_party/' + entry.name if entry.is_dir() else 'third_party'))
for package in ('streamlit', 'plotly', 'ase'):
    datas += collect_data_files(package)
    datas += copy_metadata(package, recursive=True)

hiddenimports = collect_submodules('slab_preflight')
# Streamlit injects imports such as scriptrunner.magic_funcs into the app AST;
# these do not appear as ordinary imports during PyInstaller analysis.
hiddenimports += collect_submodules('streamlit')
# Plotly's graph object classes are imported lazily; analysis of the app script
# alone cannot discover them. The script itself is executed by Streamlit.
hiddenimports += collect_submodules('plotly', filter=lambda name: '.tests' not in name)
hiddenimports += collect_submodules('uvicorn')

a = Analysis(
    [str(root / 'packaging' / 'windows' / 'launcher.py')],
    pathex=[str(root / 'src')],
    binaries=[], datas=datas, hiddenimports=hiddenimports,
    hookspath=[], runtime_hooks=[],
    hooksconfig={'matplotlib': {'backends': ['Agg']}},
    excludes=['pytest', '_pytest', 'ruff', 'playwright', 'IPython', 'notebook',
              'PyQt5', 'PyQt6', 'PySide2', 'PySide6'],
    noarchive=False,
)
pyz = PYZ(a.pure)
if mode == 'onefile':
    exe = EXE(pyz, a.scripts, a.binaries, a.datas, [], name=name,
              debug=False, strip=False, upx=False, console=True)
else:
    exe = EXE(pyz, a.scripts, [], name=name, exclude_binaries=True,
              debug=False, strip=False, upx=False, console=True)
    coll = COLLECT(exe, a.binaries, a.datas, strip=False, upx=False, name=name)
