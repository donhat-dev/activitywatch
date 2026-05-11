# -*- mode: python -*-

from PyInstaller.utils.hooks import collect_all

block_cipher = None

name = "aw-odoo-sync"

charset_datas, charset_binaries, charset_hiddenimports = collect_all("charset_normalizer")
chardet_datas, chardet_binaries, chardet_hiddenimports = collect_all("chardet")

a = Analysis(['aw_odoo_sync/__main__.py'],
             pathex=[],
             binaries=charset_binaries + chardet_binaries,
             datas=charset_datas + chardet_datas,
             hiddenimports=['charset_normalizer', 'chardet'] + charset_hiddenimports + chardet_hiddenimports,
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
          name=name,
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
               name=name)
