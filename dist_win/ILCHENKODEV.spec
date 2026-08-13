# -*- mode: python ; coding: utf-8 -*-
# PyInstaller spec for Windows — single standalone .exe, tray only, no console.
# PyInstaller injects Analysis, PYZ, EXE into this namespace automatically.

import glob
import os

# Collect all .bat strategy files at build time
bat_files = [(f, '.') for f in glob.glob('*.bat')]

a = Analysis(
    ['bypass_gui.py'],
    pathex=[],
    binaries=[],
    datas=[
        ('bin',   'bin'),
        ('lists', 'lists'),
        ('utils', 'utils'),
    ] + bat_files,
    hiddenimports=[
        'pystray',
        'pystray._win32',
        'PIL',
        'PIL.Image',
        'PIL.ImageDraw',
    ],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
)

pyz = PYZ(a.pure)

# Single-file exe: pass a.binaries + a.datas directly into EXE (no COLLECT step)
exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name='ILCHENKODEV',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=False,       # no console window
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    uac_admin=True,      # request admin rights for winws.exe
)
