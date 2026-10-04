# Architecture

## Layout

```
mobiOverlay/
  host/            # mobiOverlay Core: main window, card container, config,
                   # module loader, API client, location service, hotkey, tray
  modules/
    <module_name>/ # one folder per module, auto-discovered at startup
      module.py    # entry point class implementing the module contract
  tests/           # regression tests (plain asserts, no framework)
  docs/            # this folder — architecture, decisions, module docs
  config.json      # generated at runtime, persists next to exe, git-ignored
  locations_cache.json  # UEX location cache (7-day TTL), git-ignored
```

## Module contract

Each module folder exposes an entry point (e.g. `modules/<name>/module.py`)
with a single class mobiOverlay Core can instantiate. That class must provide:

- `module_id: str` — unique, stable, used as the config namespace key.
  mobiOverlay Core validates this is a non-empty string at load time and
  rejects a second module that claims an already-used id.
- `display_name: str` — shown in the card's header and the stow tray
- `create_card(parent) -> Card` — builds and returns this module's card widget.
  Must return an actual `host.card.Card` instance — Core validates the
  return type and skips the module (with a logged error) otherwise.
- `refresh()` — fetch/update data on its own schedule; runs inside mobiOverlay
  Core's error boundary, so a failure here degrades only this module's card
- `shutdown()` — optional cleanup hook called by `app.aboutToQuit` for every
  module before process exit (e.g. release hotkeys, close file handles)

mobiOverlay Core never reaches into a module's internals beyond this
contract. Adding module #2 means adding a new folder under `modules/` —
zero edits to `host/` or to any other module.

## mobiOverlay Core responsibilities

- Discover and load modules from `modules/` at startup; catch and isolate
  per-module import/init failures (log + show error card state, don't crash)
- Own the window: always-on-top, drag, resize, opacity
- Own the card container: free-form positioning, collapse/expand,
  stow/deploy via the tray panel, persist layout to `config.json`
- Own the shared UEX API client (base URL, rate-limit handling) and hand it
  to modules rather than each module managing its own HTTP client. Requests
  are anonymous; `api.uex_token` is sent as a bearer token only if the user
  puts their own token in `config.json` (no Settings field, never shipped)
- Own the shared LocationService (see below) for UEX location data
- Own `config.json` read/write; modules only touch their own namespaced section
- Own the single-instance guard preventing duplicate overlay processes
- Own the system tray icon for overlay recovery when minimized/hidden
- Own the global hotkey (Stow/Deploy) and its low-level keyboard hook

## LocationService (host/locations.py)

Shared UEX location data — star systems, terminals, space stations, outposts,
and cities — used by any module that needs to resolve, search, or display a
real Star Citizen place. One shared instance is created by `host/main.py` and
passed to all modules at discovery time.

Key features:
- **Disk cache**: `locations_cache.json` next to `config.json`, 7-day TTL
  (`CACHE_MAX_AGE_SECONDS`), auto-refreshes from live UEX API when stale
- **Cache versioning**: `CACHE_VERSION` (currently v2) — stale-versioned caches
  auto-invalidate on load, forcing a fresh API fetch when the schema changes
- **Alias support**: `LOCATION_ALIASES` dict maps known in-game text variations
  to UEX names (e.g. "Beautiful Glen Station" → "CRU-L5 Beautiful Glen Station")
- **Hauling-contract resolution**: `resolve_for_hauling()` prefers Admin terminals
  (the actual cargo kiosks) over structural space_station/outpost/city records;
  `resolve_fuzzy_for_hauling()` adds fuzzy matching with Admin promotion
- **Availability filtering**: `available_locations()` / `available_terminals()`
  filter to only in-game-usable locations for user-facing pickers
- **Real travel distance**: `distance(a, b)` uses `terminals_distances` (point-
  to-point) or `orbits_distances` (orbit-level fallback), queried lazily and
  cached per-session
- **Commodities cache**: `commodities()` fetches the commodity list once per
  session, shared across modules (Q2 optimization)

**Endpoint tagging**: `terminals`, `space_stations`, `outposts`, and `cities`
each have independent id sequences on UEX's side. Every row is tagged with its
source endpoint (`_endpoint`), and every dedup/lookup uses `(endpoint, id)`,
never a bare id. This was a real bug that silently collided unrelated locations.

## UexApiClient (host/api_client.py)

Shared HTTP client for all UEX API access. Key features:
- **Connection pooling**: `HTTPAdapter` with `pool_connections=10, pool_maxsize=10`
  reuses TCP connections across requests (Q3 optimization)
- **In-flight request deduplication**: Concurrent calls for the same endpoint+params
  share a single `Future` — only one HTTP request fires (M5 optimization)
- **Short-TTL cache**: Completed results are reused for 2 seconds
  (`DEDUPE_TTL_SECONDS`), preventing duplicate API calls on rapid refreshes
- **Rate-limit awareness**: `UexRateLimitError` raised when UEX reports
  `requests_limit_reached`, distinct from generic `UexApiError`

## Config schema (config.json)

```json
{
  "ui": {
    "window_opacity": 0.92,
    "card_opacity": 0.94,
    "font_scale": 1.15,
    "window_geometry": { "x": 100, "y": 100, "width": 400, "height": 600 },
    "pill_geometry": { "x": 100, "y": 100 },
    "pre_stow_geometry": { "x": 100, "y": 100, "width": 400, "height": 600 },
    "pill_click_through": false,
    "always_on_top": true,
    "show_console": false,
    "hotkey_combo": "",
    "hotkey_display": ""
  },
  "api": { "uex_token": "", "uex_base_url": "https://api.uexcorp.uk/2.0/" },
  "cards": { "<card_id>": { "x": 0, "y": 0, "collapsed": false, "visible": true } },
  "modules": { "<module_id>": { } },
  "shared": { "current_location_name": "", "current_location": null }
}
```

## Card system

A reusable `Card` base widget (not one-off per module): title bar (click to
collapse/expand), a Stow button, drag-to-reposition, resize handle,
consistent HUD styling. Modules subclass or compose this to render their
own content in the body.

Stow/Deploy replaces generic "hide/show" language on purpose — matches
Star Citizen's own in-game vocabulary (stowing a weapon, stowing cargo)
rather than desktop-UI conventions. Stowing a card (the header's Stow
button) hides it without destroying its state; the title bar's TRAY
button opens a small MobiGlas-style panel listing every stowed card,
click one to deploy it back onto the board. See `host/card_container.py`
(`stow_card`/`deploy_card`/`stowed_cards`) and `host/main_window.py`
(`_TrayPanel`).

The same Stow/Deploy vocabulary applies to the whole app, not just
individual cards: the title bar's minimize button (`▬`) shrinks the
entire window down to a small pill (just the wordmark + close button,
still always-on-top), and clicking that pill restores it to its exact
previous position/size — the pill's own position is remembered
independently too, so dragging it around survives re-stowing (see
`save_current_position()`). See `MainWindow.stow_app`/`deploy_app` in
`host/main_window.py`.

**Gap-aware pill positioning**: `_ensure_on_screen()` validates pill position
against actual monitor geometry, handling multi-monitor gaps (e.g. a 512px
horizontal gap between monitors). If the pill would land in a gap or off-screen,
it's clamped to a visible area with a 10px margin.

**Pill click-through**: `pill_click_through` setting (default OFF) controls
whether the stowed pill passes mouse events through to the game via
`WS_EX_TRANSPARENT`. When ON, the pill unlocks on hover: a `QTimer`
(`PILL_HOVER_POLL_MS`, 100 ms) checks the cursor position, and after it
has rested on the pill for `PILL_HOVER_UNLOCK_MS` (700 ms) click-through is
cleared and the title bar lights up (tint and border painted in `MainWindow.paintEvent`; `_TitleBar` has no `WA_StyledBackground`, so stylesheet rules on it never render). The pill is then
clickable (redeploy) and draggable until the cursor leaves. The timer only
runs while stowed with click-through ON, and the window style changes only
on lock/unlock, never per poll. Measured at ~2 µs per check. A global
mouse hook was deliberately not used, since it would sit in the path of
every in-game mouse movement. The hotkey and tray still redeploy as before.

**Native taskbar minimize/maximize (2026-09-30):** `MainWindow`'s window
flags changed from `Qt.Tool` to `Qt.Window | Qt.WindowMinMaxButtonsHint`
(alongside the existing `Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint`),
so it now gets a real Windows taskbar entry and icon. Two new title-bar
buttons (`🗕` OS-minimize, `🗖`/`🗗` maximize/restore) sit alongside the
existing Stow-to-pill (`▬`) button — three distinct ways to get the window
out of the way, each with a different purpose: Stow shrinks to the small
pill (still always-on-top, toggleable by hotkey even while the game has
focus); OS-minimize sends it to the taskbar like any normal window;
Maximize fills the screen. Double-clicking the title bar also toggles
maximize. `MainWindow.toggle_maximize()` explicitly captures pre-maximize
geometry before calling `showMaximized()`, since `resizeEvent`'s normal
geometry-save path skips saving while `isMaximized()` is true (a maximized
fill-screen size must never overwrite the user's real restored size).
This **supersedes** the original "`Qt.Tool` deliberately excludes the
overlay from the taskbar" reasoning behind the system tray icon below
(see DECISIONS.md, 2026-09-20) — the tray icon remains as an additional
recovery affordance, just no longer the *only* one.

## System tray icon (host/main_window.py)

A Windows system tray icon (`QSystemTrayIcon`) provides overlay recovery when
the main window is minimized/stowed or if the pill lands somewhere invisible.
Menu options: Show, Stow, Quit. Double-click also shows the window.
Icon file: `host/assets/icons/mobioverlay.png`.

## Single-instance guard (host/single_instance.py)

Prevents running two mobiOverlay copies at once. Holds an exclusive lock
(`msvcrt.locking`) on `.mobioverlay.lock` next to the exe for the process's
lifetime. If another instance holds it, shows an error dialog and exits. This
prevents duplicate global keyboard hooks from racing on the same hotkey.
The lock is released at exit, and by `MainWindow.relaunch()` before it starts
the new process (see "Exit paths" below).

## Exit paths

- **✕ / tray Quit**: `MainWindow.closeEvent` saves geometry, unhooks the
  hotkey, and calls `QApplication.quit()` explicitly. `host/main.py` sets
  `quitOnLastWindowClosed(False)` (so closing a module popout can't quit the
  app), which means closing the main window alone would otherwise leave an
  invisible process running.
- **Relaunch**: ends with `os._exit()`, which skips `aboutToQuit` and
  `atexit`. Cleanup that must still happen (every module's `shutdown()`,
  the single-instance lock) is registered with `MainWindow.add_before_exit()`
  and runs before the new process is spawned.

## Persistent files

`config.json`, `mobinotes_data.json`, and `locations_cache.json` are written
with `host/fileio.atomic_write_text()` (temp file + `os.replace`), so a crash
mid-save can't truncate them. A file that fails to parse is moved aside to
`<name>.corrupt-<timestamp>` by `quarantine_corrupt()` instead of being
overwritten by the next save. The location cache is only written after a
complete UEX fetch; a failed or partial fetch falls back to the older cache
and is retried (at most every 5 minutes) on the next lookup.

## Background calls and the price cache

`host/background.py` runs a blocking call (a UEX request) on a small thread
pool and delivers the result on the GUI thread; the three scan loops use it
so a slow response never freezes the UI (see OPTIMIZATION.md, L3).
`host/price_cache.py` is a SQLite key/value cache (`price_cache.sqlite3`) used
by Commodity Prices to keep its bulk price download across restarts (N3).

## Global hotkey (host/hotkey.py)

Uses the `keyboard` library's low-level global keyboard hook
(`WH_KEYBOARD_LL` via `SetWindowsHookEx`), not Win32 `RegisterHotKey`/`WM_HOTKEY`.
`RegisterHotKey` was tried first and reliably failed to fire while Star
Citizen had focus — it delivers through the normal window message queue,
which a fullscreen/exclusive-input game can block. A low-level hook
intercepts the actual keyboard input stream below that queue, so it isn't
affected by which window Windows currently considers focused.

**Lazy hook install**: The hook is NOT installed in `__init__` — it's installed
lazily on the first `set_hotkey()` call. A user running with no global hotkey
configured never even has a `WH_KEYBOARD_LL` hook installed.

**Teardown safety**: `GlobalHotkey.shutdown()` fully releases the OS-level hook
before process exit. An `atexit` handler provides a belt-and-suspenders safety
net. A hook that outlives its process can block game input (~5s Windows timeout).

`HotkeyState` tracks one combo's pressed/held state from raw key up/down
events fed to it by the single shared hook. A `reconcile()` watchdog runs
once/second via `QTimer`, self-healing stuck state by checking `GetAsyncKeyState`
against what the hook thinks is still held.

Because `keyboard.hook()`'s callback runs on the `keyboard` library's own
dispatch thread, never the Qt/GUI thread, `GlobalHotkey` is a `QObject`
with a `triggered` `Signal()` — emitting it from that thread is the
standard thread-safe way to marshal the actual callback back onto the GUI thread.

The capture UI (`_HotkeyField` in `main_window.py`) is click-to-arm: click
the field, press and release any combo. Capture uses
`GlobalHotkey.capture_combo()`, which spawns a daemon thread calling
`keyboard.read_hotkey(suppress=False)` and reports the result back via a Signal.
Config stores the raw `keyboard`-library combo string (`ui.hotkey_combo`,
e.g. `"f3"` or `"ctrl+alt+p"`, default `""` — no hotkey until the user sets
one) plus a prettified `ui.hotkey_display` for the UI.

## Logistics Hub OCR (modules/logistics_hub/ocr.py)

The OCR pipeline for reading hauling contract text from screen captures:

**Threading model (M2 optimization)**:
- `easyocr.Reader()` is created on the **main thread** only (first scan blocks
  ~2.8s while loading). Creating it in a QThread crashes Qt6Core.dll due to
  PyTorch/OpenMP initialization conflicts with Qt's threading model on Windows.
- Inference (`readtext()`) runs in a plain `threading.Thread`, safe from any thread.
- `_OcrSignalBridge` (QObject on main thread) marshals results back via Qt signals.

**Pipeline**:
1. `preprocess_image()`: grayscale, 2x LANCZOS upscale, autocontrast
2. `run_ocr()`: EasyOCR inference with `OCR_ALLOWLIST` character restriction
3. `order_ocr_boxes()`: column-aware reading order (splits at largest horizontal
   gap if wide enough, reads left column before right)

**Lazy import**: `easyocr` and `torch` are imported only on first scan use,
not at module load time, avoiding the 2.8s import cost for users who never
use Logistics Hub (M1 optimization).

## mobiThrottle home chirp (modules/mobi_throttle/module.py)

Uses `pygame.mixer` (SDL_mixer under the hood) instead of `winsound.Beep()`
for the home-position audio chirp. `winsound.Beep()` uses the legacy Windows
PC speaker which doesn't play when a game has exclusive audio focus. pygame.mixer
routes through WASAPI shared-mode, working alongside Star Citizen's audio.

The mixer is initialized lazily on first chirp (22050 Hz, mono, 512-sample buffer).
Multi-beep sequences use `QTimer.singleShot` scheduling instead of `time.sleep`.

## Packaging

PyInstaller onefile build — **everything in one exe**. The distinction:

- **Bundled inside the exe** (extracted to `sys._MEIPASS` at runtime):
  - `host/` — the core application
  - `modules/` — all 8 modules (discovered via `host/paths.modules_root()`)
  - `host/assets/fonts/` — bundled fonts (Orbitron, Share Tech Mono)
  - `host/assets/icons/` — tray icon
  - All dependencies (torch, easyocr, pygame-ce, etc.)

- **Persisted next to the exe** (via `host/paths.app_root()`):
  - `config.json` — layout and settings
  - `mobinotes_data.json` — mobiNotes storage
  - `locations_cache.json` — UEX location cache (7-day TTL, versioned; an expired one is served at once and refreshed in the background)
  - `price_cache.sqlite3` — Commodity Prices' last RETRIEVE DATA result
  - `logistics_hub_debug.jsonl` — Logistics Hub debug log
  - `logistics_hub_completed.jsonl` — completed hauling contracts log

The split matters because PyInstaller's onefile temp extraction directory
is wiped and recreated every launch — anything written there never persists.

`host/paths.py` exposes:
- `app_root()` — exe folder when frozen, project root from source
- `modules_root()` — `sys._MEIPASS/modules` when frozen, `modules/` from source

The module loader (`host/module_loader.py`) uses `modules_root()` for
discovery and imports each `modules/<name>/module.py` by file path
(`importlib.util.spec_from_file_location`).

**Build output**: `dist/mobiOverlay.exe` (~333 MB with CPU-only torch, larger
with CUDA). Build command: `pyinstaller mobioverlay.spec --noconfirm`.

**Development workflow**: When running from source, modules are in the
normal `modules/` folder and can be edited live. The frozen exe bundles
whatever's in `modules/` at build time.
