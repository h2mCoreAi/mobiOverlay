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

## Next

- **Human check: hotkey (again).** Confirm F3 (or whatever combo) now
  actually toggles stow/deploy while Star Citizen has focus — this is
  the whole point of the low-level-hook rewrite above, and the isolated
  `HotkeyState` tests are strong evidence the matching logic is correct,
  but only a real keypress while the game is focused can confirm the
  hook itself is actually intercepting input past the game.
- **Human check: pill position memory (again).** Drag the pill, deploy
  quickly (don't wait), re-stow, confirm it reopens at the dragged spot —
  that fast-follow-up sequence was exactly what silently broke the
  previous debounced-save version.
- **Human check: void background transparency (again).** Two fix attempts
  for this didn't hold up under the user's own testing already this
  session — the third attempt (direct `paintEvent` painting) has much
  stronger evidence behind it (see above), but only the user's own eyes
  against real desktop/game content can fully confirm it, since
  `PrintWindow` can prove the pixel data is correct and opacity-reactive
  but not what DWM does with it against whatever's actually behind the
  window.
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
Current top pick: Trade Route Optimizer (`commodities_routes`).
