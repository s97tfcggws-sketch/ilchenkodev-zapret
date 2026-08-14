# -*- mode: python ; coding: utf-8 -*-
# PyInstaller spec for macOS tray-only app.
# PyInstaller injects Analysis, PYZ, EXE, COLLECT, BUNDLE into this namespace —
# do NOT import them explicitly.

a = Analysis(
    ['app.py'],
    pathex=[],
    binaries=[],
    datas=[
        ('bin',   'bin'),
        ('lists', 'lists'),
    ],
    hiddenimports=[
        'pystray',
        'pystray._darwin',
        'PIL',
        'PIL.Image',
        'PIL.ImageDraw',
        'AppKit',
        'Foundation',
        'objc',
    ],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
)

pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name='ilchenkodev-zapret',
    icon='icon.icns',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)

coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=True,
    upx_exclude=[],
    name='ilchenkodev-zapret',
)

app = BUNDLE(
    coll,
    name='ilchenkodev-zapret.app',
    icon='icon.icns',
    bundle_identifier='dev.ilchenko.zapret',
    info_plist={
        # Hide from Dock AND Cmd+Tab switcher entirely — menu bar only
        'LSUIElement': True,
        # Retina / high-DPI support
        'NSHighResolutionCapable': True,
        'CFBundleName': 'ilchenkodev-zapret',
        'CFBundleDisplayName': 'ilchenkodev-zapret',
        'CFBundleShortVersionString': '1.1.0',
        'CFBundleVersion': '1.1.0',
        'NSAppleEventsUsageDescription': 'Used for configuration dialogs.',
    },
)
