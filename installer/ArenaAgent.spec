# -*- mode: python ; coding: utf-8 -*-
# PyInstaller spec for the Arena Windows Agent desktop executable.
#
#   Build (on Windows):  pyinstaller installer/ArenaAgent.spec
#   Output:  dist/ArenaAgent.exe   (referenced by install_windows.iss)
#
# The engine is packaged as a frozen app that serves the GUI; the bridge,
# browser-extension and vision deps are bundled so the app runs standalone.

from PyInstaller.utils.hooks import collect_data_files, collect_submodules

datas = []
for pkg in ("agent_platform",):
    datas += collect_data_files(pkg, includes=["ui/*", "*.json"])

hiddenimports = []
for pkg in ("agent_platform", "mcp", "pydantic", "fastapi", "uvicorn"):
    hiddenimports += collect_submodules(pkg)

block_cipher = None

a = Analysis(
    ["desktop_app.py"],
    pathex=["."],
    binaries=[],
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=["tkinter", "matplotlib", "pygame"],
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=block_cipher,
    noarchive=False,
)
pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)
exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="ArenaAgent",
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
    icon=None,
)
coll = COLLECT(
    exe,
    a.binaries,
    a.zipfiles,
    a.datas,
    strip=False,
    upx=True,
    upx_exclude=[],
    name="ArenaAgent",
)
