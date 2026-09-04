# Architecture

## Layout

```
mobiOverlay/
  host/            # main window, card container, config, module loader, HTTP client
  modules/
    <module_name>/ # one folder per module, auto-discovered
  docs/
  config.json       # generated at runtime, git-ignored
```

## Module contract

Each module folder exposes an entry point (e.g. `modules/<name>/module.py`)
with a single class the host can instantiate. That class must provide:

- `module_id: str` — unique, stable, used as the config namespace key
- `display_name: str` — shown in the card's header and the stow tray
- `settings_schema` — declares what config keys this module reads/writes
  (merged into `config.json` under `modules.<module_id>`)
- `create_card(parent) -> Card` — builds and returns this module's card widget
- `refresh()` — fetch/update data on its own schedule; runs inside the host's
  error boundary, so a failure here degrades only this module's card

The host never reaches into a module's internals beyond this contract. Adding
module #2 means adding a new folder under `modules/` — zero edits to `host/`
or to any other module.

## Host responsibilities

- Discover and load modules from `modules/` at startup; catch and isolate
  per-module import/init failures (log + show error card state, don't crash)
- Own the window: always-on-top, drag, resize, opacity
- Own the card container: free-form positioning, collapse/expand,
  stow/deploy via the tray panel, persist layout to `config.json`
- Own the shared UEX API client (base URL, bearer token, rate-limit handling)
  and hand it to modules rather than each module managing its own HTTP client
- Own `config.json` read/write; modules only touch their own namespaced section

## Config schema (config.json)

```json
{
  "ui": { "opacity": 0.9, "always_on_top": true, "window_geometry": {} },
  "api": { "uex_token": "", "uex_base_url": "https://api.uexcorp.uk/2.0/" },
  "cards": { "<card_id>": { "x": 0, "y": 0, "collapsed": false, "visible": true } },
  "modules": { "<module_id>": { } }
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
previous position/size. See `MainWindow.stow_app`/`deploy_app` in
`host/main_window.py`. A system-wide hotkey (`host/hotkey.py`, Win32
`RegisterHotKey` via `ctypes` — plain Qt shortcuts only fire while the
app has focus, useless for toggling while the game does) can trigger the
same stow/deploy toggle from Settings, meant for use while playing.

## Global hotkey (host/hotkey.py)

Uses the `keyboard` library's low-level global keyboard hook
(`WH_KEYBOARD_LL` via `SetWindowsHookEx`, installed once for the app's
life in `GlobalHotkey.__init__`), not Win32 `RegisterHotKey`/`WM_HOTKEY`.
`RegisterHotKey` was tried first and reliably failed to fire while Star
Citizen had focus — it delivers through the normal window message queue,
which a fullscreen/exclusive-input game can block. A low-level hook
intercepts the actual keyboard input stream below that queue, so it isn't
affected by which window Windows currently considers focused. This mirrors
ThrottleWatch (a separate, already-shipping SC overlay by the same
author), which never has this problem for exactly that reason — see
`throttle_watch.py`'s `HotkeyState` for the original this was ported from.

`HotkeyState` tracks one combo's pressed/held state from raw key up/down
events fed to it by the single shared hook (not `keyboard.add_hotkey`,
whose shared cross-hotkey pressed-keys dict is vulnerable to a permanently
stuck-down modifier if a single key-up event is ever lost — e.g. a UAC
prompt stealing focus mid-combo). A `reconcile()` watchdog (`GlobalHotkey`
runs it once/second via `QTimer`) self-heals stuck state by checking
`GetAsyncKeyState` against what the hook thinks is still held. Only one
hotkey exists right now (Stow/Deploy the whole app).

Because `keyboard.hook()`'s callback runs on the `keyboard` library's own
dispatch thread, never the Qt/GUI thread, `GlobalHotkey` is a `QObject`
with a `triggered` `Signal()` — emitting it from that thread is the
standard thread-safe way to marshal the actual callback (which touches Qt
widgets) back onto the GUI thread; Qt auto-queues a cross-thread signal
emission to whatever thread its connected slot lives on. This plays the
same role ThrottleWatch's `self.root.after(0, ...)` plays for Tk.

The capture UI (`_HotkeyField` in `main_window.py`) is click-to-arm: click
the field, press and release any combo (including a bare key, since this
hook only listens — `suppress=False` — rather than exclusively claiming
the key the way `RegisterHotKey` did). Capture itself is
`GlobalHotkey.capture_combo()`, which spawns a daemon thread calling
`keyboard.read_hotkey(suppress=False)` (blocks until a full press+release)
and reports the result back via another `Signal`, the same proven pattern
ThrottleWatch's Settings dialog uses. Escape is treated as cancel rather
than becoming the hotkey. Config stores the raw `keyboard`-library combo
string directly (`hotkey_combo`, e.g. `"f3"` or `"ctrl+alt+p"`) plus a
prettified `hotkey_display` for the UI.

## Packaging

PyInstaller. `host/` is bundled into the exe. `modules/` and `config.json`
are **not** — they live as real files next to the exe on disk, not frozen
inside it. This is a deliberate decision (2026-09-03, see DECISIONS.md):

- `modules/` external → adding/editing a module never requires rebuilding
  the exe, matching the original "drop a folder in, zero rebuild" goal.
  It also gives the community a way to audit what a module does (plain
  readable `.py`) before running it, which matters for an unsigned exe.
- `config.json` external → a PyInstaller onefile build extracts to a
  temp directory that's wiped and recreated every launch; anything written
  relative to that temp path would silently never persist between runs.

Both paths are resolved via `host/paths.py`'s `app_root()`: the exe's own
folder when frozen (`sys.frozen`), the project root when running from
source. Bundled, non-pluggable assets (fonts) keep using ordinary
`__file__`-relative paths — those are meant to travel inside the frozen
build, unlike modules/config.

Because `modules/` is external and not a real importable package once
frozen, the module loader imports each `modules/<name>/module.py` by file
path (`importlib.util.spec_from_file_location`), not as a dotted
`modules.<name>.module` package import — see `host/module_loader.py`.

Verify no personal machine paths get baked into the build or logged in
example configs before any public release.
