# Distribution Readiness Report

Status: **Not release-ready** — several blockers detailed below, but the
path to a v0.1.0 is clear and achievable.

## 1. Current Packaging Story

### What the Build Produces

The release workflow (`.github/workflows/release.yml`) produces a zip containing:
- `mobiOverlay.exe` — a PyInstaller onefile build (~50-80MB without OCR deps)
- `modules/` folder — plain `.py` files, external to the exe

This matches the documented architecture: `host/` is bundled, `modules/` and
`config.json` are external. A stranger downloading the release zip extracts
it, runs the exe, and `config.json` is created on first launch.

### What's External vs. Bundled

| Component | Location | Why |
|-----------|----------|-----|
| Host code (`host/`) | Inside exe | Core app logic |
| Fonts | Inside exe | Non-pluggable assets |
| Modules (`modules/`) | External folder | Editable/auditable without rebuild |
| `config.json` | Created at runtime | PyInstaller temp dir doesn't persist |
| Module-specific deps | **Not bundled** | Problem — see below |

### How Installation Works Today

For trading modules only (Commodity Prices, Trade Route Optimizer, Refinery
Finder, Multi-Commodity Finder):
1. Download and extract the release zip
2. Run `mobiOverlay.exe`
3. Works — these modules use only `requests` + `PySide6`, both bundled

For Logistics Hub (OCR):
1. Download and extract
2. Run exe → module shows "easyocr not installed" error
3. User must have Python installed separately
4. User must run `pip install -r modules/logistics_hub/requirements.txt`
5. **Problem**: The exe doesn't use that Python environment

This is the core distribution gap: the exe bundles its own Python interpreter,
but module-level dependencies (`easyocr`/PyTorch) aren't bundled — there's
no way for a user to satisfy them without either rebuilding the exe or
running from source.

For mobiThrottle (joystick):
- Uses `pygame-ce`, which **is** in the root `requirements.txt`
- Should bundle correctly, but hasn't been verified in a real release build

## 2. What Made Distribution Harder

### 2.1 Logistics Hub's OCR Stack (~500MB)

The single biggest distribution complexity. Timeline from DECISIONS.md:

**2026-09-04 (first attempt):** Logistics Hub was framed as an "optional,
manual-install module" — users would run `pip install -r modules/logistics_hub/requirements.txt` themselves.

**2026-09-04 (same day, superseded):** Decision reversed — "distribution is
all-inclusive, every module always bundled together." But the practical
work to make that happen never completed.

Current state per PROGRESS.md line 1049:
> Packaging: `modules/logistics_hub/requirements.txt` (easyocr, ~500MB+ with
> PyTorch) needs folding into the standard install/build path now that
> distribution is all-inclusive (see DECISIONS.md, supersedes the earlier
> "optional module" framing) — **not done yet**.

The dependency chain:
```
easyocr >= 1.7.0
├── torch (PyTorch) ~300-400MB
├── torchvision ~50-100MB
├── opencv-python-headless
├── scikit-image
└── Pillow >= 9.0.0
```

PyInstaller **can** bundle PyTorch, but:
- Adds 300-500MB to the exe (currently ~50-80MB without it)
- Startup time increases (PyTorch loads its CUDA/CPU kernels)
- Build time balloons (CI runner may timeout or run out of disk)
- Download size balloons (every user pays the cost, even if they only want trading modules)

### 2.2 Unconditional Top-Level Import

From `modules/logistics_hub/module.py` lines 107-116:
```python
try:
    import easyocr
    from PIL import Image, ImageOps
    OCR_AVAILABLE = True
except ImportError:
    OCR_AVAILABLE = False
```

This import runs **at module discovery time** (when `discover_modules()` calls
`spec.loader.exec_module()`), not when the user clicks SCAN CONTRACT. Even
with the `try/except`, the import attempt happens at startup. This is why:

- Startup takes ~3s longer when Logistics Hub is present (PROGRESS.md line 587:
  "import easyocr (2.79s of 3.64s total)")
- The splash screen shows "Loading logistics_hub..." during this pause
- If easyocr were bundled, every user would pay this startup cost

### 2.3 pygame-ce (mobiThrottle)

Added for joystick/throttle reads. It's in `requirements.txt`:
```
pygame-ce>=2.5.0  # mobiThrottle module – passive HID joystick/throttle reads
```

PyInstaller should bundle it, but:
- pygame-ce has native SDL2 binaries
- No verification that it works in the frozen build (not yet release-tested)
- Adds ~15-20MB to the bundle

### 2.4 Win32-Only Assumptions

Multiple modules use Windows-specific APIs:
- `host/hotkey.py` — `keyboard` library's `WH_KEYBOARD_LL` hook
- `modules/mobi_throttle/module.py` — `ctypes.windll.user32` for `WS_EX_TRANSPARENT`
- `host/main.py` — `ctypes.windll.kernel32.AllocConsole()` for debug console
- `modules/logistics_hub/gamelog_verify.py` — Reads Star Citizen's `Game.log` (Windows path)

This is documented and intentional (Star Citizen is Windows-only), but:
- No macOS/Linux builds possible without significant rework
- CI workflow only runs on `windows-latest`

### 2.5 Game.log Path Assumptions

Logistics Hub's Game.log verification assumes:
- Default path: `%LOCALAPPDATA%\Star Citizen\...\Game.log`
- Configurable via `game_log_path` setting

Not a blocker, but first-run UX requires manual path configuration for
non-default installs.

### 2.6 Unsigned Exe

The exe is unsigned. On Windows:
- SmartScreen will warn "Windows protected your PC"
- Some users won't know to click "More info" → "Run anyway"
- Corporate/managed machines may block it entirely

Mitigation exists (DECISIONS.md line 49-64): modules are external `.py` files
that users can audit. But this only helps technical users.

## 3. Release Blockers

### Critical (Must Fix)

| Blocker | Impact | Evidence |
|---------|--------|----------|
| **easyocr not bundled** | Logistics Hub non-functional for most users | PROGRESS.md:1049, module shows error |
| **pygame-ce untested frozen** | mobiThrottle may fail silently | No release build test documented |
| **No end-user README** | Users don't know what they're downloading | `README.md` doesn't exist |

### High (Should Fix Before v0.1)

| Blocker | Impact |
|---------|--------|
| **No install docs** | Even "extract and run" isn't documented |
| **SmartScreen warning** | Scares non-technical users |
| **~500MB download** if OCR bundled | Hostile to users on slow connections |
| **3s+ startup** with OCR loaded | Feels broken/frozen |

### Medium (Can Ship Without)

| Issue | Impact |
|-------|--------|
| Game.log path first-run UX | Minor friction for Logistics Hub users |
| Debug console opt-in unclear | Only matters for troubleshooting |
| Relaunch fix not human-verified | Edge case, workaround exists (manual restart) |

## 4. Distribution Strategies (Ranked)

### Strategy A: Slim Core + Optional OCR Add-On (Recommended)

**What**: Ship two releases:
- `mobiOverlay-v0.1.0-windows.zip` (~60-80MB) — all trading modules + mobiThrottle + Crosshair + mobiNotes
- `mobiOverlay-v0.1.0-ocr-addon-windows.zip` (~500MB) — adds Logistics Hub with easyocr/PyTorch bundled

**How**:
1. Add a `--exclude-ocr` flag to the spec file (or a second spec)
2. Core build excludes `modules/logistics_hub/` from the zip
3. OCR add-on build bundles easyocr into the exe + includes `modules/logistics_hub/`
4. User downloads core, optionally downloads add-on if they want OCR

**Tradeoffs**:
| Pro | Con |
|-----|-----|
| Most users get fast download | Two release artifacts to maintain |
| Startup stays fast for trading | "Drop a folder in modules/" breaks for OCR |
| Clear separation of concerns | User must know which zip to download |

**Effort**: Low-medium. Two spec files, workflow change, README update.
**Risk**: Low. Trading modules are already functional.
**Fit**: Preserves "drop a folder" for non-OCR modules. OCR becomes a "blessed" heavy module.

### Strategy B: All-Inclusive + Lazy Load OCR

**What**: Bundle everything, but defer `import easyocr` until first SCAN click.

**How**:
1. Move the `try: import easyocr` block from module top-level into `_do_scan()`
2. Show a "Loading OCR engine..." progress indicator on first scan
3. Cache the reader instance for subsequent scans

**Tradeoffs**:
| Pro | Con |
|-----|-----|
| One release artifact | ~500MB download for everyone |
| "It just works" UX | Long pause on first scan (3s+) |
| Matches stated "all-inclusive" decision | Build/CI complexity for bundling torch |

**Effort**: Low (code change) + Medium (bundling torch in PyInstaller).
**Risk**: Medium. PyInstaller + PyTorch can be finicky; needs CI testing.
**Fit**: Matches the superseded DECISIONS.md intent. Simpler user story.

### Strategy C: ONNX Runtime Instead of PyTorch

**What**: Replace easyocr (PyTorch backend) with an ONNX-based OCR engine.

**How**:
1. Export easyocr's model to ONNX format
2. Use `onnxruntime` (~20-50MB) instead of PyTorch (~300MB)
3. Or switch to a lighter OCR library entirely (e.g., `doctr` with ONNX)

**Tradeoffs**:
| Pro | Con |
|-----|-----|
| Much smaller bundle | May degrade OCR accuracy |
| Faster inference (ONNX is optimized) | Engineering effort to port/test |
| Still "all-inclusive" | easyocr's model may not export cleanly |

**Effort**: High. Requires OCR engine research, porting, accuracy testing.
**Risk**: High. OCR accuracy is load-bearing for Logistics Hub.
**Fit**: Best long-term solution if accuracy holds. High upfront cost.

### Strategy D: Keep Modules External, Document "Run From Source"

**What**: Accept that Logistics Hub is power-user-only; document the path.

**How**:
1. Ship only the slim core exe
2. Include `modules/logistics_hub/` in the zip as-is
3. README documents: "For Logistics Hub, run from source with `pip install -r requirements.txt`"

**Tradeoffs**:
| Pro | Con |
|-----|-----|
| Zero packaging work | Poor UX for non-developers |
| Matches current reality | "All-inclusive" decision violated |
| Users can audit all code | Logistics Hub effectively unsupported |

**Effort**: Minimal (docs only).
**Risk**: Low technically, high for user adoption.
**Fit**: Temporary stopgap. Not a real distribution strategy.

### Ranking Summary

1. **Strategy A** (Slim Core + OCR Add-On) — best balance of effort/UX/size
2. **Strategy B** (All-Inclusive + Lazy Load) — simpler UX, heavier download
3. **Strategy D** (Document "Run From Source") — temporary/fallback only
4. **Strategy C** (ONNX) — best long-term, but too much work for v0.1

## 5. Minimal Path to First Public Release

### v0.1.0: "Trading Tools" Release

**Scope**: Ship the 7 modules that work without heavy dependencies.

**Included**:
- Commodity Prices (mobiCommodities)
- Trade Route Optimizer (mobiTrade)
- Refinery Finder (mobiRefinery)
- Multi-Commodity Finder
- Crosshair (mobiAim)
- mobiNotes
- mobiThrottle

**Excluded** (documented, not hidden):
- Logistics Hub — mentioned in README as "coming in a future release" or "run from source"

**Work Required**:
1. Verify `pygame-ce` bundles correctly (build + run test)
2. Write `README.md` (what it is, how to run, what's included)
3. Confirm all 7 modules load and function in frozen build
4. Cut tag, let CI build, smoke-test the artifact

**Estimated Effort**: 1-2 focused sessions. No new code, just verification + docs.

### v0.2.0: "Logistics Hub Add-On" Release

**Scope**: Add Logistics Hub as a separate download.

**Work Required**:
1. Create second PyInstaller spec that bundles easyocr/torch
2. Modify workflow to produce two zips
3. Document the two-download story
4. OR: Implement Strategy B (lazy load) if single-artifact is preferred

**Estimated Effort**: 2-4 sessions depending on PyInstaller/torch issues.

## 6. What NOT to Do

### Don't Embed a Shared UEX Token
Per DECISIONS.md line 137-150: "no shared app token baked into the exe, ever."
The brute-force commodity scan exists specifically because the "real" ranking
endpoint requires auth. This is a hard rule, not a suggestion.

### Don't Invent UEX Business Logic
The app consumes UEX's public API exactly as documented. Don't add commodity
prices from other sources, don't fabricate distance data, don't guess at
terminal availability.

### Don't Bundle Modules Inside the Exe
Per DECISIONS.md line 49-64: modules stay external for auditability and
editability. The frozen exe should never contain `modules/**/*.py`. The only
exception would be a fully separate "all-in-one" variant, not the primary release.

### Don't Move UI Onto the Gaming Monitor for Testing
Per PROGRESS.md line 1089-1093: testing uses `PrintWindow` capture on the
secondary monitor. Never reposition the app onto the primary display.

### Don't Add Cross-Platform Support Prematurely
Star Citizen is Windows-only. macOS/Linux support adds complexity for zero users.
Keep the Win32 assumptions; they're intentional.

### Don't Over-Engineer the First Release
The goal is "useful and downloadable," not "perfect." Ship trading modules
first; Logistics Hub can follow.

---

## Summary Recommendation

**Ship a v0.1.0 with trading modules only (Strategy A, phase 1).** The 7
non-OCR modules are functional today; the only blockers are verification
(pygame-ce frozen) and documentation (README). This gives users something
real while the heavier Logistics Hub packaging is sorted out separately.
Logistics Hub as a second download (or lazy-loaded in v0.2.0) is the clear
path forward — trying to ship everything at once is what made distribution
feel "hard" in the first place.
