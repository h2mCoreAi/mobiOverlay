# Progress

## Status: Location-service plan — Phases 1-4 done (shared service,
## Logistics Hub migrated, real-distance routing, Trade Route
## Optimizer/Commodity Prices migrated) + extensive live
## hardening; Phase 5 (shared current
## location) not started

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
  User-tested 2026-09-03 and confirmed working as intended — not a bug.
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
- Trade Route Optimizer: fixed "Admin -" terminal names (user caught this
  too) by switching the picker to UEX's `nickname` field instead of the
  raw `name`; route-list destinations get the prefix stripped by hand
  since `commodities_routes` has no nickname field. Terminal picker is
  now editable with a filtering `QCompleter` (type to narrow 100+
  terminals, or still scroll the full list) — see DECISIONS.md for the
  `textActivated` vs `currentTextChanged` gotcha this required
- Trade Route Optimizer: added a "Sell In" destination-system filter
  (client-side, `commodities_routes` rows already carry
  `destination_star_system_name`, same pattern as Commodity Prices'
  filters) plus clearer buy/sell labeling ("▲ BUY HERE" above the origin
  picker, "SELL AT ..." per row instead of a bare arrow) after the user
  had to ask what a route row meant. Filter logic verified correct via a
  standalone script with sample data; the live combo-selection
  interaction itself couldn't be proven through UI Automation this
  session — see DECISIONS.md, this looks like a genuine tooling
  limitation (3 different automation methods all failed identically)
- Text size ladder shifted up one tier per user direction: new Small =
  old Normal (1.0), new Normal = old Large (1.15), new Large = old Extra
  Large (1.3), and a genuinely new Extra Large (1.45) was added on top —
  same +0.15 step throughout. Default `font_scale` moved from 1.0 to
  1.15 to match the shift
- **Collapse All / Expand All** toggle in the title bar (`▾ ALL` /
  `▸ ALL`) — one click collapses or expands every card at once. Verified
  working both directions via UI Automation
- **Minimize the whole app to a small pill.** New `▬` button shrinks
  MainWindow down to just the wordmark + close button (still always-
  on-top); clicking the pill restores the exact previous position and
  size. Uses the same Stow/Deploy vocabulary as cards, applied to the
  whole window — see `MainWindow.stow_app`/`deploy_app` in
  `main_window.py`. Verified end-to-end with a real mouse click (not
  just automation Invoke): stow → screenshot confirmed pill-only content
  → click → screenshot confirmed exact restore, cards and all
- **System-wide Stow/Deploy hotkey**, `host/hotkey.py` — real Win32
  `RegisterHotKey`/`WM_HOTKEY`, not a Qt shortcut, so it works while the
  game (not mobiOverlay) has focus. Capture field in Settings: click,
  press a combo, Escape cancels; requires at least one modifier for keys
  that would otherwise hijack normal typing — but function/navigation
  keys (F1-F12, Insert, Delete, Home, End, Page Up/Down, arrows) are
  exempt and can be set bare (`key_requires_modifier()` in `hotkey.py`).
- **Bug fix (2026-09-03): hotkey field never actually captured a
  keystroke, for any key, not just bare F3.** Root cause: `keyPressEvent`
  built the display string with `QKeySequence(int(event.modifiers()) |
  key)` — in PySide6/Qt6, `event.modifiers()` returns a `Qt.KeyboardModifier`
  flag object that `int()` can't coerce (`TypeError`), so the handler threw
  and silently died before ever calling `set_stow_hotkey()`. Fixed with
  `QKeySequence(QKeyCombination(event.modifiers(), key))`, the Qt6-correct
  way to pair a modifier with a key. Confirmed via isolated script (both a
  bare `F3` and `Ctrl+Shift+M` now build the correct display string with no
  exception) and confirmed `RegisterHotKey` itself accepts a bare F3 at the
  Win32 level. Live keystroke-into-the-popup-field capture still couldn't
  be re-verified by automation this session (see DECISIONS.md) — needs a
  human to click the field and press a combo to fully close this out.
- **Bug fix (2026-09-03): pill couldn't be dragged.** The title bar's
  wordmark is a rich-text `QLabel`, which defaults to
  `Qt::LinksAccessibleByMouse` and was intercepting mouse events before
  they reached the title bar's own drag handlers — the pill's whole
  clickable surface is that label, so nothing could ever drag it. Fixed
  with `setTextInteractionFlags(Qt.NoTextInteraction)`. Verified live:
  real mouse drag moved the pill ~180×135px.
- **Bug fix (2026-09-03): "by Kestryl" showed in pill mode.** Wordmark
  was one combined-HTML `QLabel`; split into a main wordmark label (kept
  visible while stowed) and a separate byline label (hidden via
  `set_stowed_mode()`). Verified live via UI Automation control
  enumeration — pill now shows only "MOBIOVERLAY" + close.
- **Feature (2026-09-03): pill and deployed-window positions are now each
  remembered independently and persisted to config.json**, not just held
  in memory for the current session. Dragging the pill around and
  re-stowing later reopens it at that exact spot instead of wherever the
  full-size window happened to be; likewise the full-size window's last
  position/size is saved continuously (debounced, 400ms after the last
  move/resize) so it survives even if the app is closed while stowed.
  New `pill_geometry` config key alongside the now-actually-used
  `pre_stow_geometry`. Verified live: dragged the pill, confirmed
  `pill_geometry` in config.json matched, deployed, re-stowed, pill
  reopened at the remembered spot.
- **Feature (2026-09-03): window/void background transparency decoupled
  from card opacity.** Previously `WINDOW OPACITY` used `setWindowOpacity()`,
  which dims the *entire* rendered window uniformly — cards could never
  look more opaque than the window itself, coupling the two sliders.
  Switched `MainWindow` to `Qt.WA_TranslucentBackground` with a per-pixel
  rgba background (`theme.hex_to_rgba(theme.BG_VOID, window_opacity)`,
  same pattern `Card.set_card_opacity()` already used) so the empty space
  around cards can be fully see-through independent of each card's own
  opacity slider. Settings label updated to "How see-through the empty
  space around your cards is." to match. Not yet visually confirmed
  against the desktop/game behind it (PrintWindow captures a window's own
  render, not what's genuinely behind it) — worth a human glance.

- **Bug fix (2026-09-03, second pass): the hotkey fix from the first pass
  was itself broken.** `QKeyCombination(event.modifiers(), key)` still
  raised `TypeError` on every keypress — `QKeyCombination` requires an
  actual `Qt.Key` enum member for its second argument, not the plain
  `int` that `event.key()` returns in PySide6. The first pass's isolated
  test used `Qt.Key_F3` directly (already the right type) so it didn't
  catch this. Fixed with `Qt.Key(key)`. This time verified by calling the
  real `_HotkeyField.keyPressEvent` end-to-end with synthetic `QKeyEvent`s
  (bare F3 and Ctrl+Shift+M), confirming it now reaches `set_stow_hotkey`
  with the correct `(mod, vk, display)` for both — not just testing the
  crashing line in isolation like before.
- **Bug fix (2026-09-03, second pass): window opacity slider was stuck at
  0 (fully transparent) no matter what it was set to.** The
  `WA_TranslucentBackground` change from the first pass never added
  `Qt.WA_StyledBackground` — a plain `QWidget` (which `MainWindow` is)
  silently ignores a QSS `background` property entirely without that
  attribute, so the void background rule never painted at all, leaving
  it permanently transparent regardless of the slider. `_SettingsPanel`/
  `_TrayPanel` elsewhere in the same file already had this attribute set
  correctly — `MainWindow` was the one place it was missing. Fixed.
- **Bug fix (2026-09-03, third pass): the WA_StyledBackground fix wasn't
  enough — QSS `background:` on a translucent top-level widget doesn't
  reliably composite on this Qt/Windows combo at all.** User confirmed:
  moving the slider produced no visible change at any position. Rewrote
  to paint the void directly in `MainWindow.paintEvent()` via `QPainter`
  in `CompositionMode_Source` instead of a QSS rule. Confirmed with pixel
  sampling this is a real, reactive fix this time: the same screen pixel
  read as flat `(0, 0, 0)` regardless of slider position under the old
  QSS approach (not even `theme.BG_VOID`'s actual color), vs. correctly
  `(6, 9, 11)` at 100% and `(2, 4, 4)` at 40% (matching premultiplied-
  alpha scaling almost exactly) under the new paintEvent approach. See
  DECISIONS.md for the full trail.
- User confirmed the hotkey *field* now correctly captures and displays a
  combo — but the hotkey didn't actually *toggle* stow/deploy while Star
  Citizen had focus. Root cause: `RegisterHotKey`/`WM_HOTKEY` delivers
  through the normal window message queue, which the game (fullscreen/
  exclusive input) can block. **Rewrote `host/hotkey.py` to use the
  `keyboard` library's low-level global keyboard hook
  (`WH_KEYBOARD_LL`/`SetWindowsHookEx`) instead** — the same mechanism
  ThrottleWatch (a separate, already-shipping SC overlay by the same
  author) uses, where this exact problem never comes up. Ported
  ThrottleWatch's `HotkeyState` (combo tracking + a `GetAsyncKeyState`
  reconcile watchdog for stuck modifiers) directly. Capture also switched
  from Qt key events to `keyboard.read_hotkey()` in a background thread
  (ThrottleWatch's proven capture pattern), which sidesteps the
  Qt.Popup-keyboard-focus unreliability the old capture had — see
  ARCHITECTURE.md's "Global hotkey" section for the full design. Verified
  the combo-matching logic (`HotkeyState`) directly with synthetic events:
  bare F3 fires and re-fires correctly on repeated press/release,
  multi-key combos correctly wait for every modifier before firing, and
  `clear()` correctly stops dispatch. New dependency: `keyboard>=0.13`
  (added to requirements.txt).
- **Bug fix: pill position wasn't actually being remembered.** The
  debounced `moveEvent`-driven save (added when this feature first
  shipped) checked `is_app_stowed()` only when its shared timer finally
  fired, not per-event — dragging the pill and then deploying shortly
  after (well within the 400ms debounce window) restarted the same timer
  from the deploy's own move, so it fired checking the now-deployed
  state and silently never saved the pill's dragged position at all.
  Replaced with an immediate (non-debounced) save at the exact moment a
  drag actually ends (`_TitleBar.mouseReleaseEvent`) and at the end of
  `stow_app()`/`deploy_app()`'s own repositioning — no more shared timer,
  no more race. Resize (which only happens deployed, via the grip that's
  hidden while stowed) keeps its own debounce, now unconditional since
  there's nothing for it to race against.

- User confirmed (2026-09-03): hotkey toggle, pill position memory, and
  window opacity are all working correctly now.
- **Feature: deploying via the hotkey now takes real OS input focus, not
  just visual z-order.** Toggling into full mode used to leave keyboard
  focus with whatever had it before (the game) even though the overlay
  was now on top. `MainWindow._take_foreground_focus()` (called at the
  end of `deploy_app()`) uses `AttachThreadInput` to temporarily join this
  process's input queue with the currently-foreground window's thread,
  which is what actually satisfies Windows' `SetForegroundWindow`
  restriction (a plain call is normally refused from a background
  process) — a "tap Alt first" heuristic trick was tried first and didn't
  reliably work here. Verified end-to-end with real Win32 key injection
  (`keybd_event`) while Star Citizen genuinely held foreground focus:
  sampled the foreground window at 20ms/200ms/800ms after deploying and
  it was mobiOverlay's own process at every sample, not the game.
- **Bug fix: Commodity Prices showed the raw "Admin - MIC-L2" kiosk label
  instead of a clean terminal name** — same underlying issue Trade Route
  Optimizer already had fixed (`docs/modules/trade-route-optimizer.md`).
  Confirmed via real API calls that `commodities_prices` has no nickname
  field of its own (`terminal_name` is always the raw kiosk label), but
  does have `id_terminal`. Fetches `terminals?type=commodity` once at
  card creation to build an `id_terminal -> nickname` map instead —
  `nickname` is the same clean-name field the trade route picker already
  uses. Verified against real live API data before wiring it in
  ("Admin - MIC-L2" -> "MIC-L2", "TDD - Trade and Development Division -
  Area 18" -> "TDD Area 18", etc.) and confirmed visually in the running
  app afterward.
- **Bug fix: Diamond's reported sell price was ~10x too high (80,000 vs.
  the real ~7,800 aUEC/SCU).** User flagged it as suspicious; checked live
  against UEX's own site and the raw API. Root cause: UEX's
  `commodity_name` query param is a substring match, not exact —
  `commodity_name=Diamond` also returns rows for "Diamond Laminate" (a
  different commodity, id 119 vs. Diamond's id 25), and the card's
  best-price logic just took the max/min `price_sell`/`price_buy` across
  every returned row with no check that it actually belonged to the
  selected commodity. Fixed by filtering rows to `commodity_name == name`
  exactly after fetching, in both `refresh()` and the Retrieve Data loop.
  Verified against real API data before and after the fix (mixed-in
  Diamond Laminate rows removed, top Diamond sell price correctly 7,800
  at HUR-L1) and confirmed visually in the running app.
- **New module: Crosshair** (`modules/crosshair/`) — a standalone reticle
  overlay, not from the UEX backlog. See `docs/modules/crosshair.md` for
  the full design and what's verified vs. not. Draws a fixed "+" dead-
  center on the primary display (separate top-level widget from the
  card, click-through, no UEX API involved) with a card holding
  Show/Hide + 1px-increment nudge/reset controls.
- **mobiOverlay Core hardening pass (C1-C4, all Critical items from a
  senior-dev-style readiness review):** soft diagnostic watchdog for
  slow module calls, `create_card()`/`refresh()` load-time contract
  validation, duplicate `module_id` rejection, removed the documented-
  but-never-built `settings_schema` field. Also fixed 3 code-review
  findings (a card-visibility bug, a missing `KeyError` catch in the
  hotkey code, and a GC-lifetime fragility in hotkey capture). Core
  informally renamed "mobiOverlay Core" in docs (no folder/import
  rename). See DECISIONS.md for each item's rationale/scope.
- **New module: Logistics Hub** (`modules/logistics_hub/`) — OCR-driven
  hauling mission board reader + UEX-backed route planner, the 4th
  module. Scaffolded by Aider (DeepSeek V4 Flash), then substantially
  hardened by Claude across several real-contract test/fix rounds — see
  DECISIONS.md for the full design writeup (contract model, UEX
  location resolution, the cross-endpoint id-collision bug, role
  hinting, commodity extraction, route planning with a hard pickup-
  before-dropoff constraint). Verified end-to-end against 4 real
  screenshotted Star Citizen contracts (single pickup/single dropoff,
  single pickup/multiple dropoffs, multiple pickups/single dropoff, and
  a 4-pickup/1-dropoff contract), each re-checked after every fix to
  catch regressions — caught and fixed several this way (an endpoint-
  priority "fix" that silently dropped a real station, a signature-
  based merge that wrongly collapsed two different stations on the same
  planet). Uses `easyocr` (was `winsdk`/native Windows OCR briefly —
  reverted, no prebuilt wheel for this machine's Python 3.14 and no
  Visual Studio build tools to compile it from source).
- Verified live against the real UEX API (not just unit-style checks
  with fake data) that `terminals_distances` and `orbits_distances`
  return real point-to-point/orbit-to-orbit distances, including
  cross-system — Logistics Hub's route cost is currently a coarse
  4-tier heuristic (same terminal/body/system/different-system) with
  made-up weights; switching to these endpoints is the next concrete
  improvement, not yet implemented. Also spot-checked several resolved
  locations (HDMS-Edmond/Thedus/Hadley, Bueno Ravine) against the
  Star Citizen Wiki — all correct (right planet, right system).
- **Core Location service built** (`host/locations.py`) and **Logistics
  Hub migrated onto it** — one shared, endpoint-safe, disk-cached
  (7-day refresh) location index instead of Logistics Hub's own copy;
  ~135 lines of private resolution logic removed. See DECISIONS.md,
  2026-09-04, for the full endpoint-collision bug this fixed
  (`terminals`/`space_stations`/`outposts`/`cities` have independent id
  sequences — a bare numeric id was silently colliding two unrelated
  real places).
- **Real-distance routing** — `LocationService.distance()` (terminal-
  to-terminal via `terminals_distances`, orbit-to-orbit via
  `orbits_distances` otherwise, both queried lazily and cached
  per-session) replaced Logistics Hub's coarse 4-tier cost heuristic.
  Verified 2-opt found a genuinely cheaper route (328 vs. 358) than a
  manually "intuitive" guess once real numbers were available —
  real data disagreeing with human intuition about clustering was
  exactly the point of this phase.
- **Extensive live-test-driven hardening on Logistics Hub**, many
  rounds of real captured contracts reviewed (console + COPY ROUTE
  export together each time): a 2-opt route-improvement pass on top of
  greedy nearest-neighbour; a hint-priority bug that resurfaced at a
  second, deeper merge point than the first fix caught; a short-
  nickname false-positive substring match ("DROP OFF" ~ Port Olisar's
  "PO"); bare "PICK UP"/"DROP OFF" section headers; two independent
  ambiguity-disambiguation signals (same-line trailing digit/code
  capture, and preferring a location already confirmed elsewhere in
  the same contract); commodity extraction tracking every raw OCR
  spelling that resolved to a place, not just the winning one; an
  honest "cargo unknown" label instead of a silent blank, and instead
  of ever showing a commodity name as if it were an unresolved
  location; a period-as-reward-separator OCR variant; and duplicate-
  contract detection (same reward + any shared resolved location,
  loosened from an exact full-set match after real OCR noise broke
  that) with a themed CONFIRM/DENY popup instead of silently tripling
  the route. Full history in DECISIONS.md.

- **mobi-branding standardized across all 4 card titles** (mobiOverlay,
  mobiTrade, mobiAim, mobiCommodities, mobiLogistics — "mobi" white,
  rest blue) — fixed a real bug this exposed (`host/card.py` was forcing
  `.upper()` on every card title, which would have wrecked the new
  mixed-case branding; the Logistics Hub route popout already proved the
  correct mixed-case rendering worked, the card header next to it
  didn't). Tray picks up the fix automatically, no separate tray change
  needed. See DECISIONS.md.
- Logistics Hub's "SELECT REGION" button renamed to "SET SCAN AREA" —
  user flagged it read as an in-game region, not the OCR capture area.
- Fixed right-edge text clipping on Logistics Hub's location combo and
  Trade Route Optimizer's terminal/system combos — none of the
  `QComboBox` styles reserved room for the drop-down arrow subcontrol.

- **Startup splash screen added** (`host/splash.py`) — investigated the
  reported startup delay first: confirmed via diagnostic timing it's
  Logistics Hub's `import easyocr` (2.79s of 3.64s total), not the UEX
  API. Splash shows the mobiOverlay wordmark + a status line that updates
  per-loading-stage (including which module is loading), so the pause is
  now explained instead of looking frozen. See DECISIONS.md.

- **Logistics Hub debug log added** (`logistics_hub_debug.jsonl`,
  always-on JSON Lines, one entry per scan: raw OCR, candidate phrases
  w/ role hints, resolved contract, route snapshot) — see DECISIONS.md
  for the full scoping and format. Code-reviewed/syntax-checked only,
  not yet live-tested.
- **Bug fix: Logistics Hub relaunch showed persisted contracts but an
  empty ROUTE.** `_route_order` is in-memory-only and was never
  recomputed on card load. Fixed by replanning from persisted contracts
  in `create_card()`. User-confirmed fixed 2026-09-04.
- **Debug Console toggle added to Settings** (`ui.show_console`, applies
  on next relaunch) — opens a real console window via `AllocConsole()`
  so log output is visible for the packaged windowed exe, where
  stdout/stderr otherwise go nowhere. No-op when run from an actual
  terminal (one's already attached). See DECISIONS.md.
- **Fuzzy location fallback for Logistics Hub** (`LocationService.resolve_fuzzy()`
  in `host/locations.py`, cutoff 0.85, wired into `_build_contract`'s Pass 1) —
  a candidate with a real pickup/dropoff hint but zero exact/substring matches
  no longer vanishes silently; it's fuzzy-matched and surfaced via the existing
  amber-warning mechanism instead. Verified against all 7 real contracts in
  `logistics_hub_debug.jsonl`: no regressions, cutoff tuned up from an initial
  0.75 after that same replay caught a real false positive. Locations only —
  see DECISIONS.md, 2026-09-05, for the full design/verification writeup.
- **mobiTrade's origin picker replaced** with a single searchable combo
  (matching Logistics Hub's CURRENT LOCATION UX), and `LocationService`
  gained `friendly_label()` so terminal-only pickers can borrow a sibling
  station/outpost/city's fuller name — see DECISIONS.md, 2026-09-05.
- **mobiCommodities' "Find Most Profitable"/Best Sell/Best Buy made
  stock-aware** — user caught it recommending a commodity with only 2 SCU
  of real stock over mobiTrade's correctly-ranked top pick from the same
  terminal. Fixed to weight by `scu_buy` (verified live to be the reliable
  field; `scu_sell` is not — see DECISIONS.md, 2026-09-05, for the full
  live-API investigation and the mid-implementation correction).
- **mobiTrade's origin picker made optional** — new `— Any Location —`
  sentinel + BUY IN system filter, with a manual SCAN button (multi-
  terminal, throttled, same pattern as Commodity Prices' Retrieve Data)
  since `commodities_routes` has no bulk-origin query (confirmed live —
  see DECISIONS.md, 2026-09-05). Route rows now show BUY AT alongside the
  existing SELL AT.
- **FIXED (2026-09-06): the role-assignment KNOWN BUG below** (pickup/
  dropoff hint tie-break picking the wrong mention) — two distinct
  mechanisms in `_candidate_phrases()` (`modules/logistics_hub/module.py`)
  fixed together after a fresh debug log reproduced it live on a real
  Seraphim/Ambitious Dream Station contract. See DECISIONS.md, 2026-09-06,
  for the full root-cause/fix/verification writeup.
- **FIXED (2026-09-06, same session): the Ambitious Dream Station
  commodity-extraction gap noted alongside the fix above.** A delivery
  line split by OCR before its destination even starts was invisible to
  commodity extraction entirely (not just truncated), and a commodity
  name split even further (its second word orphaned elsewhere in the raw
  text) is now completed against a fuller mention of the same commodity
  already confirmed elsewhere in the same contract. New
  `_find_delivery_match()`/`_complete_commodity_name()` helpers in
  `modules/logistics_hub/module.py`. See DECISIONS.md, 2026-09-06.
- **New module: Refinery Finder** (`modules/refinery_finder/`) —
  BACKLOG.md's Tier 1.3 "Refinery Yield Calculator," scope narrowed after
  live API investigation showed a literal SCU-in/SCU-out calculator isn't
  buildable from real UEX data (no base yield%/purity field anywhere, and
  only 3 real `refineries_audits` rows exist project-wide). Instead ranks
  real UEX-tracked refinery terminals by their reported yield modifier
  (`refineries_yields`) for a chosen raw commodity, shows each terminal's
  capacity (`refineries_capacities`), and a static refining-methods
  comparison table (`refineries_methods`). Verified end-to-end against
  live data (not a stub): 45 raw commodities in the picker, correct
  top-5 ranking for Laranite (Raw) across 3 systems, correct "no yield
  data reported yet" state for a commodity with zero reports (21 of 45
  currently have none), system filter narrowing results correctly,
  settings persisting to `config.json`, and loading cleanly through the
  real `discover_modules()` alongside all 4 existing modules with no
  contract/duplicate-id issues. See docs/modules/refinery-finder.md and
  DECISIONS.md, 2026-09-06, for the full scoping rationale.

- **Card ROUTE section restored to a full inline stop list** (was a
  placeholder pointing at the Tracker popout since 2026-09-05 — the
  original bug behind that revert never reproduced this time, verified
  live via a real launch + screenshot). **Manual CARGO CAPACITY field
  added** (SCU, persisted) with an amber over-capacity warning on the
  card's summary line, verified live. **Freight Manifest section added**
  — running commodity list across all active contracts, flags any
  commodity split across 2+ contracts (hard to tell apart in-game once
  picked up). 16/16 regression checks pass. See DECISIONS.md, 2026-09-07,
  for full detail on all three.

- **Scan → review popup shipped (Part 1 of 3 on the confirm-gate/grading
  plan** — see `~/.claude/plans/yes-please-fold-all-quizzical-starfish.md`
  for the full 3-part plan). SCAN CONTRACT no longer auto-adds; every scan
  pauses on a themed ACCEPT/REJECT popup showing the pickup/dropoff
  summary, reward, SCU, and a duplicate warning when relevant. Grading
  (letter grade + reason) and the Hauler Profile are Parts 2-3, not yet
  built. Caught and fixed two real bugs while building this (a reward-
  formatting crash in the popup, and a test that was silently overwriting
  the real config.json) — see DECISIONS.md, 2026-09-07. 19/19 regression
  checks pass, verified live via a real launch + UI Automation click.

- **Hauler Profile added (Part 2 of 3)** — new PROFILE button/popup on the
  card: Ship, Goal, Risk Tolerance, Session Time, Region, saved once and
  edited whenever. Grading (Part 3, not yet built) will read this to score
  future scans. 20/20 regression checks pass, verified live via a real
  launch + UI Automation. See DECISIONS.md, 2026-09-07.

- **Confirm-gate/grading plan complete (all 3 parts shipped)** — see
  DECISIONS.md, 2026-09-07, for each part's full writeup:
  1. Scan → review popup (ACCEPT/REJECT, replaces auto-add)
  2. Hauler Profile (Ship/Goal/Risk/Time/Region, set once)
  3. Ship/location compatibility feedback DB (starts empty, grows from
     your own GOOD/BAD answers — no static ship-data source exists to
     guess from) + contract grading (letter grade + reason, hard-capped
     amber on a known-BAD location or duplicate-freight overlap, never
     blocking ACCEPT). Verified against the literal Hull C-at-an-
     incompatible-station scenario that motivated this work. 25/25
     regression checks pass.
  Three real bugs found and fixed only by actually running the app live
  (a reward-format crash, a None-profile crash, and a cap that wasn't
  visually distinct) — none were catchable by logic-only tests alone.

- **Debug log extended for the confirm-gate/grading feature** — the scan-
  time entry now carries grade/reason/capped, and a new entry logs the
  actual ACCEPT/REJECT outcome plus which locations were shown for a
  compatibility rating and what was answered. Found and fixed a test-
  hygiene bug along the way (tests were appending fake entries into the
  real debug log — now isolated). 26/26 regression checks pass. See
  DECISIONS.md, 2026-09-07.

- **Two real bugs from first live testing, both fixed**: the review/
  profile popups used `Qt.Popup`, which closed the moment you clicked
  away (e.g. to this chat) — switched to a real always-on-top window that
  only closes on ACCEPT/REJECT/SAVE. That fix briefly introduced a
  garbage-collection bug (caught by the regression suite, not by you),
  now also fixed. Also: clicking a compatibility rating button now shows
  a colored border on the chosen one instead of just greying both out
  identically. See DECISIONS.md, 2026-09-07.

- **Grading now shows a raw 0-100% score instead of a letter grade, and
  cargo capacity overflow is finally checked** — user caught that a
  contract needing ~4x their actual capacity still scored a "B" (grading
  never checked capacity at all, a real oversight). Combined peak cargo
  (everything queued + the new scan) vs. capacity now caps the score much
  harder (20%) than the existing duplicate-freight/bad-location cap (55%)
  — exceeding your hold is a harder constraint than either of those.
  27/27 regression checks pass. See DECISIONS.md, 2026-09-07.

- **CARGO CAPACITY moved into the Hauler Profile popup**, directly beneath
  SHIP (was its own row on the card face) — per user request, since a
  hold size only makes sense in the context of a specific ship. Same
  settings key, only the UI location changed. 27/27 regression checks
  pass. See DECISIONS.md, 2026-09-07.

- **aUEC/SCU grading thresholds are now user-editable** — the hardcoded
  500/200/80 numbers were checked against this project's own real
  captured contracts and found miscalibrated low, so rather than guess a
  replacement scale, it's now a GRADING SCALE table in the Hauler
  Profile popup. Applies on the very next scan, no restart (grading
  already reads settings fresh every call). 28/28 regression checks
  pass. See DECISIONS.md, 2026-09-07.

- **New COMPLETE button** — logs every queued contract (reward, cargo,
  locations, grade at accept) to a new `logistics_hub_completed.jsonl`,
  then clears the queue. CLEAR is unchanged (still discard-without-a-
  trace, for mistakes/duplicates) — kept separate so completed history
  only ever has contracts actually delivered. 29/29 regression checks
  pass. See DECISIONS.md, 2026-09-07.

## Next

- **OCR pipeline optimization pass — in progress, incremental, one
  change at a time per user direction.** Noted 2026-09-06 per user
  request. Ranked list of candidate optimizations investigated; working
  through them one at a time with the user's go-ahead between each:
  1. ✅ **Done (2026-09-06): column-aware reading order.** Was
     `readtext(detail=0)`, which discards position data and returns text
     in whatever order EasyOCR's internal sort produces — this doesn't
     respect the contract panel's real two-column layout (mission
     narrative text next to a separate PICK UP/DROP OFF list), and is
     the root cause behind the large majority of parsing bugs fixed this
     session (split location names, orphaned words, role
     misattribution) — all really downstream symptoms of reading both
     columns interleaved. Switched to `detail=1` (keeps bounding boxes)
     + new `_order_ocr_boxes()`: splits into at most two columns by the
     single largest horizontal gap between text boxes (only if wide
     enough to be a real column boundary), sorts each column
     top-to-bottom, reads the left column in full before the right one.
     Degrades safely to one column (unchanged from before) when no real
     gap is found. See DECISIONS.md, 2026-09-06.
  2. ✅ **Done (2026-09-06): 2x upscale before OCR.** LANCZOS-resized
     the grayscale capture 2x before `readtext()` (EasyOCR's own
     internal `mag_ratio` resizing alone isn't equivalent — this happens
     before detection runs, not as a parameter to it). Verified with a
     genuinely small synthetic test line: without upscaling, EasyOCR
     fragmented it into 3 disjoint unusable pieces ("Ontr", "Pontesh");
     with upscaling, it stayed as one coherent (if still imperfect)
     line. See DECISIONS.md, 2026-09-06.
  3. **Investigated, NOT implemented (2026-09-06): thresholding/
     sharpening on top of the current grayscale+autocontrast+upscale.**
     A/B tested two candidate techniques (Otsu binarization, mild
     UnsharpMask) against 4-6 synthetic cases each, compared directly
     against the true pre-session baseline. Neither showed a consistent
     enough win to justify shipping: binarization was a wash (helped one
     detail, hurt another, on the same case); sharpening meaningfully
     helped one case, was neutral on another, slightly hurt a third.
     The already-shipped 2x upscale (#2) is the real, consistent win —
     it stops EasyOCR from fragmenting a line into disconnected pieces,
     the actual failure mode that breaks downstream line-based parsing.
     Skipping this item rather than shipping an unproven change. See
     DECISIONS.md, 2026-09-06, for the full comparison data.
  4. ✅ **Done (2026-09-06): EasyOCR character allowlist.** New
     `OCR_ALLOWLIST` — letters, digits, and every punctuation mark
     observed across this session's real captures. Theoretically sound
     (restricting a classifier's output space can only remove wrong
     options, never add new errors, given a genuinely complete list) but
     empirically inconclusive in synthetic testing — no measurable
     difference on clean synthetic text, since the real benefit targets
     genuine OCR hallucination artifacts (e.g. a reward-icon glyph
     misread as a stray symbol) that synthetic text can't reproduce.
     **All 4 ranked OCR optimizations now implemented** — a real scan is
     the actual test of the batch. See DECISIONS.md, 2026-09-06.
  5. **First live scans (2026-09-07): both parsed correctly overall.**
     Confirmed the single-word-city fix works live for real (not just
     synthetic) — but surfaced a real commodity-extraction gap for that
     exact case, fixed same day: a single-word-city destination's
     commodities were always lost, not just occasionally, due to a
     mechanical incompatibility with the Port Tressler theft fix. See
     DECISIONS.md, 2026-09-07.
- **FIXED (2026-09-06): the duplicate-stop KNOWN BUG below.**
  `_build_contract`'s `merge_resolved` now also merges two candidates that
  resolve to *different* UEX records for the *same real place* (via
  `LocationService.same_physical_place()`, added earlier the same session
  for the related distance bug), preferring the structural record's name
  over a `terminals` kiosk's raw label as the display representative. See
  DECISIONS.md, 2026-09-06, for the full writeup and verification.
- **FIXED (2026-09-06): the single-word-city KNOWN BUG below.**
  `_candidate_phrases` now also offers a single capitalized word as a
  candidate when it immediately follows "in " — narrowly scoped to that
  one preposition specifically to avoid a much worse regression (bare
  planet names like "Hurston"/"Crusader", which appear via "above PLANET"
  in every real template, collide with unrelated real shops via substring
  match — confirmed live before shipping this). See DECISIONS.md,
  2026-09-06, for the full root-cause/risk/verification writeup.
- **Human check: Logistics Hub debug log.** Run a real scan and confirm
  `logistics_hub_debug.jsonl` appears next to `config.json` (repo root
  when running from source) with one valid JSON line containing raw
  text/candidates/contract/route.
- **Human check (not yet done, deliberately deferred): Settings >
  Relaunch fix.** User reported the old process isn't always fully dead
  before the new one starts. Fixed 2026-09-04 (see DECISIONS.md for full
  detail): `GlobalHotkey.shutdown()` added (the global keyboard hook was
  never actually unhooked before), `relaunch()` reordered to clean up
  *before* spawning the new process (was racing), and `os._exit(0)`
  added as a hard stop against easyocr/torch's native thread pools
  possibly delaying interpreter shutdown. Code-reviewed and
  syntax-checked only — **needs a live test**: run at least one
  Logistics Hub scan (to actually load torch), then click Relaunch, and
  confirm via Task Manager that the old process is gone before/as the
  new one starts. Do this before trusting Relaunch is fixed.
- **Phased Core Location service** — Phases 1-4 done (see Done above and
  DECISIONS.md for rationale/detail); Phase 3's swap moved up ahead of
  Phase 4 per a later reprioritization:
  1. ✅ Shared service in `host/`, verified standalone.
  2. ✅ Migrate Logistics Hub onto it.
  3. ✅ Swap Logistics Hub's route cost onto real
     `terminals_distances`/`orbits_distances`, queried lazily — plus an
     extended live-test-driven hardening pass on top (see Done above).
  4. ✅ Migrate Trade Route Optimizer and Commodity Prices onto the
     shared service — origin-system/terminal pickers (Trade Route
     Optimizer) and the terminal-nickname lookup (Commodity Prices) now
     read from `LocationService.available_systems()`/`all_locations()`
     instead of each module's own `star_systems`/`terminals` calls.
     Verified live against the real UEX API (backend smoke script, not
     the Qt UI — see workflow conventions). Each module keeps its own
     picker UI and any endpoint-specific logic the shared service
     doesn't cover (`commodities_routes`' destination-name prefix-strip
     stays hand-rolled — that endpoint has no `id_terminal` to resolve
     through the service).
  5. **Not started.** Share a "current location" concept across modules
     — Logistics Hub already has one; Trade Route Optimizer/Commodity
     Prices could default their system filters from it.
  Each phase is its own tested checkpoint before starting the next —
  not a single big-bang change.
- Logistics Hub has now had extensive human-in-the-loop live testing
  (many real captured contracts, console + COPY ROUTE export reviewed
  together each round) — the SELECT REGION/SCAN CONTRACT/CURRENT
  LOCATION flow itself is confirmed working in the real running app,
  not just via backend calls. Still worth periodic real-world spot
  checks as new contract shapes turn up, same as any OCR-dependent
  feature.
- Packaging: `modules/logistics_hub/requirements.txt` (easyocr,
  ~500MB+ with PyTorch) needs folding into the standard install/build
  path now that distribution is all-inclusive (see DECISIONS.md,
  supersedes the earlier "optional module" framing) — not done yet.

- **Human check: crosshair module.** Confirm it actually shows up
  correctly over Star Citizen (not just confirmed centered/rendered
  against the desktop) and that it's genuinely click-through — doesn't
  ever intercept a mouse click meant for aiming. Also worth trying the
  nudge buttons for real (automation confirmed the underlying logic and
  persistence work, but a human clicking is the real test).
- **Human check: hotkey deploy now takes real focus.** Confirm pressing
  the hotkey while the game has focus actually pulls keyboard input to
  the overlay (e.g. typing into a card's field right after deploying,
  with no extra click needed first) — verified via Win32-level foreground
  sampling above, but a human typing right after the toggle is the real
  test of what this was actually for.
- Human review of the running app (this is the current handoff point) —
  especially Retrieve/Find with real system filters set (only the
  unfiltered path got a live human-equivalent test this session), the
  Force Update confirm flow, Relaunch, and the terminal search-as-you-type
  (typing itself was confirmed to reach the field; the actual filtered
  popup wasn't cleanly confirmed through automation this session)
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
Refinery Yield Calculator (Tier 1.3) is now built, as **Refinery Finder**
(scope narrowed — see docs/modules/refinery-finder.md and DECISIONS.md,
2026-09-06). Backlog is otherwise unchanged; next pick would be Tier 2.
