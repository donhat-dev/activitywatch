# -*- mode: python -*-

import platform
import sys
from pathlib import Path
from PyInstaller.utils.hooks import collect_data_files, collect_submodules

block_cipher = None

hiddenimports = collect_submodules('PIL') + ['charset_normalizer']

if platform.system() == 'Windows':
    hiddenimports += [
        'win32api',
        'win32con',
        'win32gui',
        'win32ui',
        'win32timezone',
        'pywintypes',
    ]

datas = collect_data_files('PIL', include_py_files=True)

# Explicitly bundle pywintypes/pythoncom DLLs required by win32gui/win32ui (Windows only)
_pywin32_binaries = []
if platform.system() == 'Windows':
    _pywin32_sys = Path(sys.exec_prefix) / 'Lib/site-packages/pywin32_system32'
    _pywin32_binaries = [
        (str(dll), 'pywin32_system32')
        for dll in _pywin32_sys.glob('*.dll')
        if dll.exists()
    ]

a = Analysis(['aw_watcher_screenshot_mini/__main__.py'],
             pathex=[],
             binaries=_pywin32_binaries,
             datas=datas,
             hiddenimports=hiddenimports,
             hookspath=[],
             runtime_hooks=[],
             excludes=[],
             win_no_prefer_redirects=False,
             win_private_assemblies=False,
             cipher=block_cipher)
pyz = PYZ(a.pure, a.zipped_data,
             cipher=block_cipher)
exe = EXE(pyz,
          a.scripts,
          exclude_binaries=True,
          name='aw-watcher-screenshot-mini',
          contents_directory='.',
          debug=False,
          strip=False,
          upx=True,
          console=True)
coll = COLLECT(exe,
               a.binaries,
               a.zipfiles,
               a.datas,
               strip=False,
               upx=True,
               name='aw-watcher-screenshot-mini')
