# Progress

## Status: host + 2 modules working; packaging + CI release pipeline set up

## Done

- Project pivoted from a Game.log combat-event overlay to a UEX-API-backed
  modular trading overlay (see DECISIONS.md for why)
- Host/module architecture decided: PySide6, folder-per-module, auto-discovery
- Doc structure scaffolded (this file, ARCHITECTURE.md, DECISIONS.md,
  modules/price-lookup.md)
- Visual design mocked up (dark sci-fi HUD, cyan/amber accents, Orbitron +
  Share Tech Mono) and approved as-is — see DECISIONS.md for the full value
  reference and the artifact link
- Verified UEX API field-level shapes with real live calls (no auth token
  needed for the GET endpoints this module uses): `commodities`,
  `commodities_prices`. `commodities_prices` rows come pre-joined with
  `terminal_name`/`star_system_name`/`planet_name`/`city_name` — no separate
  terminals lookup needed for this module.
- Fonts bundled: `host/assets/fonts/` (Orbitron 700/800/900, Share Tech Mono),
  both SIL OFL-licensed, downloaded from Google Fonts, license note included
- Host built: `host/main.py`, `config.py`, `api_client.py`, `module_base.py`,
  `module_loader.py`, `card.py`, `card_container.py`, `main_window.py`,
  `theme.py` — always-on-top frameless window, opacity slider, draggable
  title bar, free-form draggable/collapsible/closable cards, card picker,
  config persistence (layout + module settings), per-module auto-discovery
  from `modules/`, per-module error boundary (a failed refresh puts that
  card into its error state with a retry button, doesn't crash the host)
- Price Lookup module built and working: `modules/price_lookup/module.py` —
  commodity picker, best-sell/best-buy rows with terminal+location, last
  updated timestamp, manual refresh button, periodic auto-refresh
- Ran the actual app and screenshotted it (via PrintWindow — CopyFromScreen
  proved unreliable on this machine's multi-monitor setup, see note below):
  title bar, card chrome, and live data all rendered correctly, config.json
  persistence confirmed (watched_commodity, card layout state)
- Added independent per-row star-system filters (Best Sell and Best Buy each
  get their own "All Systems"/system dropdown, populated from the fetched
  price rows, persisted separately in config) — e.g. buy in Stanton while
  selling in Pyro
- Made the main window resizable: QSizeGrip in a footer strip, card
  container set to expand, window size now persisted alongside position
- Fixed a real bug hit while adding the above: cards built their size before
  the module populated `card.body`, and since `CardContainer` has no layout
  manager nothing resized them afterward — cards rendered as header-only.
  Fixed by forcing `layout().activate()` + `resize(layout().sizeHint())`
  after population, and in `set_collapsed`/`set_error`/`clear_error` too
  (same staleness risk on every visibility toggle)
- Two-tone wordmark: "MOBI" in primary text color, "OVERLAY" in cyan accent,
  matching the original approved mockup (the first host build had missed
  this detail — single-color instead)
- Wordmark now reads "MOBIOVERLAY by Kestryl" — the "by Kestryl" portion at
  half the font size, in muted text color
- Fixed a real first-load bug (user-reported): a card sometimes rendered
  header-only until you manually collapsed and re-expanded it. Root cause
  still not 100% pinned down (suspect layout/font-metric settling on very
  first paint), but fixed pragmatically with a belt-and-suspenders re-apply:
  `card.apply_size()` runs once right after population (as before) AND again
  50ms after `window.show()`, once the window has actually painted — see
  `main.py`'s `_resettle_cards`. Confirmed fixed on a fresh-config run with a
  realistic ~2s startup delay (previous verification used an artificial 4-5s
  delay that likely papered over the race)
- Cards are now individually resizable: a small drag handle (diagonal cyan
  lines) in each card's bottom-right corner. Width always sticks once
  manually set; height sticks only while expanded and error-free — collapse
  and error states always use their own natural minimal height. Manual size
  persists per-card to config (`cards.<id>.width/height`) and is restored
  on relaunch
- Cards now snap to a grid when dragged: a purple-bordered/tinted preview
  (mimicking SC's in-game cargo-grid styling) shows the snap target while
  dragging; on release the card jumps to that grid-aligned position.
  Grid size and snap colors are in `theme.py` (`GRID_SIZE`, `SNAP_BORDER`,
  `SNAP_FILL`).
  **User-tested 2026-09-03: doesn't behave as expected.** User has accepted
  it as-is for now, no changes requested — leave alone unless asked. Exact
  mismatch not diagnosed (not reproduced/debugged this session).
- Fixed the window defaulting onto the primary/gaming monitor: the previous
  hardcoded `(100, 100)` fallback landed on whichever screen is primary —
  which is the user's active gaming display. Default launch position (used
  only when no saved position exists) now targets a non-primary monitor via
  `QGuiApplication.screens()`, falling back to primary only if there's
  genuinely one screen. Confirmed by checking the real window rect after a
  fresh launch (x=2148, the secondary monitor) without ever moving it there
- Researched community interest and ranked the full module backlog — see
  docs/BACKLOG.md
- Second module built: Trade Route Optimizer
  (`modules/trade_route_optimizer/module.py`) — see
  docs/modules/trade-route-optimizer.md. Cascading system → terminal picker
  (only Stanton/Pyro/Nyx shown — the only `is_available` systems), optional
  investment budget, top 5 routes by profit using UEX's pre-computed
  `commodities_routes` data. Verified with two real modules loaded together
  (host correctly discovers and runs both from `modules/`)
- Decided modules ship external to the exe, not bundled — see DECISIONS.md.
  Required switching the module loader to file-path imports and adding
  `host/paths.py` for frozen-vs-source path resolution (config.json needed
  the same fix, same root cause: a frozen onefile build's temp dir doesn't
  persist between launches)
- Packaging set up and verified end-to-end: `mobioverlay.spec`
  (PyInstaller, onefile+windowed), initialized this project's own git repo
  (separate from the `C:\Users\mhoward` home-directory repo — see
  DECISIONS.md), `.github/workflows/release.yml` (builds on tag push,
  publishes a GitHub Release with the exe+modules zipped and a SHA256
  checksum), `BUILD.md` (identical manual steps for self-compiling).
  Actually built and ran the packaged exe locally with an external
  `modules/` folder next to it — confirmed fonts, both modules, live data,
  and config persistence all work correctly in the frozen build

## Next

- Human review of the running app (this is the current handoff point)
- Grid-snap drag and per-card resize handle are code-reviewed and
  screenshot-confirmed to render, but not yet mouse-drag-tested by a human
- Confirm UEX bearer token is genuinely optional for the long term (GET
  endpoints work anonymously today, but that could change) — not blocking
  for now
- No packaging (PyInstaller) attempted yet — still running from source

## Environment / process notes

- Screenshotting a running Windows app from this session is unreliable via
  naive `CopyFromScreen` — this machine has two monitors plus several
  overlapping large windows (Claude Code, browser, Discord), and window
  z-order/position reported by `GetWindowRect` didn't match what
  `CopyFromScreen` actually captured (likely DPI virtualization). Capturing
  the target window directly via the `PrintWindow` Win32 API (with
  `PW_RENDERFULLCONTENT`) sidesteps this entirely and is what worked.
- **Never reposition the app window onto the primary monitor for testing
  purposes** — that's the user's active gaming display. `PrintWindow`
  captures a window's content regardless of its on-screen position or
  z-order, so there's no need to move the window at all to screenshot it.
  An earlier testing pass violated this by using `SetWindowPos` to drag the
  live window onto the gaming monitor repeatedly — don't do that again.

## Backlog

Full ranked module backlog (22 candidates, ranked by researched community
interest, not just endpoint availability) lives in **docs/BACKLOG.md**.
Write a `docs/modules/<name>.md` when a module is picked up from it.
Current top pick: Trade Route Optimizer (`commodities_routes`).
