# -*- mode: python ; coding: utf-8 -*-
#
# Full-product spec: bundles everything into a onedir folder
# (dist/mobiOverlay/mobiOverlay.exe + _internal/):
# - All 8 modules (bundled as data, discovered at runtime from sys._MEIPASS)
# - easyocr, torch, torchvision for Logistics Hub OCR
# - pygame-ce for mobiThrottle joystick support
#
# Onedir (not onefile) is the only packaging mode: a onefile exe unpacks to a
# new temp folder on every launch and antivirus rescans it each time (~12.5 s
# to first window). The folder is unpacked once when the user extracts the
# release zip; later launches are fast. Keep the folder together — the exe
# cannot run without _internal/.
#
# config.json, notes data, cache files still persist NEXT TO the exe (not inside
# _internal/) — see host/paths.py's app_root() vs modules_root() distinction.
#
# Expect a large folder and several minutes of build time (torch binaries are large).
#
# LITE build: set MOBI_LITE=1 to leave out the OCR stack (torch, torchvision,
# easyocr, OpenCV, scipy, scikit-image, numpy, Pillow). Everything except
# Logistics Hub scanning works, and the folder is a fraction of the size. It is
# written as dist/mobiOverlay-lite/ so it never overwrites the full build.
#
#   PowerShell:  $env:MOBI_LITE = "1"; pyinstaller mobioverlay.spec --noconfirm

import os

from PyInstaller.utils.hooks import collect_all, collect_data_files, collect_submodules

LITE = os.environ.get('MOBI_LITE') == '1'
OCR_PACKAGES = ['torch', 'torchvision', 'easyocr', 'cv2', 'scipy', 'skimage', 'numpy', 'PIL']

if LITE:
    torch_datas, torch_binaries, torch_hiddenimports = [], [], []
    torchvision_datas, torchvision_binaries, torchvision_hiddenimports = [], [], []
    easyocr_datas, easyocr_binaries, easyocr_hiddenimports = [], [], []
    pillow_datas, pillow_hiddenimports = [], []
else:
    torch_datas, torch_binaries, torch_hiddenimports = collect_all('torch')
    torchvision_datas, torchvision_binaries, torchvision_hiddenimports = collect_all('torchvision')
    easyocr_datas, easyocr_binaries, easyocr_hiddenimports = collect_all('easyocr')
    pillow_datas = collect_data_files('PIL')
    pillow_hiddenimports = collect_submodules('PIL')
pygame_datas, pygame_binaries, pygame_hiddenimports = collect_all('pygame')

# Tree() returns TOC 3-tuples — must NOT be mixed into Analysis(datas=...) 2-tuples.
# Attach with a.datas += Tree(...) after Analysis instead.
modules_tree = Tree('modules', prefix='modules', excludes=['__pycache__', '*.pyc'])

all_datas = (
    [
        ('host/assets/fonts', 'host/assets/fonts'),
        ('host/assets/icons', 'host/assets/icons'),
    ]
    + torch_datas
    + torchvision_datas
    + easyocr_datas
    + pillow_datas
    + pygame_datas
)
all_binaries = torch_binaries + torchvision_binaries + easyocr_binaries + pygame_binaries
all_hiddenimports = (
    torch_hiddenimports
    + torchvision_hiddenimports
    + easyocr_hiddenimports
    + pillow_hiddenimports
    + pygame_hiddenimports
    + ([] if LITE else [
        'PIL._tkinter_finder',
        'numpy',
        'cv2',
        'scipy',
        'scipy.special',
        'scipy.ndimage',
        'skimage',
        'skimage.transform',
    ])
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
    excludes=OCR_PACKAGES if LITE else [],
    noarchive=False,
    optimize=0,
)
a.datas += modules_tree
pyz = PYZ(a.pure)

NAME = 'mobiOverlay-lite' if LITE else 'mobiOverlay'

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name=NAME,
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=False,
    disable_windowed_traceback=False,
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
    upx=False,
    upx_exclude=[],
    name=NAME,
)
