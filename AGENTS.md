# AI Agent Onboarding — mobiOverlay

This is the canonical onboarding file for any AI agent (Claude, GPT, Cursor,
Aider, etc.) working on mobiOverlay. Read this first, then dive into specific
docs as needed.

---

## What is mobiOverlay?

A modular, always-on-top Star Citizen data overlay styled after the in-game
MobiGlas. Dark sci-fi HUD with cyan/amber accents. Data comes from the
[UEX Corp API](https://uexcorp.uk/) (community-sourced SC trade/economy data).

**No game memory reads, no log parsing** (except optional Game.log verification
in Logistics Hub, user-configured). No telemetry. No embedded UEX auth token —
anonymous public API endpoints only.

---

## Repo layout

```
mobiOverlay/
├── host/                    # mobiOverlay Core (the framework)
│   ├── main.py              # entry point
│   ├── main_window.py       # always-on-top window, tray, settings
│   ├── card.py / card_container.py  # card system
│   ├── module_base.py       # module contract base class
│   ├── module_loader.py     # module discovery + contract validation
│   ├── api_client.py        # UEX API client (pooled, deduplicated)
│   ├── locations.py         # shared location service (cached, versioned)
│   ├── hotkey.py            # global keyboard hook (WH_KEYBOARD_LL)
│   ├── single_instance.py   # lockfile preventing duplicate instances
│   ├── config.py / paths.py # config persistence, frozen/source paths
│   ├── fileio.py            # atomic writes, corrupt-file quarantine
│   ├── theme.py / splash.py # HUD styling, startup splash
│   └── assets/              # fonts (Orbitron, Share Tech Mono), icons
├── modules/                 # one folder per module, auto-discovered
│   ├── commodity_prices/
│   ├── trade_route_optimizer/
│   ├── logistics_hub/       # OCR-based hauling contracts
│   │   ├── module.py
│   │   ├── ocr.py           # extracted OCR pipeline
│   │   └── gamelog_verify.py  # optional Game.log cross-check
│   ├── refinery_finder/
│   ├── multi_commodity_finder/
│   ├── crosshair/
│   ├── mobi_notes/
│   └── mobi_throttle/
├── tests/                   # regression tests (plain asserts, no framework)
├── docs/                    # architecture, decisions, module specs
├── mobioverlay.spec         # PyInstaller spec (single-file exe)
├── requirements.txt
├── config.json              # generated at runtime, git-ignored
└── locations_cache.json     # UEX cache (7-day TTL), git-ignored
```

---

## Documentation map

Read only what's relevant to your task:

| Doc | Purpose |
|-----|---------|
| `AGENTS.md` (this file) | First read — onboarding, safety rules, conventions |
| `docs/PROGRESS.md` | One-page status: version, shipped, open |
| `docs/HISTORY.md` | Session archive. Not the status |
| `docs/ARCHITECTURE.md` | Module contract, Core responsibilities, config schema |
| `docs/DECISIONS.md` | Dated log of choices + rationale (append-only) |
| `docs/BACKLOG.md` | Ranked module backlog with community-interest evidence |
| `docs/OPTIMIZATION.md` | Performance improvements (Q1-Q5, M1-M5, L1-L4) |
| `docs/modules/<name>.md` | Scope for one specific module (hyphenated: `modules/logistics_hub/` → `docs/modules/logistics-hub.md`) |
| `BUILD.md` | Build, test, and release instructions |
| `README.md` | End-user documentation |

**Start every session by reading `docs/PROGRESS.md`** (one page), then only the
docs relevant to your task. Do not start from `docs/HISTORY.md`.

---

## Running from source

```bash
# Clone and install (CPU-only torch to avoid 2GB CUDA bloat)
git clone https://github.com/h2mCoreAi/mobiOverlay.git
cd mobiOverlay
pip install torch torchvision --index-url https://download.pytorch.org/whl/cpu
pip install -r requirements.txt

# Run
python host/main.py
```

---

## Running tests

Plain asserts, no test framework dependency:

```bash
python tests/test_logistics_hub_parsing.py
```

This runs contract parsing fixtures, hauling resolution checks, distance
calculations, and UI state tests (if PySide6 is available).

Other test files:
- `python tests/test_api_client_dedupe.py` — UexApiClient deduplication
- `python tests/test_core_persistence.py` — config/cache recovery, atomic saves, rate-limit detection (no network)
- `python tests/test_pill_hover_unlock.py` — click-through pill hover-to-unlock (offscreen, no hooks)
- `python tests/test_mobi_notes_store.py` — mobiNotes data store

**Requirement**: `locations_cache.json` must exist (run the app once first, or
the test will fetch from UEX API).

---

## Building the exe

```bash
pip install pyinstaller
pyinstaller mobioverlay.spec --noconfirm
```

Output: `dist/mobiOverlay.exe` (~333 MB with CPU-only torch). True single-file —
all 8 modules bundled inside. `config.json` and cache files persist next to the exe.

---

## Branch/PR workflow

1. **Work on PR branches** — never commit directly to `master`
2. **Ask before pushing to `master`** — never push directly to `master`
   without the owner's explicit confirmation in the current session, even
   for docs-only commits
3. **Name branches**: `cursor/<descriptive-name>-<suffix>` (or similar prefix)
4. **Test side-by-side** before merge:
   - Build to a separate folder: `pyinstaller mobioverlay.spec --distpath dist-test`
   - Copy to test location, copy `config.json`, run alongside Star Citizen
   - **Never overwrite the owner's live installed exe** until approved
5. **Release flow**: tag `vX.Y.Z` on `master` → GitHub Actions publishes zip

---

## Coding conventions

- **PySide6/Qt** for all UI — no Tkinter, no web frameworks
- **Folder-per-module** under `modules/`, auto-discovered at startup
- **Module contract**: `module_id`, `display_name`, `create_card()`, `refresh()`,
  optional `shutdown()`
- **mobiOverlay Core never imports module internals** — only calls the contract
- **Shared services passed to modules**: `api_client`, `config`, `locations`
- **Config persistence**: modules touch only their own `modules.<id>` section
- **No code comments that just narrate** — comments explain non-obvious intent only
- **Docstrings** for public functions; skip obvious ones

---

## HARD SAFETY RULES

These rules are non-negotiable. Violating them can corrupt the owner's live
overlay, break Star Citizen input, or cause account issues.

### 1. Never force-kill Star Citizen processes

**Never** kill `StarCitizen.exe`, `EasyAntiCheat` service, `RSI Launcher`, or
any SC-related process. Only ever kill `mobiOverlay.exe` / `python.exe` running
mobiOverlay.

If SC keyboard input is wedged (WASD/menus unresponsive), the cause is usually
a leftover `WH_KEYBOARD_LL` hook from a crashed mobiOverlay. Fix:
1. Kill mobiOverlay (Task Manager → `mobiOverlay.exe` or `python.exe`)
2. Have the user quit Star Citizen normally and relaunch

**Never casually suggest "Character Repair"** — it has a 1-hour+ wait and can
have side effects. Only mention it if the user specifically asks about it.

### 2. Never leave the packaged overlay running unattended alongside SC

The global keyboard hook can interfere with exclusive-fullscreen games. If
you're testing and need to step away, close mobiOverlay first.

### 3. Never send global hotkey keystrokes while SC may be live

Don't use `keyboard.send()`, `keybd_event()`, or similar to inject keystrokes
into a running mobiOverlay instance while SC might be active — two instances
can race on the same `WH_KEYBOARD_LL` hook, and synthetic input can trigger
unintended game actions.

### 4. Never move the overlay onto the primary/gaming monitor

The owner's primary display is their active gaming monitor. Never reposition
the mobiOverlay window there for testing. Use `PrintWindow` to capture the
overlay's content without moving it.

### 5. Never embed a shared UEX token in the distributed app

The app uses only anonymous public API endpoints. Never add auth tokens,
API keys, or credentials to code that gets committed. If auth is needed for
a future feature, it must be user-provided in Settings.

### 6. Never invent game/API logic UEX doesn't compute

Don't write custom pathfinding, commodity prediction, or market analysis that
UEX's own API doesn't provide. The modules display UEX data as-is, with only
client-side filtering/sorting.

**Explicit, documented exception: Logistics Hub's route ordering.** UEX has
no "best order to visit these stops" endpoint, so Logistics Hub builds a
distance matrix from real `terminals_distances`/`orbits_distances` calls
and solves the stop order itself (greedy nearest-neighbor + 2-opt
improvement) — the distances are real UEX data, only the ordering logic is
ours. Scoped and justified in `docs/BACKLOG.md`'s "Multi-Stop Contract
Route Optimizer" entry; this is the one deliberate carve-out from this rule,
not a precedent for inventing logic elsewhere.

### 7. Never run two mobiOverlay instances at once

The single-instance guard exists for a reason. Don't bypass it. Check for
running instances before launching another:
```powershell
Get-CimInstance Win32_Process | Where-Object { $_.Name -eq 'mobiOverlay.exe' -or $_.CommandLine -like '*host*main.py*' } | Select-Object ProcessId, Name, CommandLine
```

---

## Key implementation details

### LocationService (`host/locations.py`)

- **Disk cache**: `locations_cache.json` with 7-day TTL
- **Cache versioning**: `CACHE_VERSION` (v2) — auto-invalidates on schema changes
- **Alias support**: `LOCATION_ALIASES` for in-game text → UEX name mapping
- **Endpoint tagging**: Every row tagged with `_endpoint` to prevent id collisions
  (terminals/space_stations/outposts/cities have independent id sequences)
- **Hauling resolution**: `resolve_for_hauling()` prefers Admin terminals, validates
  matches with fuzzy threshold, promotes structural records to Admin terminals

### UexApiClient (`host/api_client.py`)

- **Connection pooling**: `HTTPAdapter` with `pool_connections=10, pool_maxsize=10`
- **In-flight deduplication**: Concurrent calls share a `Future` (M5 optimization)
- **Short-TTL cache**: 2-second window prevents duplicate requests

### Global hotkey (`host/hotkey.py`)

- **WH_KEYBOARD_LL hook** via `keyboard` library (not `RegisterHotKey`)
- **Lazy install**: Hook not installed until a hotkey is configured
- **Teardown**: `shutdown()` + `atexit` safety net
- **Reconcile watchdog**: `GetAsyncKeyState` check every 1s to self-heal stuck keys

### Logistics Hub OCR (`modules/logistics_hub/ocr.py`)

- **Reader on main thread only** — QThread crashes Qt6Core.dll
- **Inference in `threading.Thread`** — `readtext()` is thread-safe
- **Signal bridge**: `_OcrSignalBridge` marshals results back to Qt
- **Preprocessing**: grayscale → 2x LANCZOS upscale → autocontrast
- **Column-aware**: `order_ocr_boxes()` splits at largest horizontal gap

---

## Common tasks

### Adding a new module

1. Create `modules/<name>/module.py` with a class implementing:
   - `module_id: str`
   - `display_name: str`
   - `create_card(parent) -> Card`
   - `refresh()`
   - `shutdown()` (optional)
2. Create `docs/modules/<name-with-hyphens>.md` with scope and design
3. Run from source to verify auto-discovery
4. Add to `mobioverlay.spec` if special data files needed (usually not)

### Debugging location resolution

1. Check `locations_cache.json` age and version
2. Run `resolve_for_hauling()` with the OCR text, inspect results
3. Check `LOCATION_ALIASES` for missing mappings
4. Look at `logistics_hub_debug.jsonl` for raw OCR + resolution trace

### Debugging hotkey issues

1. Check if the hook is installed: `_hotkey._hook is not None`
2. Run `reconcile()` manually to clear stuck state
3. Verify with `GetAsyncKeyState` that keys are physically up
4. Check for duplicate mobiOverlay instances

---

## Questions?

If something is unclear, check `docs/DECISIONS.md` for the rationale behind past
choices. If you need to make a new architectural decision, document it there
(append-only, dated entries).

For UEX API questions, see https://uexcorp.uk/api/2.0/docs/ — but remember:
**never invent logic UEX doesn't compute**.
