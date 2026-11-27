# AI Agent Onboarding — mobiOverlay

This is the canonical onboarding file for any AI agent (Claude, GPT, Cursor,
Aider, etc.) working on mobiOverlay. Read this first, then dive into specific
docs as needed.

---

## What is mobiOverlay?

A modular, always-on-top Star Citizen data overlay styled after the in-game
MobiGlas. Dark sci-fi HUD with cyan/amber accents.

**Vision (owner-confirmed 2026-11-27):** a fast, safe, read-only Star Citizen
companion HUD. It shows trade and economy data (UEX) and a verified leveling
guide in a draggable overlay. It never touches the game: no memory reads, no
input injection, no telemetry.

**Audience:** any Star Citizen player. The repo is public and MIT-licensed,
and GitHub Actions publishes release zips. The owner (TheRealKestryl) is the
only developer and tester and its first user, so "works on the owner's
machine next to a live game" is the bar every change has to clear.

### Data charter

- **Runtime data comes only from the [UEX Corp API](https://uexcorp.uk/)**,
  displayed as-is with client-side filtering and sorting. Anonymous public
  endpoints only; no embedded token (a user's own token in `config.json`,
  `api.uex_token`, is optional).
  No network calls except UEX, plus EasyOCR's one-time model download on the
  first Logistics Hub scan.
- **Static content packs** (mobiGuide) ship as JSON. Contract catalogs are
  generated offline by `scripts/build_contract_catalog.py` from SCMDB and
  the star-citizen.wiki API, cross-checked and stamped with the game build.
  Chapter facts are hand-checked against named sources (RSI Knowledge Base
  and others), listed in `docs/leveling-guide/verification.md`. The app
  never calls those sources at runtime; mobiGuide's only network call is
  UEX ship prices.
- **Nothing is computed that the game or UEX doesn't provide.** The one
  carve-out is Logistics Hub's route ordering (safety rule 6).
- **Game.log** is read only by Logistics Hub's one-shot check when you press
  ACCEPT, on the user's own file. Owner decision 2026-11-27: it becomes a
  true opt-in (off unless the user turns it on). **Today's code still falls
  back to the default LIVE install path when no path is set**, so it runs
  whenever that file exists; the fix is planned work in `docs/PROGRESS.md`.
  mobiGuide never reads Game.log: completion is manual only.

### Related projects

- **ThrottleWatch:** the owner's earlier standalone Tkinter throttle overlay.
  mobiThrottle and `host/hotkey.py` were ported from it.
- **[h2mCoreAi/mobiThrottle](https://github.com/h2mCoreAi/mobiThrottle):**
  mobiThrottle split out into its own app (PR #17, 2026-10-30). The
  `modules/mobi_throttle/` folder on `claude/leveling-guide` is a leftover
  that is dropped when that branch rebases onto `master`.
- **SubliminalsTV-Projects/sc-overlay:** a third-party app that reads
  hauling data live from Game.log. Its documented log line shapes were
  studied and confirmed against the owner's own log, and Logistics Hub's
  one-shot check is its own Python implementation (DECISIONS 2026-09-08).
  mobiOverlay deliberately doesn't replicate its live tracking or payouts.

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
│   ├── services.py          # Services: the shared objects handed to modules
│   ├── background.py        # run blocking calls off the GUI thread
│   ├── refresh.py           # per-module refresh: error boundary, worker thread, timer pause
│   ├── price_cache.py       # SQLite cache for bulk price data
│   ├── theme.py / splash.py # HUD styling, startup splash
│   └── assets/              # fonts (Orbitron, Share Tech Mono), icons
├── modules/                 # one folder per module, auto-discovered
│   ├── commodity_prices/
│   ├── trade_route_optimizer/
│   ├── logistics_hub/       # OCR-based hauling contracts
│   │   ├── module.py        # card + orchestration
│   │   ├── ocr.py           # OCR pipeline
│   │   ├── parsing.py       # contract-text parsing (pure)
│   │   ├── routing.py       # route ordering: greedy + 2-opt + Or-opt
│   │   ├── grading.py       # contract score, freight manifest
│   │   ├── popups.py        # review / profile / region / banner widgets
│   │   ├── results_view.py  # contracts / manifest / route rendering, route popout
│   │   └── gamelog_verify.py  # optional Game.log cross-check
│   ├── refinery_finder/
│   ├── multi_commodity_finder/
│   ├── crosshair/
│   ├── mobi_notes/
│   ├── leveling_guide/      # mobiGuide: per-patch packs in packs/<id>/ (see docs/modules/leveling-guide.md)
│   └── mobi_throttle/       # retired: lives in h2mCoreAi/mobiThrottle; dropped on rebase onto master
├── tests/                   # regression tests (plain asserts, no framework)
│   └── run_all.py           # runs every test file, one summary
├── scripts/                 # git hook, decisions_index.py
├── docs/                    # architecture, decisions, module specs
├── mobioverlay.spec         # PyInstaller spec (onedir: exe + _internal/)
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
| `docs/DECISIONS.md` | Dated log of choices + rationale (append-only). Too long to read whole: `python scripts/decisions_index.py <keyword>` lists matching entries with line numbers |
| `docs/BACKLOG.md` | Ranked module backlog with community-interest evidence |
| `docs/OPTIMIZATION.md` | Performance work: Q, M, L, N and P items, with status |
| `docs/modules/<name>.md` | Scope for one specific module (hyphenated: `modules/logistics_hub/` → `docs/modules/logistics-hub.md`) |
| `docs/leveling-guide/` | mobiGuide research and `verification.md` (every checked game claim) |
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

Plain asserts, no test framework dependency. Run everything (offscreen Qt,
UTF-8 output, one summary, non-zero exit on any failure):

```bash
python tests/run_all.py            # every suite
python tests/run_all.py logistics  # only files whose name contains a word
```

Each file also runs on its own, e.g. `python tests/test_logistics_hub_parsing.py`
(contract parsing fixtures, hauling resolution, distances, UI state).

Test files:
- `python tests/test_api_client_dedupe.py` — UexApiClient deduplication
- `python tests/test_core_persistence.py` — config/cache recovery, atomic saves, rate-limit detection (no network)
- `python tests/test_pill_hover_unlock.py` — click-through pill hover-to-unlock (offscreen, no hooks)
- `python tests/test_mobi_notes_store.py` — mobiNotes data store
- `python tests/test_leveling_guide.py` — mobiGuide content, progress store, offscreen card
- `python tests/test_logistics_hub_routing.py` — route ordering (no Qt, no network)
- `python tests/test_services.py` — shared Services wiring
- `python tests/test_background_scans.py` — worker-thread scan loops (offscreen, fake API)
- `python tests/test_mobi_throttle_reconnect.py` — mobiThrottle joystick re-init only when needed (no Qt window, no device)
- `python tests/test_price_cache.py` / `python tests/test_commodity_prices_cache.py` — SQLite price cache and its restore/save in Commodity Prices
- `python tests/test_module_refresher.py` — module refresh on a worker thread, stale-response drop, timer pause while hidden
- `python tests/test_taskbar_restore.py` — tray Show / hotkey / Stow on a minimized window (offscreen)

**Requirement**: `locations_cache.json` must exist (run the app once first, or
the test will fetch from UEX API).

---

## Building the exe

```bash
pip install pyinstaller
pyinstaller mobioverlay.spec --noconfirm
```

Output: `dist/mobiOverlay/` (~333 MB with CPU-only torch) — `mobiOverlay.exe`
plus `_internal/` (every folder under `modules/`). Keep the folder together.
`config.json` and cache files persist next to the exe.

---

## Branch/PR workflow

1. **Work on PR branches** — never commit directly to `master`
2. **Ask before pushing to `master`** — never push directly to `master`
   without the owner's explicit confirmation in the current session, even
   for docs-only commits
3. **Name branches**: `<agent>/<topic>` — e.g. `claude/taskbar-restore`, `cursor/item-lookup`
4. **Test side-by-side** before merge:
   - Build to a separate folder: `pyinstaller mobioverlay.spec --distpath dist-test`
   - Copy to test location, copy `config.json`, run alongside Star Citizen
   - **Never overwrite the owner's live installed exe** until approved
5. **Release flow**: tag `vX.Y.Z` on `master` → GitHub Actions publishes zip

---

## Working with multiple agents

Several agents (Claude, Cursor, Codex, ...) may work on this repo at the same
time, each on its own branch or worktree. These rules keep their work from
colliding:

1. **Claim before you start.** Add a row to the "In flight" table in
   `docs/PROGRESS.md` (agent, branch, area/files) in your first commit, and
   remove it when the PR merges or is abandoned. If your area overlaps a
   claimed row, pick other work or ask the owner.
2. **One task per branch**, named `<agent>/<topic>`. Branch from `master`.
   If you must stack on an unmerged branch, say so in the PR description.
3. **Parallel-safe units:** one module folder (`modules/<name>/`) with its
   `docs/modules/<name>.md` and its `tests/test_<name>*.py`. Logistics Hub is
   split by concern (`parsing.py`, `routing.py`, `grading.py`, `popups.py`,
   `results_view.py`, `ocr.py`, `gamelog_verify.py`), so two agents can work
   in it if they claim different files.
4. **One agent at a time (hot spots):** `host/main_window.py`, `host/main.py`,
   `host/module_base.py` and `host/refresh.py` (the module contract),
   `host/config.py` (config schema), `mobioverlay.spec`, `.github/workflows/`.
   A contract or schema change also needs a `docs/DECISIONS.md` entry.
5. **Shared docs that merge cleanly:** append new `docs/DECISIONS.md` entries
   at the end only. Add a new section to `docs/HISTORY.md` and don't edit
   others. In `docs/PROGRESS.md`, edit only your own rows and lines.
6. **Before pushing:** `python tests/run_all.py` must pass. New behavior gets a
   test (plain asserts, offscreen Qt, fake API, no network).
7. **Running the app:** only one instance can exist on the machine (lock file
   and global keyboard hook). Check first (safety rule 7). If the owner's or
   another agent's instance is running, or Star Citizen is, verify with the
   offscreen tests instead of launching.
8. **Finding past decisions:** `python scripts/decisions_index.py <keyword>`
   prints matching entries with line numbers. Read only those entries, at
   that offset.

---

## Coding conventions

- **PySide6/Qt** for all UI — no Tkinter, no web frameworks
- **Folder-per-module** under `modules/`, auto-discovered at startup
- **Module contract**: `module_id`, `display_name`, `create_card()`, `refresh()`,
  optional `shutdown()`. A module that calls UEX should also implement
  `refresh_job()`/`finish_refresh()` so the request runs off the GUI thread
  (see `docs/ARCHITECTURE.md`, Module contract)
- **mobiOverlay Core never imports module internals** — only calls the contract
- **Shared services passed to modules**: `api_client`, `config`, `locations` (also bundled as `self.services`, see `host/services.py`)
- **Config persistence**: modules touch only their own `modules.<id>` section.
  Use `config.set_module_settings()` (debounced) for settings that change in
  bursts; `config.save()` writes at once
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

### 4. Never move the overlay onto the primary/gaming monitor while testing

This is a rule for agents testing on the owner's machine. The owner's primary
display is their active gaming monitor. Never reposition the mobiOverlay
window there for testing. Use `PrintWindow` to capture the overlay's content
without moving it.

It is not a product rule. The product default is a non-primary monitor
(`_default_launch_position()` in `host/main_window.py`), users may drag the
overlay anywhere, and Crosshair draws on the primary display by design
(click-through, it never moves the window). An in-game mobiGuide strip on
the primary monitor is deferred: it needs its own owner decision and
DECISIONS entry before anyone builds it.

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

mobiGuide's recommendations (best contracts for a rank or goal, "≈N to go")
are sorting and filtering of game-file values from its static packs, not
invented logic. See `docs/modules/leveling-guide.md`, Data and honesty rules.

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
