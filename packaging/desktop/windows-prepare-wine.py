"""Reproduce the ICU setup inside an already-created disposable Wine prefix.

Windows supplies ICU itself. These Microsoft symbol-server files compensate
for that missing Wine implementation and are NEVER placed in the app payload.
No installed VM, host registry, or non-Wine operating-system tree is accessed.
"""
from __future__ import annotations

import argparse
from hashlib import sha256
import json
import os
from pathlib import Path
import shutil
import struct
import subprocess
import urllib.request


def prepare(prefix: Path, wine: Path | None = None, font_directory: Path | None = None) -> dict:
    prefix = prefix.resolve(strict=True)
    system = prefix/'drive_c/windows/system32'
    if not (prefix/'system.reg').is_file() or not system.is_dir():
        raise ValueError('Select an existing disposable Wine prefix, not an OS or application directory.')
    manifest = json.loads(Path(__file__).with_name('windows-wine-icu.json').read_bytes())
    for record in manifest['files']:
        path = system/record['name']
        data = path.read_bytes() if path.is_file() else b''
        if sha256(data).hexdigest() != record['sha256']:
            with urllib.request.urlopen(record['url'], timeout=30) as response:
                data = response.read(record['size_bytes']+1)
        if len(data) != record['size_bytes'] or sha256(data).hexdigest() != record['sha256']:
            raise ValueError('Microsoft test-system DLL size/hash mismatch.')
        pe = struct.unpack_from('<I', data, 60)[0]
        if data[:2] != b'MZ' or data[pe:pe+4] != b'PE\0\0' or struct.unpack_from('<H',data,pe+4)[0] != 0x8664:
            raise ValueError('Test-system DLL is not PE AMD64.')
        path.write_bytes(data)
    if font_directory is not None:
        fonts=prefix/'drive_c/windows/Fonts'
        fonts.mkdir(exist_ok=True)
        font_hashes={
            'DejaVuSans.ttf':'3fdf69cabf06049ea70a00b5919340e2ce1e6d02b0cc3c4b44fb6801bd1e0d22',
            'DejaVuSans-Bold.ttf':'b184b89e3c1075f22f6b71575b6fc20d4972b3cfd3b23322ca6fd596dcaef167',
        }
        for name,expected in font_hashes.items():
            original=font_directory/name
            if sha256(original.read_bytes()).hexdigest()!=expected:
                raise ValueError('Test-prefix font does not match the verified Matplotlib wheel font.')
            shutil.copyfile(original,fonts/name)
        manifest['test_fonts']={'origin':'Unmodified DejaVu fonts from locked Matplotlib wheel',
                                'sha256':font_hashes,'scope':'Disposable test prefix only'}
    if wine is not None:
        # Some macOS Wine launchers filter Unix QT_* variables. Configure only
        # this prefix's Windows environment so the actual EXE inherits the test mode.
        environment = dict(os.environ, WINEPREFIX=str(prefix), WINEDEBUG='-all', MVK_CONFIG_LOG_LEVEL='0',
                           WINEDLLOVERRIDES='winemenubuilder.exe=d;mscoree=d;mshtml=d;icuuc,icuin=n,b')
        subprocess.run([str(wine), 'reg', 'add', r'HKCU\Environment', '/v', 'QT_QPA_PLATFORM',
                        '/t', 'REG_SZ', '/d', 'offscreen', '/f'], env=environment, check=True)
        if font_directory is not None:
            subprocess.run([str(wine), 'reg', 'add', r'HKCU\Environment', '/v', 'QT_QPA_FONTDIR',
                            '/t', 'REG_SZ', '/d', r'C:\windows\Fonts', '/f'], env=environment,check=True)
    (prefix/'CALCLENS-WINE-TEST-SYSTEM-DLLS.json').write_text(json.dumps(manifest,indent=2)+'\n')
    return manifest


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--prefix', type=Path, required=True)
    parser.add_argument('--wine', type=Path)
    parser.add_argument('--font-directory', type=Path,
                        help='Verified payload Lib/site-packages/matplotlib/mpl-data/fonts/ttf directory.')
    options = parser.parse_args()
    print(json.dumps(prepare(options.prefix, options.wine, options.font_directory), indent=2))
