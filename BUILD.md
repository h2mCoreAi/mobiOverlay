# Building mobiOverlay from source

You don't need to trust the prebuilt exe on the Releases page — everything
needed to build it yourself is in this repo, and it's the exact same
process the automated release build uses (`.github/workflows/release.yml`),
so a self-built copy and the one on Releases should be identical.

## System requirements for building

- **Python 3.12** (3.11+ should work, 3.12 is what CI uses)
- **~4GB disk space** during build (torch/easyocr deps are large)
- **~8GB RAM** recommended (PyInstaller analyzing torch can be memory-heavy)
- **10-20 minutes** build time (mostly PyInstaller collecting torch binaries)

The final exe is ~600-900MB. This is normal for a full torch/easyocr bundle.

## Run from source (no build step)

Fastest way to try it without producing an exe at all:

```bash
git clone <repo-url>
cd mobiOverlay
pip install -r requirements.txt
python host/main.py
```

### Smaller install (CPU-only torch)

The default `easyocr` install pulls CUDA-enabled torch (~2GB). For a smaller
install on machines without NVIDIA GPUs:

```bash
pip install torch torchvision --index-url https://download.pytorch.org/whl/cpu
pip install -r requirements.txt
```

## Build your own exe

```bash
# CPU-only torch (recommended unless you have CUDA)
pip install torch torchvision --index-url https://download.pytorch.org/whl/cpu
pip install -r requirements.txt
pip install pyinstaller

pyinstaller mobioverlay.spec --noconfirm
```

This produces `dist/mobiOverlay.exe` — a **true single-file executable**
with all 8 modules bundled inside. No separate `modules/` folder needed
next to the exe. Just double-click and go.

`config.json` and other data files (notes, cache) are created next to
the exe the first time you run it — those persist between launches.

## Development workflow

When running from source, modules are loaded from the `modules/` folder in
the project root (the normal external layout). When running the packaged exe,
modules are bundled inside and extracted to a temp directory at launch —
the module discovery code handles both cases transparently.

## Build troubleshooting

### Out of memory during build
PyInstaller analyzing torch can use 4-6GB RAM. Close other applications or
add swap space.

### Missing DLLs at runtime
If the exe crashes on launch with missing DLL errors, ensure you built with
the same Python version you installed torch for. Mixing Python versions or
using a venv created with a different Python can cause this.

### UPX errors
UPX is disabled in the spec file — torch binaries don't compress well and
UPX can corrupt them. Don't re-enable it.

### First OCR scan is slow
The first Logistics Hub scan after launch takes 10-30 seconds while easyocr
initializes and (on first-ever run) downloads the English language model
(~100MB, cached afterward in `~/.EasyOCR/`). Subsequent scans are fast.

## Verifying a downloaded release build matches source

Every release ships a `.sha256` file alongside the zip. Check the tag's
GitHub Actions run log to see the exact commit and steps that produced it,
or just build the same tag yourself with the steps above and compare.
