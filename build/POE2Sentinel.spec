# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller spec for POE2 Sentinel (Memory + OCR).

Onedir build producing dist/POE2Sentinel/POE2Sentinel.exe + _internal.
Tesseract OCR is bundled via the Inno Setup installer for OCR fallback mode.

Build: py -m PyInstaller build/POE2Sentinel.spec --clean
"""
import os
import glob

block_cipher = None
spec_root = os.path.dirname(os.path.abspath(SPECPATH))

from PyInstaller.utils.hooks import collect_data_files, collect_all

# customtkinter ships theme/asset data files
added_files = collect_data_files("customtkinter")

# Extra binaries/hidden imports gathered from optional packages below.
extra_binaries = []
extra_hiddenimports = []

# pythonnet + clr_loader power the Shader Reveal feature (LibGGPK3 via .NET).
# Collected best-effort: if the .NET tooling is incomplete the build still
# succeeds and Shader Reveal degrades gracefully at runtime.
for _pkg in ("pythonnet", "clr_loader"):
    try:
        _datas, _bins, _hidden = collect_all(_pkg)
        added_files += _datas
        extra_binaries += _bins
        extra_hiddenimports += _hidden
    except Exception:
        pass

# LibGGPK3 .NET assemblies (+ native oo2core) used by map_shader_patch.
# map_shader_patch resolves these via __file__-relative "libggpk", which under
# a onedir freeze lands in _internal/libggpk, so bundle them to that subfolder.
_libggpk_dir = os.path.join(spec_root, "libggpk")
added_files += [(f, "libggpk") for f in glob.glob(os.path.join(_libggpk_dir, "*"))]

# Optional application icon
_icon_path = os.path.join(spec_root, "assets", "flask.ico")
_icon = _icon_path if os.path.isfile(_icon_path) else None

hiddenimports = [
    "customtkinter",
    "PIL._tkinter_finder",
    "win32gui",
    "win32con",
    "win32api",
    "pygetwindow",
    "mss",
    "mss.windows",
    "numpy",
    "pytesseract",
    "keyboard",
    "pymem",
    "pymem.process",
    "pymem.memory",
    "pymem.pattern",
    # Terrain overlay (runs in a multiprocessing child) + PyQt5 backend
    "PyQt5",
    "PyQt5.QtCore",
    "PyQt5.QtGui",
    "PyQt5.QtWidgets",
    "PyQt5.sip",
    # Shader reveal (.NET bridge via pythonnet)
    "clr",
    # Local modules
    "flask_bot",
    "coordinate_picker",
    "custom_dialog",
    "toast_notification",
    "terrain_reader",
    "map_overlay",
    "map_shader_patch",
] + extra_hiddenimports

a = Analysis(
    [os.path.join(spec_root, "gui.py")],
    pathex=[spec_root],
    binaries=extra_binaries,
    datas=added_files,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={
        "tk": {
            "tk_library": None,
            "tcl_library": None,
        }
    },
    runtime_hooks=[],
    excludes=[
        "matplotlib",
        "pandas",
        "scipy",
        "pytest",
        "IPython",
        "jupyter",
        "notebook",
    ],
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=block_cipher,
    noarchive=False,
    optimize=1,
)

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="POE2Sentinel",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=_icon,
    uac_admin=True,  # Memory reading + keyboard requires elevation
)

coll = COLLECT(
    exe,
    a.binaries,
    a.zipfiles,
    a.datas,
    strip=False,
    upx=False,
    upx_exclude=[],
    name="POE2Sentinel",
)
