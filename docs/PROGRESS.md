# Progress

## Status: Retrieve/Find split with countdown+force-update, Settings Relaunch button; awaiting human test

## Done

- Project pivoted from a Game.log combat-event overlay to a UEX-API-backed
  modular trading overlay (see DECISIONS.md for why)
- Host/module architecture decided: PySide6, folder-per-module, auto-discovery
- Doc structure scaffolded (this file, ARCHITECTURE.md, DECISIONS.md,
  modules/commodity-prices.md — named modules/price-lookup.md at the time,
  renamed 2026-09-03, see below)
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
- Price Lookup module built and working (renamed to Commodity Prices /
  `modules/commodity_prices/module.py` on 2026-09-03, see below) —
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
- MIT `LICENSE` added; repo pushed public to
  github.com/h2mCoreAi/mobiOverlay. No release tag cut yet (deliberately —
  still heavily testing)
- Card hide/show renamed to Stow/Deploy end-to-end (code + UI), replacing
  the generic "+ ADD CARD" dropdown with a themed `_TrayPanel` matching
  SC's own in-game vocabulary — see DECISIONS.md for the full rationale
  and the visibility-tracking bug found and fixed along the way. Verified
  the complete stow → tray → deploy cycle via real UI Automation clicks
  (not just a static screenshot) — confirmed working end-to-end, entirely
  on the secondary monitor
- Clicking anywhere in a card raises it to front (app-wide event filter in
  `CardContainer` — see DECISIONS.md)
- Price Lookup renamed to **Commodity Prices** (module folder + `module_id`
  + class renamed too) — the old name implied it covered items/ships, but
  it's commodities only
- **Find Most Profitable** brute-force scan added to Commodity Prices —
  client-side scan across every commodity (~150-200 of them) since no real
  ranking endpoint exists anonymously (`commodities_ranking` deprecated,
  its replacement needs auth we've ruled out embedding). Chunked via
  `QTimer` so the UI stays responsive with live progress, 30-min in-memory
  cache, skips individually-failing commodities rather than aborting.
  Verified end-to-end via UI Automation: ran a real scan (205 commodities,
  ~25s), found "Osoian Hides" at an 870,000/283,500 sell/buy margin —
  genuine result, not a stub
- `UexRateLimitError` added to `api_client.py` — a distinct, clear message
  ("UEX rate limit reached — wait a moment, then retry") instead of a
  generic failure when UEX's own rate limit is hit. Not yet live-triggered
  (hard to force deliberately without actually spamming UEX) — code path
  reviewed, not observed firing for real
- Fixed a real bug hit while testing the rename: `refresh()` treated zero
  price rows as a hard error, when the existing per-row display logic
  already handled that gracefully ("no terminals buying/selling"). Some
  commodities (e.g. whatever sorts alphabetically first) genuinely have no
  active listings — that's a legitimate state, not a failure
- Settings menu added: SETTINGS button next to TRAY, opens a themed panel
  (`_SettingsPanel`) with Window Opacity (moved out of the title bar),
  Card Opacity (new — card background transparency independent of the
  window), and Text Size (Small/Normal/Large/Extra Large). Opacity changes
  apply live; Text Size applies on next launch (labeled as such — live
  font-rescaling would need every stylesheet rebuilt and reapplied, out of
  scope for this pass). Verified all three via UI Automation +
  `config.json` inspection + an actual restart for Text Size (fonts and
  card sizes visibly larger after relaunch)
- Config schema: `ui.opacity` renamed to `ui.window_opacity`, added
  `ui.card_opacity` and `ui.font_scale`
- **Retrieve Data / Find Most Profitable split.** User caught a real bug:
  the old combined scan computed margin across ALL systems, ignoring the
  Best Sell/Best Buy system filters entirely. Fixed by splitting into two
  actions: "Retrieve Data" only downloads (`_all_commodity_data` cache, no
  math), "Find Most Profitable" is now instant/local and reads
  `sell_system`/`buy_system` filter state at click time — verified
  end-to-end for the unfiltered case (live scan + selection); the
  filtered case is code-reviewed (identical filter logic to the
  already-verified `_apply_filters`) but not interactively confirmed —
  UI Automation couldn't reliably drive the system-filter combo boxes in
  this environment (popups closing between separate tool calls, z-order
  making element ordering unstable), not an app problem
- **Countdown / Force Update on Retrieve Data.** After a successful
  retrieve, the button shows a live "REFRESH IN MM:SS" countdown (30 min).
  Clicking while it's counting down doesn't re-fetch — it prompts "FORCE
  UPDATE?" first (auto-reverts after 4s if not confirmed), and only a
  second click actually forces a fresh retrieve. Verified all three states
  via UI Automation, including confirming the 4-second auto-revert
  actually happens by letting two separate tool calls (each with real
  wall-clock latency) land on either side of it
- **Settings > Relaunch button.** Spawns a fresh instance
  (`host/paths.py`'s new `relaunch_command()` — same exe when frozen, same
  interpreter+script from source) and closes the current one. **Found and
  fixed a real bug during testing**: the old process didn't actually exit
  after `self.close()` — the Settings panel itself (a `Qt.Popup`, open at
  the moment Relaunch is clicked, since that's where the button lives) is
  a separate top-level widget that `self.close()` never touched, so Qt's
  `quitOnLastWindowClosed` never fired and the old process lingered
  indefinitely. Fixed with an explicit `QApplication.instance().quit()`
  rather than relying on that. Verified clean: old PID fully gone,
  exactly one new PID running, new window visible and functional
- Text Size's settings-panel description reworded to point at the new
  Relaunch button ("Applies after a relaunch — use the button below")
  instead of a vague "next launch" — real-time font scaling was
  considered and explicitly dropped per user direction (too heavy a
  refactor for the value)

## Next

- Human review of the running app (this is the current handoff point) —
  especially Retrieve/Find with real system filters set (only the
  unfiltered path got a live human-equivalent test this session), the
  Force Update confirm flow, and Relaunch
- Grid-snap drag and per-card resize handle are code-reviewed and
  screenshot-confirmed to render, but not yet mouse-drag-tested by a human
- Confirm UEX bearer token is genuinely optional for the long term (GET
  endpoints work anonymously today, but that could change) — not blocking
  for now
- `UexRateLimitError`'s UI has never actually fired against a real rate
  limit — worth keeping an eye on the first time it does

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
