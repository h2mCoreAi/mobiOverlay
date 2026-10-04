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

The final exe is ~333MB with CPU-only torch, larger with CUDA.

## Run from source (no build step)

Fastest way to try it without producing an exe at all:

```bash
git clone https://github.com/h2mCoreAi/mobiOverlay.git
cd mobiOverlay
pip install torch torchvision --index-url https://download.pytorch.org/whl/cpu
pip install -r requirements.txt
python host/main.py
```

### Why CPU-only torch first?

The default `easyocr` install pulls CUDA-enabled torch (~2GB). Installing
CPU-only torch first avoids that bloat on machines without NVIDIA GPUs.

## Build your own exe

```bash
# CPU-only torch (recommended unless you have CUDA)
pip install torch torchvision --index-url https://download.pytorch.org/whl/cpu
pip install -r requirements.txt
pip install "pyinstaller>=6.9"  # 6.9+ required for Settings > Relaunch (see host/paths.py)

pyinstaller mobioverlay.spec --noconfirm
```

This produces `dist/mobiOverlay.exe` — a **true single-file executable**
with all 8 modules bundled inside. No separate `modules/` folder needed
next to the exe. Just double-click and go.

**Persisted files** (created next to the exe on first run):
- `config.json` — layout and settings
- `locations_cache.json` — UEX location cache (7-day TTL)
- `mobinotes_data.json` — mobiNotes storage
- `logistics_hub_debug.jsonl` — Logistics Hub debug log (if used)
- `logistics_hub_completed.jsonl` — contracts marked COMPLETE in Logistics Hub

## Running tests

The test suite uses plain asserts with no test framework dependency:

```bash
python tests/test_logistics_hub_parsing.py
```

This runs:
- Contract parsing fixtures (real OCR captures with hand-verified results)
- Location resolution fixtures (hauling-specific Admin terminal promotion)
- Distance calculation checks (`same_physical_place()`, `distance()`)
- UI state checks (if PySide6 is importable; skipped otherwise)

**Requirements**: Needs `locations_cache.json` present (run the app once first,
or the test will fetch from UEX API on first run).

Other test files:
- `tests/test_api_client_dedupe.py` — UexApiClient request deduplication
- `tests/test_core_persistence.py` — config/cache recovery, atomic saves, rate-limit detection (no network)
- `tests/test_pill_hover_unlock.py` — click-through pill hover-to-unlock (offscreen, no hooks)
- `tests/test_mobi_notes_store.py` — mobiNotes data store

## Test build side-by-side (before release)

To test a new build without overwriting your live/stable exe:

1. **Build to a separate folder**:
   ```bash
   pyinstaller mobioverlay.spec --noconfirm --distpath dist-test
   ```

2. **Copy to a separate test folder**, outside the repo and away from your live install

3. **Copy your existing `config.json`** to the test folder (preserves settings)

4. **Run the test build alongside Star Citizen** — verify features work

5. **Only after approval**: copy the tested exe over your live one, or wait for
   the official release

**Never overwrite your live exe with an untested build** — the owner may be
mid-session using the current version.

## Development workflow

When running from source, modules are loaded from the `modules/` folder in
the project root. When running the packaged exe, modules are bundled inside
and extracted to a temp directory at launch — the module discovery code
handles both cases transparently (`host/paths.py`'s `modules_root()`).

## Release workflow

1. Test the build locally (see "Test build side-by-side" above)
2. Merge the PR into `master` (pushing to `master` directly needs the
   owner's explicit OK — see `AGENTS.md`)
3. Tag the release: `git tag vX.Y.Z && git push origin vX.Y.Z`
4. GitHub Actions (`.github/workflows/release.yml`) automatically:
   - Builds the exe from `mobioverlay.spec`
   - Creates a zip: `mobiOverlay-vX.Y.Z-windows.zip`
   - Computes SHA256 checksum
   - Publishes a GitHub Release with the zip and checksum

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
