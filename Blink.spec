# -*- mode: python ; coding: utf-8 -*-
from PyInstaller.utils.hooks import collect_submodules

hiddenimports = ['webview.platforms.cocoa']
hiddenimports += collect_submodules('uvicorn')
hiddenimports += collect_submodules('httptools')
hiddenimports += collect_submodules('websockets')


a = Analysis(
    ['launcher.py'],
    pathex=[],
    binaries=[],
    datas=[('app/templates', 'app/templates'), ('app/static', 'app/static'), ('vendor/bin', 'vendor/bin'), ('vendor/licenses', 'vendor/licenses')],
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
    optimize=0,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name='Blink',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=['/Users/isaac/Developer/Blink/Blink.icns'],
)
coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=True,
    upx_exclude=[],
    name='Blink',
)
app = BUNDLE(
    coll,
    name='Blink.app',
    icon='/Users/isaac/Developer/Blink/Blink.icns',
    bundle_identifier=None,
)
