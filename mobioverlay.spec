# -*- mode: python ; coding: utf-8 -*-
#
# Full-product spec: bundles everything into a single mobiOverlay.exe:
# - All 8 modules (bundled as data, discovered at runtime from sys._MEIPASS)
# - easyocr, torch, torchvision for Logistics Hub OCR
# - pygame-ce for mobiThrottle joystick support
#
# config.json, notes data, cache files still persist NEXT TO the exe (not inside
# it) — see host/paths.py's app_root() vs modules_root() distinction.
#
# Expect a ~600-900MB exe and 3-10min build time (torch binaries are large).

from PyInstaller.utils.hooks import collect_all, collect_data_files, collect_submodules

# ---------------------------------------------------------------------------
# Collect torch/torchvision (CUDA-free CPU variant ships with easyocr on PyPI)
# ---------------------------------------------------------------------------
torch_datas, torch_binaries, torch_hiddenimports = collect_all('torch')
torchvision_datas, torchvision_binaries, torchvision_hiddenimports = collect_all('torchvision')

# ---------------------------------------------------------------------------
# Collect easyocr — models are downloaded at runtime, but the package itself
# has compiled components and data files (character dicts, configs).
# ---------------------------------------------------------------------------
easyocr_datas, easyocr_binaries, easyocr_hiddenimports = collect_all('easyocr')

# ---------------------------------------------------------------------------
# Pillow — collect PIL plugins and libs
# ---------------------------------------------------------------------------
pillow_datas = collect_data_files('PIL')
pillow_hiddenimports = collect_submodules('PIL')

# ---------------------------------------------------------------------------
# Collect pygame-ce — mobiThrottle uses it for joystick/throttle axis reads.
# pygame bundles SDL2 DLLs that must be collected explicitly.
# ---------------------------------------------------------------------------
pygame_datas, pygame_binaries, pygame_hiddenimports = collect_all('pygame')

# ---------------------------------------------------------------------------
# Collect modules/ tree (all 8 modules, bundled into the exe as data).
# PyInstaller extracts these to sys._MEIPASS/modules at runtime.
# Excludes __pycache__ via Tree's excludes parameter.
# ---------------------------------------------------------------------------
modules_tree = Tree('modules', prefix='modules', excludes=['__pycache__', '*.pyc'])

# ---------------------------------------------------------------------------
# Aggregate all external deps' artifacts
# ---------------------------------------------------------------------------
all_datas = (
    [('host/assets/fonts', 'host/assets/fonts')]
    + torch_datas
    + torchvision_datas
    + easyocr_datas
    + pillow_datas
    + pygame_datas
    + modules_tree
)
all_binaries = torch_binaries + torchvision_binaries + easyocr_binaries + pygame_binaries
all_hiddenimports = (
    torch_hiddenimports
    + torchvision_hiddenimports
    + easyocr_hiddenimports
    + pillow_hiddenimports
    + pygame_hiddenimports
    + [
        'PIL._tkinter_finder',
        'numpy',
        'cv2',
        'scipy',
        'scipy.special',
        'scipy.ndimage',
        'skimage',
        'skimage.transform',
    ]
)

a = Analysis(
    ['host/main.py'],
    pathex=[],
    binaries=all_binaries,
    datas=all_datas,
    hiddenimports=all_hiddenimports,
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
    a.binaries,
    a.datas,
    [],
    name='mobiOverlay',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,  # Disabled — UPX on torch binaries causes crashes and barely shrinks them
    upx_exclude=[],
    runtime_tmpdir=None,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)
