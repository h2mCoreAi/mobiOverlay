# Decisions

Append-only. Newest at bottom. Short entries — rationale, not essays.

- **2026-09-03 — Pivoted from Game.log combat overlay to UEX-API trading overlay.**
  Investigated Game.log on current patch (4.10, build ~12545750) across 51
  real sessions covering ~1 week of the user's actual PvE combat. Found no
  attacker/weapon/kill-attribution data at all — only signal was a bare
  `[ActorState] Dead` line for the player's own death, no cause info. Concept
  wasn't worth building on. Pivoted to UEX Corp API (community SC trade data)
  instead.

- **2026-09-03 — PySide6/Qt chosen over CustomTkinter and pywebview.**
  A prior overlay (pygame + Tkinter, different SC tool) hit packaging
  failures getting all dependencies into one distributable exe. PySide6 +
  PyInstaller is a more reliable one-file packaging path, and Qt's widget
  system handles card drag/drop and custom-font styling natively.

- **2026-09-03 — Modules are folder-per-module, auto-discovered.**
  Chosen over an explicit registry list so adding a module is purely
  additive — drop a folder in `modules/`, zero edits to host code or other
  modules.

- **2026-09-03 — Project name: mobiOverlay.**
  Nods to Star Citizen's in-game MobiGlas UI, generic enough for public
  open-source release (doesn't use the user's in-game callsign).

- **2026-09-03 — Visual design approved.**
  Mockup at https://claude.ai/code/artifact/63a18572-a046-4045-aa3c-caa8dfa0f4bc
  (working source: `design/Main.dc.html`). Approved as-is, no revisions
  requested. Key values to carry into Qt/QSS:
  - Fonts: Orbitron (headers, 600/800/900 weight) + Share Tech Mono (data/body),
    both via Google Fonts — must be bundled as files for the packaged exe,
    not linked at runtime
  - Background: deep charcoal/near-black (`#06090b` void, `#0d1417` card panel,
    `#101a1e` card header)
  - Primary accent: cyan `#2de1d0`, glow via `box-shadow: 0 0 0 1px + 0 0 14px`
  - Alert/error accent: amber `#ffb443`, same glow treatment, used for the
    Market Alerts / error-state card
  - Text: `#dff5f2` primary, `#7fa3a1` muted, `#3f5c5a` dim/labels
  - Sharp corners everywhere — no border-radius
  - Card header: small circular status dot + Orbitron label (letter-spaced,
    uppercase) + collapse chevron + close X, all right-aligned
  - Optional subtle scanline overlay (1px repeating gradient, very low
    opacity, blend-mode overlay) on the outer container
  - Card states to replicate in Qt: expanded (full body), collapsed
    (header-only), error (amber border + warning icon + retry action)

- **2026-09-03 — Modules ship external, not bundled into the packaged exe.**
  Decided before a third module made this expensive to reverse. Two
  reasons: (1) preserves the original "drop a folder in `modules/`, zero
  rebuild" goal — bundling would've quietly broken that; (2) directly helps
  the exe-trust-skepticism problem raised in conversation — a `modules/`
  folder of plain readable `.py` sitting next to the exe is auditable in a
  way a monolithic compiled binary isn't. `config.json` gets the same
  external treatment for an unrelated but equally load-bearing reason: a
  PyInstaller onefile build's temp extraction directory is wiped every
  launch, so a config path resolved relative to that would never actually
  persist. Both resolved via the new `host/paths.py` `app_root()` (exe's
  own folder when frozen, project root when running from source). Required
  switching the module loader from a dotted `modules.<name>.module` package
  import to file-path loading (`importlib.util.spec_from_file_location`),
  since external `modules/` won't be a real importable package once frozen.
  Fonts stay bundled inside the exe (not pluggable, no reason to externalize).

- **2026-09-03 — Project's own git repo initialized separately from the
  home-directory repo.** Found that `C:\Users\mhoward` itself is a git repo
  (tracking the whole home directory, including things like `.ssh/` and
  `NTUSER.DAT` — no commits made there by this project). Initialized an
  independent `git init` inside `mobiOverlay/` instead, since a GitHub
  Actions workflow needs to live at an actual repo root, and this project
  clearly shouldn't be nested inside a home-directory-wide repo.

- **2026-09-03 — CI release build verified end-to-end before wiring up
  automation.** Built `mobiOverlay.exe` locally with PyInstaller
  (`mobioverlay.spec`, onefile + windowed) and ran the actual packaged exe
  with a `modules/` folder copied next to it, matching the real
  distribution layout. Confirmed: bundled fonts render, both real modules
  load externally, live API data fetches correctly, config persists next
  to the exe. One non-obvious thing hit during verification: a PyInstaller
  **onefile** build's visible top-level window belongs to a **child
  process** the bootloader spawns, not the process you launched — checking
  `Get-Process`/window enumeration against the original PID shows nothing
  useful (tiny working set, no window); you have to find the child via its
  parent PID to see the real app. `.github/workflows/release.yml` builds
  the exe the same way (same spec file) on a tag push and publishes it as
  a GitHub Release with a SHA256 checksum; `BUILD.md` documents the
  identical steps for anyone who'd rather build it themselves.

- **2026-09-03 — Repo pushed to GitHub, public: github.com/h2mCoreAi/mobiOverlay.**
  License: MIT (matches the user's prior ThrottleWatch project). Bundled
  fonts (Orbitron, Share Tech Mono) stay separately licensed under SIL OFL —
  see `host/assets/fonts/LICENSE.txt` — not superseded by the root MIT
  LICENSE. No release tag pushed yet — user is still heavily testing;
  `.github/workflows/release.yml` only fires on a `v*.*.*` tag, so nothing
  auto-publishes until that's deliberately pushed.

- **2026-09-03 — Card hide/show renamed to Stow/Deploy, dropdown replaced
  with a themed tray panel.** User's own instinct: generic desktop "hide/
  add" language didn't fit, asked how SC itself would handle it. SC already
  has the exact concept under different words — stowing a weapon/tool,
  deploying it again — so reused that vocabulary throughout, not just in
  UI text: `Card.stowed` signal (was `closed`), `CardContainer.stow_card`/
  `deploy_card` (was `hide_card`/`show_card`), the title-bar button reads
  "TRAY (n)" (was "+ ADD CARD"), and the plain `QMenu` dropdown became a
  custom `_TrayPanel` styled like the rest of the HUD (dark panel, cyan
  border) listing only stowed cards with a DEPLOY action, rather than a
  native OS menu checklist of everything.
  Hit and fixed a real bug while building this: `Card.isVisible()` is
  unreliable for tracking stow state — Qt's `isVisible()` reflects
  ancestor visibility too, so every card read as "not visible" (and the
  tray badge showed everything as stowed) until the top-level window
  itself had been shown. Fixed by having `CardContainer` track stowed
  card IDs itself (`self._stowed: set[str]`) instead of querying Qt
  widget visibility.
  Verified the full stow → tray → deploy cycle end-to-end via UI
  Automation (`System.Windows.Automation`, `InvokePattern` on real
  buttons, `BoundingRectangle`-derived clicks for the plain-QWidget tray
  rows) — not coordinate-guessed clicks, which proved unreliable on this
  multi-window desktop (a "click" can land on whatever window is actually
  topmost at that screen position, which `PrintWindow`-based screenshots
  don't reveal since they capture by window handle, not screen region).
  Testing stayed entirely on the secondary monitor throughout — never
  touched the user's active game session on the primary display.

- **2026-09-03 — Clicking anywhere in a card raises it to front.**
  User-requested. Implemented as an application-wide event filter in
  `CardContainer` (`QApplication.instance().installEventFilter(self)`)
  rather than a `mousePressEvent` override on `Card` — a press on a child
  widget (combo box, button, label) never bubbles up to the parent Card's
  own `mousePressEvent`, so watching at the application level is the only
  reliable way to catch a click anywhere inside a card, not just its
  header. Smoke-tested via UI Automation (click doesn't crash the app);
  full visual confirmation of the raise (two overlapping cards) needs a
  human dragging one over the other, not yet done by this session.

- **2026-09-03 — Never embed our own UEX token; "most profitable" done as
  a client-side brute-force scan instead.** User asked how to make
  Commodity Prices smarter (query for most profitable) and separately
  drew a hard line on distribution: no shared app token baked into the
  exe, ever — it'd get extracted from the public repo immediately and
  either get abused by randoms or revoked by UEX, breaking the feature for
  everyone at once. Investigated the "real" ranking path first:
  `commodities_ranking` is deprecated (confirmed live, returns empty). Its
  documented replacement `commodities_averages` requires a bearer token
  AND is still per-commodity (`id_commodity` required) — not actually a
  ranking/discovery query even with a token. With per-user tokens ruled
  out as a *requirement* (optional/degraded is fine, required for a core
  feature is not) and the "official" path a dead end anyway, landed on:
  scan every commodity via `commodities_prices` (already anonymous, ~150-
  200 calls), compute margin client-side, cache 30 min, chunk via `QTimer`
  so it doesn't freeze the UI or look like a stub while running. See
  docs/modules/commodity-prices.md for the mechanics.

- **2026-09-03 — Price Lookup renamed to Commodity Prices.** User noticed
  it only covers commodities (ore, agricultural goods) — the old name
  implied broader scope (items, ship components) it never had. Renamed
  the module folder, `module_id`, and class to match
  (`price_lookup`/`PriceLookupModule` → `commodity_prices`/
  `CommodityPricesModule`), not just the display string, since it's still
  pre-release and there's no cost to getting the internal name right too.
  Also dropped a hardcoded "default to Laranite if present" fallback that
  existed only because that's what got typed in while first building the
  module — not tied to profitability or any real signal. Removing it
  surfaced a latent bug (see PROGRESS.md): the new alphabetical-first
  default landed on a commodity with zero active listings, and `refresh()`
  treated that as a hard error instead of the graceful empty state the
  per-row display logic already supports. Fixed the actual bug rather than
  reintroducing a hardcoded "safe" commodity to paper over it.

- **2026-09-03 — Settings menu added; Window/Card Opacity split, Text Size
  added.** User: opacity slider belonged in a real settings surface, not
  loose in the title bar, and 1440p made the default text hard to read.
  Added `_SettingsPanel` (same themed Qt.Popup pattern as the Tray).
  Window Opacity (existing slider, relocated) and the new Card Opacity
  (card background alpha, independent of the window — lets you see through
  cards without making window chrome/text transparent too) both apply
  live: `Card._apply_border` now composites `theme.BG_PANEL` through
  `theme.hex_to_rgba` at the card's stored opacity, and
  `CardContainer.set_all_card_opacity` broadcasts a change to every
  existing card immediately. Text Size does NOT apply live — every
  font-size in the app is a literal baked into a stylesheet string built
  once (`theme.fpx()`, a scale-aware helper, reads `theme.FONT_SCALE` at
  the moment each stylesheet function runs); rebuilding and reapplying
  every stylesheet on every existing widget live was out of scope for this
  pass, so it's an honest "applies next launch" setting instead, labeled
  as such in the panel. `theme.FONT_SCALE` must be set from config
  (`main.py`) before `MainWindow` is constructed and before modules are
  imported — `host/main_window.py`'s top-level `STYLESHEET` constant had
  to be converted from a module-level string (frozen at import time, i.e.
  before config even loads) into a function called at construction time,
  otherwise the scale-aware helper would always see the default 1.0.

- **2026-09-03 — Dropped real-time text scaling; kept everything else from
  that request.** Considered actually attempting live font rescaling
  (every stylesheet rebuilt and reapplied to every existing widget on a
  Settings change) rather than assuming it was too painful, per the user's
  instruction. User then explicitly cut it before implementation to keep
  scope sane. In its place: reworded the existing Text Size description
  to point at the new Relaunch button rather than building a separate
  toast/notice — the panel already had a persistent description line, no
  new UI needed.

- **2026-09-03 — Find Most Profitable split into Retrieve Data +
  Find Most Profitable; user caught a real correctness bug.** The
  original combined scan computed sell-minus-buy margin across ALL
  systems, silently ignoring the Best Sell/Best Buy system filters right
  above it on the same card — a real bug the user found by asking "does
  it take into account the selected system filters?" rather than one
  caught by our own testing. Fixed by separating concerns: "Retrieve
  Data" does only the network fetch (~150-200 calls, cached in
  `_all_commodity_data`, no margin math); "Find Most Profitable" is a
  separate, instant, local-only action that reads `sell_system`/
  `buy_system` filter state at click time — same filter logic already
  proven correct in `_apply_filters`, just applied across every cached
  commodity instead of one. This also enables the countdown/force-update
  UX below, since "when was the data retrieved" is now a separate concept
  from "what did we do with it."

- **2026-09-03 — Countdown + "FORCE UPDATE?" confirm on Retrieve Data.**
  User-specified UX: after retrieving, the button counts down (MM:SS) to
  the next recommended refresh (reuses the existing 30-min cache window).
  Clicking mid-countdown doesn't immediately re-fetch — it swaps to
  "FORCE UPDATE?" as a confirm step (auto-reverts after 4s if ignored,
  via a singleShot `QTimer`), and only a second click while that's showing
  triggers an actual forced retrieve. One implementation detail worth
  recording: verifying the two-click force-confirm sequence requires both
  clicks to land within that 4-second window, which is impossible across
  two separate tool-call round-trips (each has real latency exceeding 4s)
  — had to combine "click, verify prompt, click again" into one atomic
  script to test it at all. Same underlying lesson as the earlier
  UI-Automation-popup-timing issue, one level up: it's not just popups
  that need atomic scripts, anything with its own auto-reverting timeout
  does too.

- **2026-09-03 — Settings > Relaunch button; found and fixed a real
  process-leak bug while verifying it.** Spawns a fresh instance via the
  new `host/paths.py` `relaunch_command()` (mirrors `app_root()`'s
  frozen-vs-source detection) and closes the current one. First
  implementation only called `self.close()`, which turned out to be
  insufficient: the Settings panel itself is where the Relaunch button
  lives, and it's a separate top-level `Qt.Popup` widget still open at
  the moment it's clicked — `self.close()` only closes `MainWindow`, not
  that popup, so Qt's `quitOnLastWindowClosed` never fires and the old
  process lingers forever (confirmed live: old PID stayed `Responding:
  True` indefinitely, spawned the new instance as its own child process).
  Fixed with an explicit `QApplication.instance().quit()` after
  `self.close()`, not relying on last-window-closed detection at all.
  Re-verified clean afterward: old PID fully exits, exactly one new PID
  ends up running, its window is the real visible one.

- **2026-09-03 — Trade Route Optimizer: "Admin -" terminal names fixed;
  terminal picker made searchable.** User asked why so many terminals
  showed as "Admin" — checked the raw API response directly rather than
  guessing: `name` really is `"Admin - Baijini Point"` (that's genuinely
  the in-game kiosk's name, not a UEX data error), but `nickname` gives
  the clean location name (`"Baijini Point"`, `"ARC-L1"`). Switched the
  terminal picker to `nickname`. `commodities_routes` (used for the route
  list itself) has no equivalent nickname field for destinations, so
  those fall back to stripping the `"Admin - "` prefix by hand.
  Also made the terminal combo editable with a filtering `QCompleter`
  (`Qt.MatchContains`) per explicit request — type to narrow a 100+ item
  list, or still scroll the full dropdown. Had to switch its signal
  connection from `currentTextChanged` to `textActivated`: an editable
  combo's `currentTextChanged` fires on every keystroke, which would
  trigger a refresh (and an "unknown terminal" error) per character
  typed rather than only on a real, committed selection.
  Verification note: confirmed both the display-name fix (screenshot) and
  that the field genuinely accepts keyboard input (real keystrokes did
  change its content), but couldn't cleanly demonstrate the completer's
  filtered dropdown popup itself through UI Automation in this session —
  `SendKeys` timing produced garbled input (`"arcbbbbb..."`) rather than
  clean text, and `ValuePattern.SetValue` doesn't reliably trigger Qt's
  real keystroke-driven signals (same class of issue as the earlier
  combo-selection problem). The underlying pattern
  (`QCompleter` + `MatchContains` on an editable `QComboBox`) is
  standard, well-tested Qt behavior — left for the user to confirm
  directly rather than over-investing further in fighting the test
  tooling.

- **2026-09-04 — Trade Route Optimizer: added a "Sell In" destination
  filter and clearer buy/sell labeling.** User had to ask what a route
  row actually meant (origin terminal = buy, each row's destination =
  sell) — real signal the layout wasn't self-explanatory. Added "▲ BUY
  HERE" above the origin picker and changed each row's destination text
  from a bare "→ ..." arrow to "SELL AT ...". Also added the destination
  filter itself: `commodities_routes` rows already carry
  `destination_star_system_name` per row, so this is pure client-side
  filtering (populate the dropdown from systems seen in the fetched
  routes, filter+resort before slicing to the top 5) — identical pattern
  to Commodity Prices' sell/buy filters, no new API call.
  Verification note: confirmed the UI renders correctly (labels, filter
  dropdown present) and confirmed the filter *logic* is exactly correct
  by extracting it into a standalone script with sample data (no Qt
  involved) — Pyro-only and Stanton-only both returned exactly the right
  rows. Could NOT get UI Automation to actually change the destination
  combo's selection to prove the live interaction end-to-end: tried
  `SelectionItemPattern.Select()` on the popup item, `ValuePattern
  .SetValue()`, and real keyboard nav (`{F4}{DOWN}{DOWN}{ENTER}` after
  `SetForegroundWindow`) — all three reported success but the combo's
  value never actually changed on readback, even within one atomic
  script. That's a strong signature of a genuine Qt-accessibility-bridge
  limitation for `QComboBox` popup *selection* specifically (buttons via
  `InvokePattern` have been reliable all session) rather than an app bug
  — logged as a general lesson, not just for this feature.

- **2026-09-04 — Whole-app minimize-to-pill, Collapse All, and a
  system-wide Stow/Deploy hotkey.** All user-requested, implemented
  together since the hotkey's whole purpose is toggling the same
  stow/deploy behavior the minimize button drives directly.
  - **Minimize-to-pill** reuses `MainWindow` itself rather than spawning
    a second window — hides `card_container`/size grip, hides
    Tray/Settings/minimize in the title bar (keeps wordmark + close),
    resizes down to the wordmark's `sizeHint()` (padded for
    `MainWindow`'s own content margins, which `sizeHint()` alone
    ignores), and remembers the pre-stow geometry to restore exactly.
    Avoided a second top-level window on purpose — it would've resurrected
    the "which window is actually on top" z-order/focus fights this
    session already hit repeatedly with popups.
  - **Global hotkey required real Win32 API access** (`ctypes`,
    `RegisterHotKey`/`WM_HOTKEY`), not a Qt `QShortcut` — shortcuts only
    fire while the app itself has focus, useless for "toggle while I'm
    alt-tabbed into the game," which is the actual use case per the
    request ("utilized more as part of the player's UI"). New
    `host/hotkey.py`, a `QAbstractNativeEventFilter` installed on
    `QApplication` to catch `WM_HOTKEY` regardless of focus.
  - **Hard requirement: at least one modifier.** A hotkey capture field
    that accepted a bare key would let someone accidentally register,
    say, plain `M` as a system-wide hotkey — hijacking that key
    everywhere, including normal typing in the game. Rejected before
    `RegisterHotKey` is ever called, with an inline message telling the
    user why.
  - Verification is split, and the gap matters: the click-to-arm
    "listening" state change is confirmed live (real mouse click,
    visible text change). The key/modifier→VK-code parsing logic is
    confirmed correct in isolation (`Ctrl+Shift+M` → exactly
    `MOD_CONTROL|MOD_SHIFT` + `VK_M`, using real `Qt` constants, no GUI
    involved). But actual keystroke capture — pressing the combo while
    the field is armed — could not be verified at all: `SendKeys`,
    even after `SetForegroundWindow` on the main window, never visibly
    reached the field, and `config.json` confirmed nothing was actually
    saved. Root cause suspected rather than confirmed: the Settings
    panel is its own `Qt.Popup` HWND, and focusing the *owner* window
    doesn't necessarily focus the popup's own HWND — `NativeWindowHandle`
    came back empty for the field too, so there wasn't even a handle to
    route input to directly as a workaround. This is a real, flagged gap
    in PROGRESS.md, not a "probably fine" — a human needs to actually
    click the field and press a real combo before trusting it works.

- **2026-09-03 — The hotkey field's real bug was a PySide6/Qt6 API
  mismatch, not focus routing.** The previous entry's "SendKeys never
  reaches it" theory turned out to be a red herring for the underlying
  functional bug (though the focus-routing problem is real and separately
  documented in memory). `_HotkeyField.keyPressEvent` built its display
  string with `QKeySequence(int(event.modifiers()) | key)` — but in
  PySide6/Qt6's new-style enums, `event.modifiers()` returns a
  `Qt.KeyboardModifier` flag object that `int()` cannot coerce, raising
  `TypeError` on every single keypress, for every key, with or without a
  modifier. The exception was thrown and silently swallowed by Qt's event
  loop before `set_stow_hotkey()` was ever reached — so the field had
  *never* worked, for anyone, the entire time it existed. Fixed with
  `QKeySequence(QKeyCombination(event.modifiers(), key))`. Confirmed by
  reproducing the exact `TypeError` in an isolated script, then confirming
  the fix produces correct strings for both a bare `F3` and a modified
  combo (`Ctrl+Shift+M`).

- **2026-09-03 — Window background transparency decoupled from card
  opacity; `WINDOW OPACITY` now controls only the empty space.**
  `setWindowOpacity()` scales the whole rendered window's alpha uniformly
  at the compositor level, so cards could never look more opaque than the
  window they sit in — the two opacity sliders were coupled despite
  looking independent in the UI. Switched to `Qt.WA_TranslucentBackground`
  with a per-pixel rgba background on `MainWindow` (same
  `theme.hex_to_rgba()` pattern `Card.set_card_opacity()` already used),
  so the void area's alpha is now genuinely independent of each card's own
  background alpha. Title bar and panels keep their own solid/gradient
  backgrounds, unaffected by this slider — that's a visible behavior
  change from before (previously lowering window opacity dimmed the
  title bar too), but it's the correct trade for making the setting mean
  what its label says.

- **2026-09-03 — Pill and deployed-window positions are tracked and
  persisted independently.** Previously the pill always reopened wherever
  the full-size window last was, forgetting any position it had been
  dragged to; `pre_stow_geometry` lived only in memory and was lost on
  restart if the app closed while stowed. Added a `pill_geometry` config
  key alongside `pre_stow_geometry` (already in the config schema but
  unused until now), both updated via debounced `moveEvent`/`resizeEvent`
  handlers on `MainWindow` (400ms after the last move, so a drag doesn't
  hammer disk I/O) rather than only at the moment of stow/deploy.

- **2026-09-03 — Both hotkey and transparency fixes above shipped broken;
  root causes were different from what they looked like.** Caught by the
  user re-testing the live app rather than by this session's own
  verification, which is the actual failure worth learning from:
  - The hotkey "fix" (`QKeyCombination(event.modifiers(), key)`) still
    threw `TypeError` on every keystroke — `QKeyCombination` needs an
    actual `Qt.Key` enum for its key argument, and `event.key()` returns
    a plain `int` in PySide6. The isolated test written to confirm the
    first fix used `Qt.Key_F3` directly, which is already the right
    type, so the test couldn't have caught this even in principle — it
    wasn't testing the real code path. Fixed with `Qt.Key(key)`, and this
    time verified by importing the actual `_HotkeyField` class and firing
    real `QKeyEvent`s at its real `keyPressEvent` end-to-end, which is
    the only version of this check that could have caught either bug.
  - The transparency fix (`WA_TranslucentBackground` + rgba background)
    was missing `Qt.WA_StyledBackground`, without which a plain `QWidget`
    doesn't paint a QSS `background` property at all — so the window was
    permanently fully transparent no matter the slider, not "decoupled
    from card opacity" as intended. This one had no isolated test at all
    the first time; a synthetic-widget check written afterward to
    understand it turned out to be unreliable too (`QWidget.grab()`
    reports alpha=0 for `WA_TranslucentBackground` widgets even when they
    render correctly on real screen via DWM), so the real signal was
    reading `PrintWindow` screenshots of the actual running app, not a
    synthetic reproduction.
  - Lesson: for anything routing through PySide6/Qt6's new-style enums,
    "isolated test passes" only means something if the test uses the
    exact runtime types the real code path produces (e.g. `event.key()`
    is `int`, not `Qt.Key`) — reproducing the shape of the call, not just
    its intent, is what makes a regression test meaningful here.

- **2026-09-03 — Window opacity fix #3: QSS `background:` on a
  `WA_TranslucentBackground` top-level widget doesn't reliably work at
  all; switched to painting the void directly in `paintEvent()`.**
  `WA_StyledBackground` (the previous fix) was a real, necessary
  requirement but not sufficient — the user reported no visible change
  from the slider at any position. Live debug output proved the Python
  side was unambiguously correct (right rgba string recomputed and
  reapplied on every slider move, both attributes `True`, right class
  name for the QSS selector), and `GetWindowLong`/`GWL_EXSTYLE` confirmed
  Windows genuinely created the native window with `WS_EX_LAYERED`. So
  the bug was in Qt's own QSS-background-to-layered-window compositing
  path specifically — a real, if obscure, rough edge, not a code mistake
  this time. Fix: paint the void directly with `QPainter` in
  `CompositionMode_Source` inside `MainWindow.paintEvent()`, which writes
  ARGB pixels straight into the translucent surface instead of going
  through the QSS pipeline. Proof this actually changed something (not
  just another unverified guess): sampling the same screen pixel at
  100% vs. 40% opacity went from `(6, 9, 11)` — exactly `theme.BG_VOID`,
  correctly rendered — down to `(2, 4, 4)`, matching premultiplied-alpha
  scaling by ~0.4 almost exactly. The *previous* (QSS) attempt sampled as
  flat `(0, 0, 0)` at both settings — not even the right color, let alone
  reactive to the slider — which is hard confirmation the QSS path was
  never really working, not just hard to verify.
  Still can't fully confirm the on-screen result against real desktop
  content behind the window (PrintWindow only proves Qt is producing
  correct, opacity-reactive premultiplied pixel data, not what DWM does
  with it against the desktop) — needs the user's own eyes as the final
  check, same as before, but now with much stronger evidence the
  mechanism itself is doing the right thing.

- **2026-09-03 — Replaced RegisterHotKey with a low-level keyboard hook
  (the `keyboard` library), because RegisterHotKey doesn't fire while
  Star Citizen has focus.** The hotkey field's capture bug (int vs
  Qt.Key) was fixed and confirmed working — but the user then reported
  the hotkey still didn't actually toggle stow/deploy while the game was
  focused, even with a correctly-captured combo. `RegisterHotKey` posts
  `WM_HOTKEY` through the normal window message queue; a fullscreen or
  exclusive-input game can block that queue from ever reaching a
  background process's hotkey registration. Told to look at how
  ThrottleWatch (a separate, already-shipping Star Citizen overlay by
  the same author, at `D:\Documents\Mitch\Star Citizen\ThrottleWatch\
  throttle_watch.py`) handles this — its hotkey reliably works with the
  game focused. It uses the `keyboard` Python library, which installs a
  low-level global keyboard hook (`WH_KEYBOARD_LL` via
  `SetWindowsHookEx`) that intercepts the actual keyboard input stream
  below the window message queue entirely, so which window currently has
  focus is irrelevant to whether the hook sees the keystroke.
  Ported ThrottleWatch's `HotkeyState` design directly rather than
  reinventing it: raw key down/up events (not `keyboard.add_hotkey`,
  whose shared cross-hotkey pressed-keys dict can get a modifier stuck
  "held" forever if a single key-up event is ever lost — e.g. a UAC
  prompt stealing focus mid-combo, which happens easily alt-tabbing out
  of a fullscreen game) plus a `GetAsyncKeyState`-based `reconcile()`
  watchdog that self-heals exactly that stuck-state case. Also ported the
  capture mechanism — `keyboard.read_hotkey()` in a background thread —
  replacing the Qt-keyPressEvent-based capture entirely, which
  incidentally also resolves the Qt.Popup-keyboard-focus unreliability
  documented earlier for that field, since this capture path doesn't
  depend on Qt focus routing at all.
  `keyboard.hook()`'s callback runs on the `keyboard` library's own
  dispatch thread, not the Qt/GUI thread — `GlobalHotkey` is a `QObject`
  with a `Signal`, and emitting a Qt signal from a non-GUI thread is the
  standard, correct way to marshal a callback that touches Qt widgets
  back onto the GUI thread (Qt auto-queues cross-thread signal delivery).
  This plays the same role ThrottleWatch's `self.root.after(0, ...)`
  plays for marshaling onto the Tk thread.
  Verified `HotkeyState`'s combo-matching logic directly with synthetic
  key events (not the live hook, which needs a human's real keyboard):
  bare `f3` fires on down and correctly re-fires on a fresh press after
  release, a multi-key combo (`ctrl+alt+p`) correctly waits for every
  modifier to be down before firing, and `clear()` correctly stops
  dispatch. New dependency: `keyboard>=0.13` (already vendored/used by
  ThrottleWatch, confirmed installed in this environment).
  Config schema changed: `hotkey_mod`/`hotkey_vk` (Win32 concepts)
  replaced by a single `hotkey_combo` string (the `keyboard` library's
  own canonical form, e.g. `"f3"` or `"ctrl+alt+p"`) — simpler, and
  matches what `keyboard.read_hotkey()` already returns with no
  translation needed. Old keys left as harmless orphans in existing
  users' `config.json` rather than actively migrated/deleted.

- **2026-09-03 — Fixed a real race in pill-position persistence: a
  shared debounce timer read stow-state at fire time, not per-event.**
  The pill-position-memory feature (shipped earlier this session) used
  one `QTimer` restarted on every `moveEvent`, which after a 400ms quiet
  period would save either `pill_geometry` or `pre_stow_geometry`
  depending on `self._app_stowed` *at that moment*. This breaks the
  instant two different-state moves happen within the same 400ms window:
  drag the pill, then deploy shortly after (an entirely natural thing to
  do — most people don't pause half a second after dragging something
  before clicking it) restarts the same timer from the deploy's own
  `move()`/`resize()` calls, so when it finally fires it reads
  `self._app_stowed == False` and saves `pre_stow_geometry` — the pill's
  just-dragged position is never written to disk at all, silently.
  Fixed by removing the debounce for moves entirely and instead saving
  position immediately, synchronously, at the exact moments a move
  actually finishes: `_TitleBar.mouseReleaseEvent` (covers both pill and
  deployed-window dragging — the same handler drives both, distinguished
  by `is_app_stowed()`) and the end of `stow_app()`/`deploy_app()`'s own
  programmatic repositioning. `resizeEvent` keeps a debounce (resizing is
  naturally bursty — dozens of events for one drag of the corner grip)
  but no longer branches on stow state at all, since the grip is hidden
  whenever the app is stowed and so can never race against a pill move.

- **2026-09-03 — Deploying via the hotkey now takes real OS foreground
  focus, via AttachThreadInput, not the "tap Alt" heuristic.** User
  asked that toggling into full mode via the hotkey actually take input
  focus, not just visually appear on top while the game keeps keyboard
  input. First attempt: `keybd_event`-simulate an Alt press/release
  before `SetForegroundWindow`, the commonly-cited trick for background
  processes to bypass Windows' foreground-switch lock. Live-tested with
  Star Citizen genuinely holding foreground focus (confirmed via
  `GetForegroundWindow` before the test) — `SetForegroundWindow` reported
  success and, checked immediately from inside the same process, the
  window *was* foreground — but a separate follow-up check (a new
  PowerShell process, one tool-call round-trip later) found focus back
  on Star Citizen. Root cause: that gap was pure measurement latency
  (~300-500ms from spawning a new process to run the check), not the fix
  failing — an atomic single-script test (press F3, then sample
  `GetForegroundWindow` at 20/200/800ms, all in one script with no
  cross-process delay) confirmed mobiOverlay held foreground at every
  sample. Switched anyway to `AttachThreadInput` (temporarily joining
  this process's input queue with the current foreground window's
  thread, called around `SetForegroundWindow`/`BringWindowToTop`) since
  it's the actual documented mechanism Windows' foreground-switch
  restriction checks against, rather than relying on a lock-timeout
  heuristic — more robust than the Alt-tap trick even though that one
  turned out to work too once measured correctly. Also caught and fixed
  a separate real bug along the way: the first draft called
  `SetForegroundWindow`/`GetForegroundWindow` without declaring
  `ctypes` `argtypes`/`restype`, which defaults to 32-bit `c_int` — on
  64-bit Windows an `HWND` is a 64-bit pointer, so window handles could
  have been silently truncated. Fixed by declaring proper
  `ctypes.wintypes.HWND`/`DWORD`/`BOOL` signatures throughout.

- **2026-09-03 — Commodity Prices had the same raw-kiosk-label bug Trade
  Route Optimizer already had fixed; fixed the same way.** User spotted
  `"Admin - MIC-L2"` in the Best Buy row. Checked the live
  `commodities_prices` API response directly rather than guessing: it
  has `terminal_name` (always the raw label) and `id_terminal`, but no
  nickname field of its own — unlike `terminals`, which has both `name`
  (raw) and `nickname` (clean, e.g. `"MIC-L2"`) for the same terminal.
  Fetch `terminals?type=commodity` once at card creation
  (`_populate_terminal_nicknames()`) and look the clean name up by
  `id_terminal` in `_format_location()`, falling back to the raw
  `terminal_name` if a terminal isn't in that map. Same `nickname` field
  the trade route picker already uses — not a new pattern, just applied
  to the one place it was missed.

- **2026-09-03 — UEX's `commodity_name` query param is a substring match,
  not exact — filter results client-side or the wrong commodity can win
  "best price."** User flagged Diamond's reported sell price (80,000
  aUEC/SCU) as suspiciously high. Cross-checked against UEX's own website
  (~7,800) and the raw API directly: `commodity_name=Diamond` returns
  rows for both `"Diamond"` (id 25) and `"Diamond Laminate"` (id 119) —
  a different commodity that happens to contain "Diamond" as a substring.
  `_apply_filters`/`find_most_profitable` took `max()`/`min()` over
  `price_sell`/`price_buy` across every row returned with no check that
  the row's `commodity_name` actually matched the selected commodity, so
  Diamond Laminate's much higher price silently won. Fixed by filtering
  to `r["commodity_name"] == name` right after fetching, in both
  `refresh()` and the Retrieve Data loop. Worth remembering for any
  future UEX endpoint call using a `*_name` filter param — this API
  doesn't appear to support exact-match filtering, so assume substring
  matching unless proven otherwise.

- **2026-09-04 — Small border-radius added everywhere, `theme.RADIUS = 4`.**
  User wanted the 90° corners softened globally, not just on one widget.
  Added a single shared constant and applied `border-radius:
  {theme.RADIUS}px` next to every `border:` declaration across
  `host/main_window.py`, `host/card.py`, `host/card_container.py`, and
  all three module files — cards, buttons, combos, line edits, the tray/
  settings popups, the title bar. Skipped `border: none` rules with no
  background fill (nothing to round) and `:checked`/`:disabled`
  pseudo-state rules that only override color (Qt keeps the base rule's
  radius across states on the same widget). Confirmed visually after
  relaunch.

- **2026-09-04 — The radius pass above missed the window's own true outer
  shape, including the pill.** User asked directly whether the pill got a
  radius. It hadn't: `MainWindow.paintEvent()` painted the void background
  with a plain `fillRect` (sharp corners), and that rect *is* the window's
  actual outer edge in both deployed and stowed-to-pill mode — the
  previous pass's `border-radius` only rounded the title bar's own QSS
  border, an inset element sitting inside that sharp-cornered void, not
  the window boundary itself. Fixed by painting a `QPainterPath` rounded
  rect instead of a plain rect, using the same `theme.RADIUS` constant —
  since `paintEvent` is shared by both deployed and pill states, this
  rounds both identically for free, nothing to keep in sync separately.
  Had to clear the whole rect to transparent first before filling the
  rounded path — `fillPath` alone only touches pixels inside the shape,
  so without the clear the four corners cut off by the rounding would
  keep whatever stale/garbage pixels were already in the translucent
  backing store instead of being genuinely see-through. Also bumped
  `theme.RADIUS` from 4 to 8 per the user's "increase it" ask. Confirmed
  visually on both the pill and the deployed window after relaunch.

- **2026-09-04 — Checked mobiOverlay's styling directly against a live
  MobiGlas (in-game device menu) screenshot, not memory/guesswork.**
  User asked for this explicitly. Captured the actual Star Citizen window
  via `PrintWindow` (found by window title, not by trusting a stale PID —
  the game had restarted since it was last checked this session) while
  MobiGlas was open. Observations: dark navy-black panel fills and thin
  cyan borders already matched our palette closely, no color changes
  needed — but MobiGlas's panels use a visibly larger, softer corner
  radius than ours, and each panel is clearly two-tier: a separate,
  slightly lighter, more-rounded header strip sitting above a flatter
  body, not one uniform box. Bumped `theme.RADIUS` 8 -> 10. Gave
  `_DragHeader` (card.py) its own background fill with only the top
  corners rounded and a bottom border separating it from the body —
  `theme.BG_PANEL_HEADER` already existed for exactly this in `theme.py`
  (from the original approved design mockup) but had never actually been
  wired up anywhere until now. Confirmed visually after relaunch.

- **2026-09-04 — Shifted the whole color palette from teal-black to
  MobiGlas's actual blue-gray, sampled from the live screenshot pixel by
  pixel, not eyeballed.** User asked for the app to look like it's part
  of the game's own UI. Used PIL to sample real pixel colors from
  specific regions of the MobiGlas screenshot (panel body, panel border,
  body text, deep-space background) rather than guessing from the
  earlier visual inspection. Findings: `BG_VOID` (deep space background)
  already matched almost exactly (sampled `#03080d` vs. our `#06090b`) —
  no change needed there. Everything else was off: MobiGlas panel bodies
  sample as a lighter blue-gray (`#202832`) than our near-black teal
  (`#0d1417`); its border/chrome glow is a pale ice-blue (`#87bee6`
  family), not the teal-cyan (`#2de1d0`) this app used everywhere; body
  text carries a blue-white tint (`#e4e7f3`), not teal-white. Note:
  MobiGlas *does* also use a bright mint-teal (`#57f3d0`, close to this
  app's old accent) but only for a secondary "tracked/active" status
  indicator, not as the dominant chrome color — keeping our primary
  accent teal would have kept the app looking like a HUD sitting next to
  MobiGlas rather than part of it. Updated `BG_PANEL`, `BG_PANEL_HEADER`,
  `BORDER_FLAT`, `ACCENT_CYAN`/`ACCENT_CYAN_DIM`/`BORDER_CYAN`,
  `TEXT_PRIMARY`/`TEXT_MUTED`/`TEXT_DIM` in `theme.py`, plus the title
  bar's hardcoded gradient in `main_window.py` (the only color anywhere
  in the codebase not already routed through `theme.py`). Left
  `SNAP_BORDER`/`SNAP_FILL` (purple grid-snap) and `ACCENT_AMBER` (error/
  retry) alone — unrelated to this pass. Confirmed visually after
  relaunch.

- **2026-09-04 — Named the `host/` package "mobiOverlay Core."** Docs/naming
  only — no folder rename, no import changes. `host/` remains the actual
  package path; "mobiOverlay Core" is the name used in docs and
  conversation for what it contains (window, card container, config,
  module loader, hotkey, HTTP client). Updated CLAUDE.md and
  ARCHITECTURE.md's forward-facing descriptions; left historical
  entries in this file and PROGRESS.md referring to "the host" as-is
  since this log is append-only.

- **2026-09-04 — v1.0-readiness review fixes, Critical items (C1-C4).**
  A senior-dev-style review of mobiOverlay Core flagged 4 critical gaps
  in module fault isolation before a public v1.0. Fixed:
  - **C1** (no fault isolation for hung/blocking modules) — modules run
    synchronously on the GUI thread by design (see "Module contract"
    above); a true preemptive timeout would require a threading/process
    redesign, out of scope here. Added a soft diagnostic watchdog instead
    (`main.py`'s `_timed_call`): logs a warning naming the module and
    call if `create_card()`/`refresh()` takes >2s, so a slow module is
    visible in the log instead of just "the app feels laggy."
  - **C2** (no contract validation) — `module_loader.py`'s new
    `_validate_module_contract()` checks `module_id`/`display_name` are
    non-empty strings and `create_card`/`refresh` are callable, at load
    time, before the module is used anywhere else. `main.py`'s new
    `safe_create_card()` also now guards `create_card()` (previously
    unguarded — an exception there crashed the whole app before other
    modules loaded) and validates it returns an actual `Card`.
  - **C3** (duplicate module_id) — `discover_modules()` now tracks
    claimed `module_id`s and skips (with a logged error naming both
    folders) any module trying to reuse one already claimed.
  - **C4** (`settings_schema` documented but never implemented) —
    removed from the documented contract in ARCHITECTURE.md and
    `module_base.py` rather than building it now; it wasn't used by
    Core or any of the 3 existing modules, and a fictional required
    field is worse than no field for a public module-authoring guide.

- **2026-09-04 — Logistics Hub (OCR module) ships as an optional,
  manual-install module; its deps are not bundled into the exe.**
  `modules/logistics_hub/` (OCR-driven hauling mission board reader +
  route optimizer) depends on `easyocr`, which pulls in PyTorch +
  torchvision (~500MB+). Per the Packaging decision, `modules/` is
  deliberately kept external/unfrozen so it's editable without a
  rebuild — but that also means PyInstaller never bundles a module's
  dependencies, only `host/`'s. A user who drops this module folder
  next to the packaged exe without also running
  `pip install -r modules/logistics_hub/requirements.txt` in a Python
  environment will see the module's own clear "not installed" error
  rather than a crash (see `OCR_AVAILABLE` guard in `module.py`).
  Considered instead bundling this module's deps into the exe as an
  exception to the external-modules rule — rejected for now: it would
  bloat every user's download by hundreds of MB even if they never use
  this module, just to save an optional module's users one pip command.
  Documented as an opt-in, power-user module in release notes/README
  instead. Revisit bundling (or a companion installer script) if this
  module proves popular enough to justify the packaging investment.

- **2026-09-04 — Superseded same-day: distribution is all-inclusive,
  every module always bundled together.** The "optional, manual-install
  module" framing above (same day, Logistics Hub's own deps) no longer
  reflects how the project ships — user decided to keep the modular
  *architecture* (folder-per-module stays valuable for adding/changing
  features without touching Core) but not modular *distribution*.
  Practical effect: `modules/logistics_hub/requirements.txt` (easyocr/
  Pillow) should be treated as part of the app's real dependency set
  going forward, not an opt-in extra — packaging work should fold it
  into whatever the standard install path becomes, not keep it
  separately documented as power-user-only.

- **2026-09-04 — Logistics Hub built: OCR mission-board reader + UEX-
  backed route planner.** `modules/logistics_hub/` — originally scaffolded
  by Aider (DeepSeek V4 Flash, see below) then substantially hardened by
  Claude across several real-contract test/fix rounds. Final design,
  each piece earned from a real OCR failure, not designed upfront:
  - **Contracts, not a flat stop list.** A contract holds `pickups: []`
    and `dropoffs: []` (symmetric, either can have more than one — real
    contracts use both "DROP OFF LOCATIONS (ANY ORDER)" and "PICK UP
    LOCATIONS (ANY ORDER)" panel styles). Scanning accumulates contracts
    (CLEAR to reset) rather than overwriting on every scan.
  - **Location text is resolved against real UEX data**, not guessed
    from strings: every capitalized 2-4-word phrase (plus a separate
    pass for single hyphenated station codes like "HDMS-Edmond", which
    the multi-word pattern can't see at all) is a *candidate*; only
    phrases that match a real `terminals`/`space_stations`/`outposts`/
    `cities` record survive. Letting the API be the filter turned out
    far more robust than trying to regex-parse contract narrative text
    correctly, since OCR corrupts any single mention but a real contract
    repeats each place name several times across different sentences.
  - **Cross-endpoint id collision was a real, silent-data-loss bug**:
    `terminals`, `space_stations`, `outposts`, `cities` each have their
    own independent id sequence (UEX `terminals` id 17 = "Bud's
    Growery"; `space_stations` id 17 = a completely different real
    place, "MIC-L1 Shallow Frontier Station"). Deduping by raw `id`
    silently dropped one of every colliding pair — fixed by tagging
    each row with its source endpoint at index-build time and keying
    every dedup (`_build_contract`'s merge, the location picker, route
    cost's "same terminal" check) on `(endpoint, id)` instead.
  - **Pickup-vs-dropoff role** comes from nearby keywords ("Collect X
    from Y" -> pickup; "Deliver...to Y" or a "DROP OFF LOCATIONS"/"PICK
    UP LOCATIONS" section -> dropoff/pickup) with the section header
    scoped to only apply to lines that actually look like a location row
    (contain "at") — otherwise it kept bleeding into trailing footer/
    signature text and misclassifying the contractor's own name as a
    stop.
  - **Commodities** ("Waste", "Silicon", ...) are extracted the same
    way — "Collect X from Y"/"Deliver...of X to Y" — and attached per
    pickup/drop-off, matched by substring against every name the
    location is known by (resolved candidate text, nickname, full name).
  - **Route planning**: nearest-neighbour, starting from a CURRENT
    LOCATION picker (searchable combo over the same UEX location data,
    labeled with both name and short code — e.g. "Shallow Frontier
    Station (MIC-L1)" — since search-by-code silently found nothing
    before this). Falls back to "start at the first stop" only if no
    location has been picked. **Hard constraint, not a cost tiebreaker:**
    a drop-off is ineligible until every pickup on its own contract has
    been visited — cargo can't be delivered before it's collected.
    Travel cost is currently a coarse same-terminal/same-body/same-
    system/different-system tier, not real distance — see the Next
    section, this is a known near-term follow-up (`terminals_distances`
    / `orbits_distances` exist and were verified live against real
    location pairs; the module just isn't using them yet).
  - Bare-hyphenated-code candidates ("MIC-L1" alone) can resolve to an
    unrelated shop that happens to share the exact same short-code
    nickname as the station itself, producing a spurious duplicate stop
    — fixed by suppressing the bare-code candidate specifically when a
    fuller phrase immediately follows it on the same line (the common
    case), rather than trying to merge look-alike results after the
    fact (tried a signature-based merge first; it wrongly collapsed two
    genuinely different stations that happened to share a planet, and
    was reverted).

- **2026-09-04 — Aider (DeepSeek V4 Flash) added as a secondary dev
  tool for new-module work, with a hard boundary.** Configured via
  `.aider.conf.yml` (`openai/deepseek-v4-flash`, DeepSeek's OpenAI-
  compatible endpoint — LiteLLM's built-in `deepseek/` provider doesn't
  know this model id) + a gitignored `.env` for the key. Used to
  scaffold Logistics Hub's first pass. Explicit rule given to it and
  worth keeping for any future use: **only create files under one new
  module's folder — never edit `host/` or another module.** Observed
  behavior worth remembering: it iterates against its own mistakes more
  than a stronger model would (multiple fix-commits in a row on the same
  file — pytesseract, then easyocr, then several follow-up fixes, all
  same session) — review its diffs rather than trusting a single pass.

- **2026-09-04 — Decided: a shared Location service belongs in Core
  (`host/`), not as a module other modules depend on.** All three real
  modules (`commodity_prices`, `trade_route_optimizer`, `logistics_hub`)
  independently fetch `star_systems`/`terminals` and build their own
  system/terminal pickers — duplicate API calls and, in Logistics Hub's
  case, a lot of endpoint-safe-dedup logic that the other two modules
  don't have and would benefit from. Considered making it a "location
  module" other modules pull from — rejected: `module_loader.py` has no
  mechanism for one module to depend on another (each is loaded
  independently, no registry), so that would mean inventing inter-
  module dependency wiring in Core anyway. If Core has to change either
  way, do it directly as a shared service (same tier as `UexApiClient`)
  instead of building a fake "module" that's actually Core-shaped.
  Not implemented yet — planned as a phased rollout (Core service ->
  migrate Logistics Hub -> migrate the other two -> swap Logistics
  Hub's route cost onto real `terminals_distances`/`orbits_distances`
  -> optionally share a "current location" across modules), each phase
  its own tested checkpoint before starting the next. See PROGRESS.md
  Next section.

- **2026-09-04 — Location-service phases 1-3 complete; reordered the
  remaining plan.** Built `host/locations.py` (Phase 1), migrated
  Logistics Hub onto it (Phase 2), then moved the real-distance route-
  cost swap ahead of migrating the other two modules — new order:
  Phase 3 = real distance data (done), Phase 4 = migrate Trade Route
  Optimizer/Commodity Prices, Phase 5 = shared current-location
  concept. Phase 3 turned into a much longer live-test-driven
  hardening pass than expected — every fix was verified against real
  captured Star Citizen contracts, several rounds catching genuine
  regressions from earlier fixes (see PROGRESS.md's Done section for
  the itemized list: hint-priority bugs resurfacing at a second merge
  point, short-nickname false positives, ambiguity disambiguation,
  duplicate-contract detection). Phases 4-5 not started.

- **2026-09-04 — Location-service Phase 4 complete: Trade Route
  Optimizer and Commodity Prices migrated onto `host/locations.py`.**
  Both modules' system/terminal fetching now goes through
  `LocationService` instead of their own `star_systems`/`terminals`
  calls:
  - Trade Route Optimizer: `_populate_systems` uses
    `available_systems()`; `_populate_terminals` filters
    `all_locations()` to `_endpoint == "terminals"`, the chosen
    `id_star_system`, `type == "commodity"`, `is_available_live`, and
    displays via `LocationService.display_name()` (same nickname/short-
    code disambiguation Logistics Hub already benefits from).
  - Commodity Prices: `_populate_terminal_nicknames` builds its
    `id_terminal -> display name` map the same way, from
    `all_locations()` filtered to commodity terminals, instead of its
    own unscoped `terminals?type=commodity` call.
  - `commodities_routes`' destination-terminal naming (Trade Route
    Optimizer) intentionally stays a hand-rolled `Admin -` prefix strip
    — that endpoint returns no `id_terminal` for the destination, so
    there's no id to resolve through the shared service; not a gap in
    the migration, a real endpoint limitation already documented in
    the module's own doc.
  - Verified against the real UEX API via a backend smoke script
    (available systems, Stanton commodity-terminal filtering/counts,
    a live `commodities_prices` and `commodities_routes` call cross-
    checked against the new nickname map) — not through the Qt UI.
  Phase 5 (shared current-location concept) is next and last.

- **2026-09-04 — Logistics Hub UI/UX polish batch: auto-rescan removed,
  route popout added, ROUTE renamed from "SUGGESTED VISITING ORDER".**
  User-requested batch, independent of the location-service phased plan
  (Phase 5 explicitly not being done). Notable pattern: the ROUTE popout
  is a separate top-level QWidget (Qt.Window | Qt.WindowStaysOnTopHint,
  no minimize button) that's just an alternate render target for the same
  underlying `_route_order`/`route_done` state the card already owns —
  closing it doesn't lose anything, it just switches `_render_results()`
  back to rendering into the card's own layout. It's independent of the
  main window's stow-to-pill mechanism (a resize of the same top-level
  window, not a separate widget), so popping out and stowing don't
  interact. Per-route-stop done/skip state is keyed by
  `"{contract_id}:{role}:{index}"` (not list index) so it survives
  contract removal/reordering.

- **2026-09-04 — Logistics Hub CONTRACTS list moved out of the card into
  its own detached window.** Follow-up to the polish batch above: the
  inline contracts list shared one QScrollArea with the ROUTE section
  below it, and in live testing a freshly-scanned contract reliably
  landed the user's view in the ROUTE section instead of showing the new
  contract — a shared-scroll-position problem, not a data bug (contracts
  were always saved and correct; a restart showed them fine). Rather than
  fight scroll-position/auto-scroll-to-top timing in a shared QScrollArea,
  gave CONTRACTS the same detached-always-on-top-window treatment already
  built for the ROUTE popout, and factored the shared shell into
  `_make_always_on_top_window()` so both use the same window flags/scroll
  setup. Per-contract remove still lives on the same row widget, now
  inside that window instead of the card.

- **2026-09-04 — Reverted the CONTRACTS detached-window popup; found and
  fixed a real app-quit bug in the host along the way.** Two problems
  surfaced in live testing of the previous entry's popup:
  1. The CONTRACTS list still "disappeared" after a scan — because the
     button opening it lived inside the same shared QScrollArea as the
     ROUTE section, so it was just as vulnerable to being scrolled out of
     view as the original inline list was. Fixed by giving CONTRACTS its
     own independent `QScrollArea` on the card (separate from ROUTE's),
     not a popup at all — the user explicitly didn't want the popup
     approach either.
  2. Closing the popup via its title-bar X closed the *entire app*. Root
     cause: `host/main.py`'s `QApplication` never set
     `quitOnLastWindowClosed`, so Qt's default (`True`) applied — and
     `MainWindow` (`host/main_window.py`) uses `Qt.Tool`, which Qt
     excludes from its "last window" tracking. So any ordinary
     `Qt.Window` a module opens (the popup, and the still-present ROUTE
     popout) looks like the *only* real window from Qt's point of view;
     closing it quits the app out from under the still-open, still-
     Qt.Tool main window. Fixed generally in `host/main.py` with
     `app.setQuitOnLastWindowClosed(False)` — this was latent and would
     have hit the ROUTE popout (or any future module window) too, not
     just this one popup.

- **2026-09-04 — Standardized "mobi<Name>" branding across all 4 module
  card titles; found and fixed a case bug this exposed.** User request:
  every card title reads "mobi" in white (`theme.TEXT_PRIMARY`) + the
  rest in the current blue accent (`theme.ACCENT_CYAN`) — mobiOverlay
  (main window wordmark), mobiTrade (was "Trade Routes"), mobiAim (was
  "Crosshair"), mobiCommodities (was "Commodity Prices"), mobiLogistics
  (Logistics Hub, name unchanged, only the rendering bug below fixed).
  Found a real bug while doing this: `host/card.py`'s `_DragHeader` was
  calling `title_label.setText(title.upper())` on every card title.
  Logistics Hub's title was already rich HTML and already all-uppercase,
  so `.upper()` was a harmless no-op there — but the target branding is
  **mixed case** (lowercase "mobi"), so `.upper()` would have silently
  forced every new mobi-branded title back to all caps. Proof this
  already mattered before any of this work started: the Logistics Hub
  route-popout window builds its own title separately
  (`_open_route_popout`) as mixed-case "mobi"+"Logistics", so the popout
  already rendered correctly while the card header right next to it
  showed "MOBILOGISTICS" in full caps — a real, pre-existing mismatch.
  Fixed by removing the `.upper()` call entirely; every module's
  `display_name` is now the rich-text HTML directly. The stow Tray needed
  no separate change — `CardContainer.stowed_cards()` reads back
  `card.header.title_label.text()` (whatever HTML the header ended up
  with) and `_TrayRow` renders it as-is, so it picked up the corrected
  casing for free.

- **2026-09-04 — Renamed Logistics Hub's "SELECT REGION" button to "SET
  SCAN AREA".** User flagged real ambiguity: "region" reads as an
  in-game/UEX star-system region, not the screen rectangle being
  configured for OCR capture. Renamed the button, its status message
  ("No capture region set — use SET SCAN AREA..."), and the matching
  code comments/docstring in `modules/logistics_hub/module.py`. No
  behavior change.

- **2026-09-04 — Fixed dropdown text clipping on the right edge in
  Logistics Hub's location combo and Trade Route Optimizer's terminal/
  system combos.** User-reported. Root cause: none of the project's
  `QComboBox` QSS blocks styled the `QComboBox::drop-down` subcontrol —
  once a stylesheet sets custom padding/border on `QComboBox`, Qt no
  longer automatically reserves room for the drop-down arrow the way it
  does with an unstyled native combo, so the arrow button was painted
  directly over the last few pixels of text/completer content. Fixed by
  adding an explicit `QComboBox::drop-down { width: ...px; border: none; }`
  rule plus a larger right-padding on `QComboBox` itself (enough to clear
  the arrow) to every combo style block in `modules/logistics_hub/module.py`
  and `modules/trade_route_optimizer/module.py` — the user only reported
  Logistics Hub's combo, but Trade Route Optimizer's terminal/system/
  destination-filter combos share the exact same stylesheet pattern and
  would have had the identical bug.

- **2026-09-04 — Added a startup splash screen instead of speeding up the
  slow import.** User reported a "significant delay" on launch; added
  diagnostic timing first rather than guessing (see the log in this
  conversation) and confirmed it's NOT the UEX API — `discover_modules()`
  took 2.80s of a 3.64s total startup, and 2.79s of that was Logistics
  Hub's unconditional top-level `import easyocr` (pulls in PyTorch),
  which runs before any window exists. Locations loaded instantly from
  the on-disk cache; no module's `create_card()`/`refresh()` tripped the
  existing >2s watchdog. Offered to make the `easyocr` import genuinely
  lazy (deferred to first SCAN CONTRACT click) instead — user chose a
  splash screen over that fix. New `host/splash.py`: a themed
  (`QSplashScreen`, void background, cyan border, rounded corners via
  `WA_TranslucentBackground`) splash with the two-tone mobiOverlay
  wordmark baked into the pixmap and a status line via `showMessage()`
  updated at each startup stage — including per-module ("Loading
  Logistics Hub...") via a new `on_module_loading` callback param on
  `discover_modules()`, so the 2.8s pause is now visibly explained
  rather than looking like a frozen launch. `showMessage()` only takes
  plain text, so `main.py`'s new `_plain_text()` strips the HTML tags
  out of a module's rich-text `display_name` before showing it on the
  splash. `splash.repaint()` is called after every status update since
  the caller is about to block the event loop with the next slow
  synchronous step, with no natural repaint opportunity otherwise. The
  diagnostic timing log lines added for this investigation
  (`main.py`/`module_loader.py`) were left in place — cheap, and useful
  if startup regresses again later.

- **2026-09-04 — Added a "Debug Console" toggle to Settings** (`ui.show_console`,
  default off, applies on next relaunch — same pattern as Text Size).
  Mainly matters for the packaged exe: `mobioverlay.spec` builds
  `console=False`, so stdout/stderr normally go nowhere and every
  `logging`/print call (including the startup-timing diagnostics added
  earlier this session) is silently dropped with no way to see it without
  rebuilding. `host/main.py`'s new `_maybe_allocate_console()` uses
  `ctypes`' `AllocConsole()`/`GetConsoleWindow()` to open a real console
  window and rebind `sys.stdout`/`stderr`/`stdin` to it when the setting
  is on — must run before `logging.basicConfig()` (which grabs
  `sys.stderr` at call time) and before any other import that might log,
  so `Config` is now imported and read before the PySide6 imports rather
  than alongside them. Running from an actual terminal already has a
  console (`GetConsoleWindow()` catches that) so the toggle is a no-op
  there — it only changes anything for a windowed/no-console launch.

- **2026-09-04 — Added a "by Kestryl" byline to the splash screen,
  centered below the wordmark.** User request: same two-tone split as
  everywhere else ("by " white/TEXT_PRIMARY, "Kestryl" in the blue
  accent), but as its own centered line rather than trailing inline like
  the main window's title-bar byline. Factored the wordmark's two-tone
  draw logic out into a shared `_draw_two_tone()` helper in
  `host/splash.py` since the byline needed the identical
  white-then-blue/horizontally-centered treatment at a smaller size.
  Pixmap height bumped 140 -> 150 to fit the extra line above the
  status-message area at the bottom.

- **2026-09-04 — Bug fix: Logistics Hub was auto-scanning on its own,
  appending garbage contracts.** User-reported symptom: new contracts
  appeared with "messed up" data with no SCAN CONTRACT click. Root cause:
  `host/main.py`'s generic per-module periodic-refresh `QTimer` (every
  `DEFAULT_REFRESH_SECONDS` = 300s, applies to every module uniformly)
  calls `module.refresh()` regardless of module type. Logistics Hub's
  `refresh()` only no-ops on the very first call (`self._started` guard,
  meant for main.py's one-time initial-fetch call) — every subsequent
  timer tick ran a real OCR capture of whatever was on screen at that
  moment (desktop, chat, game menus, anything), built a "contract" out of
  garbled text, and appended it. This directly contradicts the module's
  documented on-demand-only design (docs/modules/logistics-hub.md: "No
  auto-rescan — on-demand SCAN CONTRACT only"), which had only ever
  disabled the module's own now-removed opt-in auto-rescan toggle, not
  Core's separate generic refresh timer. Fixed two places: `host/main.py`
  now skips starting the periodic timer entirely when a module's
  `refresh_interval_seconds` is falsy, and `LogisticsHubModule.__init__`
  defaults its own `refresh_interval_seconds` to `0` (via `setdefault`, so
  an explicit user config value would still win). Syntax-checked both
  files; not yet live-tested by the user.

- **2026-09-04 — Bug fix: Logistics Hub reversed pickup/dropoff for a
  real contract** (user pasted a real COPY ROUTE export: "Everus Harbor"
  showed as the pickup with cargo unknown, "Seraphim" as the dropoff,
  backwards from the actual contract text). Root cause in
  `_candidate_phrases()`: OCR's two-column layout wrapped the real
  dropoff name across a line break ("...SCU of Agricultural Supplies to
  Everus" / "Harbor above Hurston:"), so the phrase regex (single-line
  only) never saw "Everus Harbor" intact on the keyworded line. It only
  resolved later via an unrelated, unhinted repeat mention two lines
  later — and the existing lookback heuristic (nearest keyword within 2
  lines back) grabbed a coincidentally-adjacent "Collect...from Seraphim"
  pickup line and mis-attributed its hint to that mention instead,
  flipping the roles. Fixed by also re-scanning a line joined with the
  next one for phrase matches, but *only* when the current line's hint
  came directly from its own text (`own_line`, not `lookback`/`section`)
  — trying this unconditionally first backfired: it let a lookback-hinted
  line's contamination reach one line further and wrongly hinted
  "Seraphim Station" too. Verified against the user's real pasted OCR
  text for both the broken contract (Everus Harbor -> dropoff, Seraphim
  Station -> neutral -> correctly falls back to pickup) and an
  already-correct multi-dropoff contract from the same export (no
  regression). Does not retroactively fix contracts already saved in
  `contracts` config — needs a rescan.

- **2026-09-04 — Two Logistics Hub route/display fixes, user-requested
  after reviewing a real (now-correct) route export.**
  1. **SCU quantity now shown alongside every commodity** ("13 SCU
     Agricultural Supplies" instead of a bare name) — the module extracted
     commodity names but silently dropped the SCU count that was sitting
     right there in the same "Deliver N/TOTAL SCU of X to..." line. New
     `_commodity_quantities()` builds a commodity-name -> total-SCU map
     once per contract (the "Collect X from Y" pickup line never carries a
     quantity itself — it's the same cargo moving through both ends, so
     the map is looked up for both roles). `_extract_commodities()` now
     returns `(name, qty)` pairs; `_cargo_label()` formats accordingly and
     still accepts bare strings for contracts saved before this change
     (old `commodities` lists in `config.json` aren't migrated). Verified
     against real pasted OCR text for a single-commodity contract and a
     genuine two-commodity contract (Waste 6 SCU + Scrap 7 SCU, same
     pickup/dropoff pair) — both quantities correct on both ends.
  2. **Drop-off now wins ties over pickup in route ordering.** When a
     station has both a due pickup and a due drop-off at equal travel
     cost (most commonly "same stop, cost 0" — already standing there),
     `_plan_route`'s nearest-neighbour `min()` previously picked whichever
     came first in `nodes`, which happened to always be pickups (built
     before drop-offs per contract in `_stop_nodes`) — an accident of
     internal ordering, not a deliberate choice. Per user direction
     (clear cargo you're already carrying before loading more), the
     nearest-neighbour cost key now breaks ties by role
     (`dropoff` before `pickup`) before falling back to list order.

- **2026-09-04 — Settings > Relaunch review, user-reported "the old
  process isn't always fully dead before the new one starts."** Found
  two real gaps on inspection (not yet reproduced live):
  1. `GlobalHotkey` (`host/hotkey.py`) stored the return value of
     `keyboard.hook()` in `self._hook` but never actually called
     `keyboard.unhook()` on it anywhere — `clear()` (used both by
     Settings' own Clear button and, previously, by shutdown) only reset
     the combo/callback, deliberately leaving the OS-level `WH_KEYBOARD_LL`
     hook installed since a user might set a new combo later without
     restarting. That's correct for the Settings Clear case but wrong for
     process exit — added a separate `GlobalHotkey.shutdown()` that stops
     the reconcile `QTimer` and actually `keyboard.unhook()`s the hook,
     called from `closeEvent` and `relaunch()` instead of `clear()`. The
     OS does remove a dead process's hook automatically, but the old
     instance was reachable for a bit *before* fully dying (see next
     item) and would have kept a genuinely live global hook until then.
  2. `relaunch()` started the new process (`subprocess.Popen`) *before*
     tearing this instance down (`self.close()` / `quit()`) — meaning
     both instances could be briefly alive together: two global keyboard
     hooks racing for the same Stow/Deploy combo, and the new instance
     reading `config.json` before this one's `closeEvent`-driven
     `window_geometry` save had landed. Reordered: save geometry + hotkey
     shutdown now happen first, then the new process is spawned, then
     this one closes.
  3. Added `os._exit(0)` as a hard stop at the very end of `relaunch()`,
     after everything that needs saving is already done. `keyboard`'s own
     listener thread is daemon (verified in the installed package,
     `_generic.py`), so it isn't the risk — but easyocr/torch's native
     (non-Python) thread pools are a known source of slow/stuck CPython
     interpreter shutdown on Windows once a Logistics Hub scan has
     actually loaded them, which lines up with the reported symptom.
     `os._exit()` skips that risk entirely instead of trusting
     `sys.exit(app.exec())` to return promptly.
  Code-reviewed and syntax-checked; not yet live-tested (needs a
  relaunch after running at least one Logistics Hub scan, to actually
  exercise the torch-loaded case the fix targets).

- 2026-09-04: **Logistics Hub debug log added** (`logistics_hub_debug.jsonl`,
  always-on, append-only JSON Lines). Purpose: accumulate real usage data
  the user can hand to an AI later to evaluate whether parsing/routing is
  holding up. Scoped with the user before building rather than assumed:
  - Always-on, no Settings toggle — simplest, and avoids forgetting to
    enable it before a session worth capturing.
  - Lives at `paths.app_root() / "logistics_hub_debug.jsonl"`, same helper
    `config.json` uses, for the same reason (must persist outside a frozen
    build's wiped temp extraction dir).
  - No size cap/rotation — user manages the file manually; scan-triggered
    logging won't grow large quickly.
  One JSON object appended per scan (`LogisticsHubModule._log_scan_debug`,
  called from `refresh()`), with `note` = `"added"` or `"duplicate_pending"`:
  timestamp, raw OCR text, every candidate phrase with its role hint and
  priority (`_candidate_phrases()`'s own output, not re-derived), the
  built contract dict (pickups/dropoffs/commodities/reward/ambiguous
  notes), and a route snapshot reusing the existing `_format_route_text()`
  (the same text COPY ROUTE already produces) rather than a second
  route-formatting implementation. Write is wrapped in try/except OSError
  so a log-write failure can never break a scan. Code-reviewed and
  syntax-checked only — not yet live-tested (needs a real scan to confirm
  the file actually gets written and is valid JSONL).

- 2026-09-04: **Bug fix: Logistics Hub relaunch showed persisted contracts
  but an empty ROUTE section.** `self._route_order` is in-memory only
  (never persisted) and was only ever recomputed by `_plan_route()` inside
  a scan, a location change, or CLEAR — `create_card()` rendered whatever
  contracts config.json restored without ever recomputing the route for
  them. Fixed by calling `_plan_route(contracts)` in `create_card()` right
  after loading, before the first `_render_results()`, when there are any
  persisted contracts. Code-reviewed and syntax-checked only — not yet
  live-tested (needs a relaunch with existing contracts to confirm ROUTE
  now shows immediately). **User confirmed 2026-09-04: fixed** — relaunch
  with existing contracts now shows ROUTE immediately.

- 2026-09-05: **Fuzzy location fallback added for OCR-garbled names that
  miss substring matching entirely.** Auditing `logistics_hub_debug.jsonl`
  against live UEX data surfaced two already-tagged `KNOWN BUG`s in
  PROGRESS.md (a pickup/dropoff role tie-break, a same-terminal duplicate
  stop) plus a third, distinct gap: a candidate with a real pickup/dropoff
  hint but zero exact/substring matches in `LocationService.resolve_all()`
  was silently dropped — no stop, no warning — whenever OCR garbled a name
  enough to miss substring matching too (a dropped/altered letter, e.g.
  "Seraphim Staton"), as opposed to being unreadable.
  Added `LocationService.resolve_fuzzy()` (`host/locations.py`,
  `difflib.SequenceMatcher` ratio against the same in-memory name index
  `resolve_all` already uses) as a deliberately separate, opt-in method —
  never folded into `resolve()`/`resolve_all()` themselves, since every
  other caller (Trade Route Optimizer's terminal picker, Commodity Prices'
  nickname lookup, this module's own CURRENT LOCATION combo) has no way to
  show an uncertainty warning, and a fuzzy guess there would look exactly
  as confident as a real match. `_build_contract`'s Pass 1 now tries it
  only when `resolve_all` found nothing **and** the candidate's hint isn't
  `neutral` (same gating already used for the ambiguous-match note path) —
  on a hit, the stop resolves normally (`merge_resolved`, so it still
  counts as the same real place if another mention already confirmed it
  unambiguously) and an amber-warning note is appended, reusing the exact
  same `ambiguous_notes` mechanism/UI already built for multi-match
  ambiguity, e.g. `"'Baijni Point' (pickup) fuzzy-matched to Baijini Point
  (96% confidence) — please verify"`.
  **Cutoff tuned from an initial 0.75 to 0.85 after live verification
  caught a real false positive**: replaying all 7 real captured contracts
  from `logistics_hub_debug.jsonl` through the updated `_build_contract`
  found OCR debris "Tech's Ll" (mangled from "microTech's Ll Lagrange
  point" — not a location mention at all) scoring 0.77 against an
  unrelated real shop named "Teach's", which would have added a spurious
  dropoff stop at the original cutoff. Every genuine OCR-garbled name in
  the same replay (dropped/altered letters, not debris) scored 0.87+, so
  0.85 cleanly separates the two without losing any real catch — confirmed
  by re-running the same 7 contracts: identical pickups/dropoffs list for
  all 7 (no regression), with two of them now carrying an accurate fuzzy-
  match warning for a candidate that previously vanished silently, in both
  cases merging into an *already*-resolved terminal (widening its `_aka`
  alias set) rather than adding a new stop. Locations-only for this pass,
  per the phased plan — commodity extraction and an editable
  correction-combo UI (so a user can override a wrong or low-confidence
  resolution) are deliberately deferred to later passes.

- 2026-09-05: **Debug log gets a per-candidate resolution trace, closing two
  remaining blind spots the fuzzy-match feature above didn't cover.** Asked
  "is there additional debugging that could be added" right after that
  feature shipped. Two gaps identified: (1) a candidate that misses *both*
  exact/substring match *and* the fuzzy cutoff still vanishes with zero
  trace — no record it was ever considered, or how close it came; (2) which
  of `_build_contract`'s five resolution paths (exact/substring match,
  suffix disambiguation, "already confirmed elsewhere," fuzzy match) won for
  a resolved candidate wasn't recorded — only the final outcome was visible.
  `LocationService.best_fuzzy_match()` (`host/locations.py`) was split out
  of `resolve_fuzzy()` — same scoring loop, no cutoff applied — so a caller
  can see the *near-miss* score for a dropped candidate; `resolve_fuzzy()`
  is now a thin cutoff-enforcing wrapper around it, unchanged for existing
  callers. `_build_contract()` gained an optional `debug_trace: list[dict] |
  None = None` out-parameter (only one call site, `refresh()`, so a safe
  additive signature change) — a trace entry gets appended at each of the
  six places a candidate's fate is decided across Pass 1/Pass 2, recording
  `outcome` (`resolved`/`ambiguous_unresolved`/`dropped_no_match`) and,
  for `resolved`, which `method` won. Deliberately an out-parameter rather
  than changing `_build_contract`'s return type — keeps the change purely
  additive/observational with zero risk to the actual resolution logic,
  `merge_resolved`, or the persisted `config.json` contract schema (the
  trace is never attached to the contract dict itself, only threaded
  separately into `_log_scan_debug`). The existing `fuzzy_matches` log field
  (2026-09-05, earlier the same day) now derives from this trace
  (`outcome == "resolved" and method == "fuzzy"`) instead of string-matching
  "fuzzy-matched" in the ambiguous-notes text — same field, sturdier source.
  **Verified via backend replay of all 7 real contracts in
  `logistics_hub_debug.jsonl`**: `_build_contract`'s output is byte-for-byte
  identical whether or not `debug_trace` is passed (confirmed by diffing the
  returned contract dict, ids/timestamps excluded); trace-entry count
  exactly equals candidate count for every scan; a genuinely irrelevant
  candidate ("Chase Hewitt", `neutral` hint) correctly shows
  `dropped_no_match` with no near-miss lookup attempted, matching the
  existing neutral-hint gating. Locations-only, same phased scope as the
  fuzzy-match feature — a runner-up score on a *successful* fuzzy match and
  a schema/build-version stamp per log entry were both considered and
  deferred as lower-value follow-ups.

- 2026-09-05: **Debug log gets a route-planning trace too, not just
  location-parsing.** User's stated goal: get to ~90% confidence the app
  isn't "doing anything stupid" on routing before switching to spot-checking
  logs occasionally instead of live-testing every change. The parsing trace
  above answers "did it resolve locations correctly" but not "did it route
  them well" — the debug log only ever showed the *final* route, giving no
  way to tell from the log alone whether `_two_opt` actually improved on the
  greedy pass or left something on the table. `_plan_route()` gained an
  optional `route_debug: dict | None = None` out-parameter (same
  observational-only pattern as `_build_contract`'s `debug_trace`) capturing
  the greedy route and its cost (via the existing `_route_cost()` helper)
  *before* handing off to `_two_opt`, alongside the final route/cost after —
  threaded through `_add_contract` (also gains the same optional param) and
  into `_log_scan_debug` as a new `route_debug` field. New `_node_label()`
  helper renders a stop as `"[PICKUP] Baijini Point (contract 0)"` for both
  the greedy and final order lists, so a reordering is readable directly
  without cross-referencing node indices. **Verified via the same 7-contract
  backend replay**: 2-opt genuinely improved 6 of the 7 scans (savings of
  5-19 cost units), one had nothing to improve (0.0) — confirms the
  optimization pass is doing real work, not a no-op, on real captured data.
  `duplicate_pending` log entries get an empty `route_debug` (`{}`), since
  the route isn't replanned until a contract actually gets added.

- 2026-09-05: **Or-opt added alongside 2-opt — a real routing gap found on
  live data, planned and fixed the same session.** Reviewing the
  `route_debug` trace added earlier the same day across several real scans
  showed the same real terminal (Everus Harbor) visited twice in one
  route — once as a pickup for one contract, once as a dropoff for
  another — instead of merging into a single stop, even though merging was
  legal (precedence-respecting) and cheaper. Root cause: `_plan_route`
  only ran 2-opt after the greedy pass, and 2-opt's move set (reversing a
  contiguous sub-segment) structurally cannot express "relocate one node
  past several others without reversing anything between them" — that's a
  different move type (Or-opt), not a bug in 2-opt itself. Measured impact
  on the live case was modest (~5 of ~153 cost units, ≈3%) but structural,
  not incidental — confirmed it'll recur any time a hub location plays
  both roles across contracts. New `_or_opt()` (mirrors `_two_opt`'s exact
  style: repeatedly try one move, keep it if `_route_cost` drops and
  `_respects_precedence` still holds, run until a full pass finds nothing —
  both existing helpers reused unchanged). `_plan_route` now alternates
  2-opt and Or-opt (2-opt first each round, since either pass's moves can
  open new opportunities for the other) until neither improves, capped at
  5 rounds as a termination safety net. `route_debug`'s `two_opt_improved_by`
  field (same-day, not yet relied on anywhere) renamed
  `optimized_improved_by` to reflect the combined effect, plus a new
  `rounds_run` count. **Verified**: replayed the exact live 4-contract
  scenario that exposed the gap — final cost dropped 153 → 148 (matching
  the manual live-distance calculation done during the original review),
  Everus Harbor's two visits landed adjacent in the output (merged), 2
  rounds to converge. Also confirmed the Or-opt inner loop restarts its
  scan from the top of the current pass immediately after any accepted
  move (`break` out of both loops) rather than continuing against a stale
  pre-move sequence — an early draft didn't do this and could have
  silently discarded an improvement it had just found.

- 2026-09-05: **Three at-a-glance additions to the card, reviewed from a
  Star Citizen player's perspective mid-session** (user's framing: what's
  useful to see in a few seconds without reading the whole scrollable
  list). All three reuse data already computed — no new state, no new API
  calls: (1) a summary line ("4 contracts · 268,750 aUEC · 143 SCU peak
  cargo") below the CONTRACTS title, always visible without scrolling
  either list; (2) peak cargo is deliberately the running max along the
  *planned route* (`+SCU` on pickup, `-SCU` on dropoff, tracked via a new
  `_peak_cargo_scu()`), not a flat sum of every pickup — a flat sum
  overstates the hold size needed whenever some cargo gets delivered
  before more is picked up, confirmed by hand-tracing the same live
  4-contract scenario (peak 143, vs. a flat-sum figure that would have
  been higher); (3) a cyan-accented NEXT STOP banner above the ROUTE list
  (new `_next_stop_banner()`, distinct from the existing amber
  `_ambiguous_row`) — the first not-yet-done stop, verified to correctly
  advance once that stop is marked done. `_describe_stop()`/`_stop_entry()`
  extracted from what was inline logic in `_populate_route_rows` so the
  route list, the peak-cargo walk, and the next-stop lookup all share one
  implementation instead of three. **Verified** via a backend script
  (`_total_reward`/`_peak_cargo_scu` cross-checked against a hand-computed
  trace of the same live scenario, both matched exactly) — the actual
  widgets (`_summary_label`, `_next_stop_banner`) construct real `QLabel`s
  and can't be exercised without a live `QApplication`, consistent with
  this project's existing "can't launch the actual Qt UI in this
  environment" limitation; needs a human glance in the real running app.

- 2026-09-05: **Bug reported: NEXT STOP/ROUTE invisible on the card until
  the Tracker popout was opened at least once** (same box also made the
  route stop done/skip toggle look broken — nothing to click, since the
  rows themselves weren't visible). First attempt: theorized a stale
  `_results_scroll` scroll position (matching a real, documented
  2026-09-04 bug in the old shared CONTRACTS/ROUTE scroll area) and reset
  it to 0 at the end of every `_render_results()` call. **User confirmed
  live: did not fix it.** Root cause was never actually pinned down — no
  way to run the real Qt UI in this environment to inspect it further —
  and continuing to guess blind wasn't converging.
- 2026-09-05: **Reverted inline ROUTE rendering entirely instead of
  continuing to chase the bug above.** Per user direction: NEXT STOP isn't
  a feature that'll get used, and the Tracker popout (confirmed working
  throughout) is the actual tool for working a route — so the card's
  ROUTE area now shows only a stop count + "click TRACKER" prompt, no
  per-row list, no done/skip toggling inline. This removes the whole
  broken code path (the full stop-by-stop list, the NEXT STOP banner, and
  the scroll-reset attempt above) rather than fixing it blind. Simpler
  surface area: the card owns "how many stops, how much reward, how much
  cargo" (all confirmed working live), the Tracker popout owns "walk the
  route." `_next_stop_banner()` removed entirely (unused);
  `_describe_stop()`/`_stop_entry()` kept — still shared between
  `_populate_route_rows` (popout only, now) and `_peak_cargo_scu()`.
  Also fielded in the same review: no way to confirm/edit a fuzzy-matched
  or ambiguous location from the card — this is the already-scoped-out
  correction-combo UI (see the 2026-09-05 fuzzy-match entry above, "later
  passes"), not a new finding, reconfirmed still wanted.

- 2026-09-05: **Bug fix: a pickup feeding two drop-offs of the same
  commodity only counted one of them.** User-reported live: the Tracker
  showed "PICKUP 50 SCU Titanium" from Ambitious Dream Station, missing
  that the same contract also delivers 52 SCU of Titanium to a second
  station (Seraphim) — the pickup actually needs 102 SCU total, not 50.
  Root cause: `_commodity_quantities()` mapped commodity name -> quantity
  from every "Deliver N/TOTAL SCU of X to Y" line, but a plain dict
  assignment (`qty[commodity] = ...`) meant the *second* delivery line for
  the same commodity name silently overwrote the first instead of adding
  to it — and `_extract_commodities`'s dedup-by-commodity-name then
  dropped the second occurrence entirely once resolving the pickup entry.
  Fixed two ways at once: `_commodity_quantities()` now sums instead of
  overwrites (correct for the pickup side, which needs the contract-wide
  total); `_DROPOFF_COMMODITY_RE` extended to capture the SCU quantity
  directly from its own line (`\bdeliver\s+(?:\d+/)?(\d+)\s*scu\s+of...`),
  so each drop-off's `_extract_commodities` call uses *that* line's own
  exact amount instead of looking it up in the (now summed, and therefore
  wrong for a single delivery) shared dict — otherwise summing would have
  fixed the pickup but broken every drop-off into showing the combined
  total instead of its own share. `_all_commodity_names()` updated for the
  shifted capture group (drop-off commodity is now group 2, group 1 is the
  quantity). **Verified** against the exact live contract that exposed the
  bug: pickup now correctly shows `('Titanium', '102')`, the two drop-offs
  still correctly show `52` and `50` independently — and the peak-cargo
  summary (2026-09-05, earlier the same day) was silently under-reporting
  too as a direct consequence (143 instead of the correct 193 SCU for the
  live 4-contract scenario), now fixed as the same side effect.

- 2026-09-05: **New REPROCESS button — re-parse saved contracts without
  rescanning.** Direct follow-up to the commodity-quantity fix above: fixing
  the *code* doesn't fix the 4 contracts already sitting in `config.json`
  with the old, wrong quantities baked in (`_build_contract` computes
  commodities once at scan time and persists the result; nothing re-derives
  it later), and the only existing option was CLEAR + rescan everything
  from the game — wasteful when every contract's own `raw_text` is already
  persisted (same text the debug log/COPY ROUTE export already use).
  New `_reprocess_contracts()` (`modules/logistics_hub/module.py`, right
  next to `_clear_contracts()`) re-runs `_build_contract()` against each
  saved contract's own `raw_text` and swaps in the freshly-parsed result,
  then replans the route — no OCR, no rescan, no additional UEX API calls
  beyond what `_build_contract` already does (location index is already
  loaded in-memory). Deliberately preserves each contract's original `id`/
  `scanned_at` rather than the freshly-rebuilt ones: `route_done` entries
  are keyed `f"{contract_id}:{role}:{index}"` (`_toggle_route_done`), so
  keeping the same id is what lets an already-marked-done stop stay
  correctly matched after reprocessing — this only holds as long as the
  fix being picked up doesn't change how many pickups/dropoffs a contract
  has (true for the quantity fix); a future parsing change that adds/
  removes a stop would leave a stale `route_done` entry pointing at
  nothing, same outcome CLEAR-and-rescan already has today, not a new
  failure mode. Wrapped in `_safe_reprocess()`, matching `_safe_scan()`'s
  try/except-and-status pattern — no busy-button treatment needed since
  this is pure in-memory regex/lookup work, not OCR or a network call.
  **Verified**: simulated the exact stale pre-fix state (the real Titanium
  contract with its pickup quantity hand-corrupted back to the old buggy
  `50`, plus a `route_done` entry for that same stop) and confirmed
  reprocessing corrects it to `102`, preserves `id`/`scanned_at` exactly,
  and the `route_done` entry still matches the reprocessed stop. Button
  wiring itself (not the underlying logic) can't be click-tested without a
  live `QApplication` — needs a human check in the real running app, same
  as this session's other UI-only changes.

- 2026-09-05: **REPROCESS now writes a debug log entry too.** User changed
  CURRENT LOCATION and ran REPROCESS, then asked to verify it worked —
  found nothing in `logistics_hub_debug.jsonl` to check, since only
  `refresh()` (a live scan) ever called `_log_scan_debug`. New
  `_log_reprocess_debug()` (`modules/logistics_hub/module.py`) writes one
  entry per REPROCESS run — same shape as a scan's entry, but `contracts`/
  `resolution_traces` cover every reprocessed contract at once (a list per
  field) instead of one fresh scan's single `raw_text`/`candidates`/
  `contract`, since REPROCESS re-parses everything already saved in one
  pass. Shared the actual file-write/error-handling code with
  `_log_scan_debug` via a new small `_append_debug_log()` helper rather
  than duplicating the `try/open/write/except OSError` block a second
  time. `_reprocess_contracts()` now collects a `debug_trace` list per
  contract (via `_build_contract`'s existing optional out-param, added
  2026-09-05 earlier the same day) instead of discarding it. **Verified**:
  reprocessing 2 contracts (one with a fuzzy-matched pickup) produces
  exactly one log entry with `note: "reprocessed"`, both contracts'
  resolution traces present, the fuzzy match correctly surfaced in
  `fuzzy_matches`, and a populated `route_debug`.

- 2026-09-05: **Trade Route Optimizer's origin picker replaced: system →
  terminal cascading combo → single searchable combo**, matching Logistics
  Hub's CURRENT LOCATION picker UX (editable `QComboBox` + `QCompleter` in
  `PopupCompletion` mode, `Qt.MatchContains`, case-insensitive, labeled via
  `LocationService.search_label()` so search works by name or short code).
  User asked for the two pickers to behave the same way. Deliberately kept
  **terminals-only**, not `LocationService.all_locations()` (which
  Logistics Hub's combo does use) — `commodities_routes` (the endpoint
  `refresh()` calls) requires a real `id_terminal_origin`; space stations/
  outposts/cities aren't valid origins for it, so including them would be
  a dead-end pick with no way to actually use the selection. Kept the same
  `type == "commodity"` + `is_available_live` filter the old per-system
  `_populate_terminals` already applied, just no longer scoped to one
  system at a time. Settings key renamed `origin_system`/`origin_terminal`
  → single `origin_terminal_name` (stores the combo's search-label text).
  See docs/modules/trade-route-optimizer.md for the updated card
  description.

- 2026-09-05: **`LocationService.friendly_label()` added** — user reported
  typing "Glen" found mobiLogistics' CURRENT LOCATION (CRU-L5 Beautiful
  Glen Station) but found nothing in mobiTrade's new origin combo. Root
  cause: the two combos read the exact same shared cache (confirmed, not a
  data-divergence bug), but mobiTrade's combo is terminals-only (see the
  entry above) and the `terminals` record for that same physical place
  (`id` 22, "Admin - CRU-L5") has no descriptive name of its own — its
  `name`/`nickname` are both just the bare "CRU-L5" code. The friendly name
  ("CRU-L5 Beautiful Glen Station") only exists on the sibling
  `space_stations` record for the same place, which mobiTrade's picker
  deliberately excludes. `friendly_label(terminal)` in `host/locations.py`
  looks up a matching non-terminal record by shared (normalized) nickname
  and borrows its fuller name when the terminal's own name isn't as
  descriptive — built as a shared `LocationService` helper (not a local
  mobiTrade-only fix) per user direction, so any current/future
  terminals-only picker gets the same resolution. Deliberately excludes
  other `terminals` records from the candidate pool (a same-station
  facility like "Landing Services - CRU-L5" is textually longer than the
  real place name but isn't the place's name — an earlier version of this
  fix picked exactly that facility name by mistake before restricting the
  lookup to non-terminal endpoints). Verified against the real
  `locations_cache.json`: 19 of 114 live commodity terminals gained a
  fuller name (all Lagrange-point stations plus GrimHEX), CRU-L5
  specifically now labels as "Beautiful Glen Station (CRU-L5)" and matches
  "glen"; terminals that already had a real name of their own (e.g. "Bud's
  Growery") are unchanged.

- 2026-09-05: **mobiCommodities' "Find Most Profitable" (and Best Sell/Best
  Buy) made stock-aware — user caught a real mobiTrade/mobiCommodities
  disagreement.** mobiCommodities said Compboard was most profitable to buy
  at Rayari Kaltag and sell at Shubin SM0-22; mobiTrade said Distilled
  Spirits (sell at MIC-L5) was the best route from the same origin.
  Investigated live against the real UEX API: `commodities_routes` really
  does return Distilled Spirits → MIC-L5 as the top route by total profit
  (3,156,000 aUEC) from Rayari Kaltag — mobiTrade was correct. Compboard is
  in that same route list, worth only 15,080 aUEC total, because Rayari
  Kaltag has just 2 SCU (`scu_buy: 2`) of it in stock — huge per-unit
  margin, negligible achievable total. Root cause:
  `find_most_profitable()` (`modules/commodity_prices/module.py`) computed
  a pure `max(price_sell) - min(price_buy)` price gap with no regard for
  `scu_buy`/`scu_sell` at all. Fixed to rank by
  `(price_sell - price_buy) * scu_buy` (best buy/sell pairing per
  commodity), capped by source stock only. **First pass of this fix also
  gated the SELL side on `scu_sell > 0` and was wrong** — caught before
  shipping by live-checking the fix against the real data that started
  this investigation: `scu_sell` reads 0 for Distilled Spirits at MIC-L5
  (mobiTrade's own correct answer) despite a real `price_sell`, and
  checked broadly across 5 commodities, `scu_sell` is 0 despite a real
  sell price 75-95% of the time — UEX just doesn't reliably track
  sell-side demand capacity the way it tracks source stock (confirmed via
  `commodities_routes`' own `scu_destination`, which mirrors `scu_origin`
  rather than reflecting an independently-tracked number). Corrected to
  gate only on `scu_buy` (BUY side, confirmed live to be 0 only when
  `price_buy` is also 0 — reliable) and leave the SELL side as a pure
  price comparison, both in `find_most_profitable()` and the regular Best
  Sell/Best Buy rows (`_apply_filters()`). Verified against live data
  before shipping: Distilled Spirits' stock-aware total (3,156,000, best
  pairing Rayari Kaltag → Admin - MIC-L5) now correctly and exactly
  matches mobiTrade's `commodities_routes` answer for the same origin;
  Compboard drops to 52,700.

- 2026-09-05: **mobiTrade's origin picker made optional — "Any Location"
  search, with a per-system BUY IN filter.** User's ask: a real trader
  often doesn't have a fixed starting terminal and wants the best trade
  *anywhere* (or anywhere in a system), then decides where to fly — not
  the other way around. Requested semantics: no filter + no location =
  whole game; filter only = that system; location picked = that terminal
  only (unchanged from before). Confirmed live against the real UEX API
  before designing anything: `commodities_routes` has **no bulk-origin
  query** — `id_star_system_origin` alone returns
  `missing_one_required_inputs`; it strictly requires one of
  `id_terminal_origin`/`id_planet_origin`/`id_orbit_origin`/`id_commodity`
  per call. So "Any Location"/BUY IN genuinely means one API call per
  candidate terminal (up to 114 for the whole game) and merging results —
  no server-side shortcut exists. Implemented as a manual **SCAN** button
  (`modules/trade_route_optimizer/module.py`, `_start_scan`/`_scan_step`/
  `_finish_scan`), ported directly from Commodity Prices' Retrieve Data
  `QTimer`-throttled scan pattern (same 120ms/~8req/sec pacing, live
  progress text, skip-on-individual-failure, rate-limit-aware abort, same
  30-min cache-countdown + "FORCE UPDATE?" confirm) rather than inventing
  a new mechanism — confirmed with user this should be an explicit manual
  action, not automatic, since `refresh()` runs synchronously on the
  host's auto-refresh timer and at startup
  (`host/main.py`'s `wrap_refresh`/`safe_refresh`, no threading) and a
  15-30+s scan must never block that path; `refresh()` is simply a no-op
  while origin is Any Location. Each `commodities_routes` row already
  carries its own `origin_terminal_name`/`origin_star_system_name`/
  `origin_planet_name` (confirmed live) — no extra tagging needed to merge
  rows from many different scanned terminals into one sorted pool.
  Route rows now show "BUY AT ..." alongside the existing "SELL AT ..."
  (confirmed with user) since origin is no longer implied by a single
  picker selection in scan mode — kept in single-terminal mode too, for
  consistency. Verified the merge/sort logic against real live data: 3
  real terminals scanned and merged, top result correctly pulled from
  whichever of the three actually had the best profit (not just the first
  terminal queried), matching what a real multi-terminal scan will
  produce.

- 2026-09-05: **Two real bugs in the above, caught by the user immediately
  after using it for real.**
  1. **Origin combo's dropdown arrow was clipped/invisible** — the BUY IN
     filter was placed in the same row as the origin combo, squeezing it
     enough that the arrow region (reserved via `_COMBO_STYLE`'s
     `padding`/`drop-down width`) had no room left; the box looked like a
     plain text field. Fixed by moving BUY IN to its own row below the
     origin combo, restoring its full width — same root-cause class as the
     right-edge combo clipping already fixed once before (PROGRESS.md,
     "Fixed right-edge text clipping..."), just reintroduced by this
     session's own layout change.
  2. **A changed MAX INVESTMENT didn't invalidate a prior SCAN's
     results.** User set a $1M cap and still saw a 54,500,000 profit
     figure on screen. Confirmed live this profit is real API-level
     impossible at that cap — scanned 15 real terminals with
     `investment=1000000`, best genuine result was 447,600; confirmed the
     `investment` param does correctly cap `commodities_routes`' returned
     `profit` server-side (Kaltag alone: 3,156,000 uncapped vs 342,849 at
     $1M). Root cause: unlike SELL IN, which re-slices already-fetched
     data client-side, `investment` changes what the API itself returns —
     but nothing invalidated a prior SCAN's rows when investment (or BUY
     IN) changed afterward, since `refresh()` no-ops in Any Location mode
     and only the explicit SCAN button actually re-queries. The screen
     kept showing pre-investment-cap numbers next to a filled-in budget
     field, which reads as "this is what $1M gets you" when it isn't.
     Fixed with `_invalidate_scan_results()` — clears displayed rows and
     sets "RESCAN NEEDED" whenever investment changes (Any Location mode),
     BUY IN changes, or origin switches back to Any Location from a
     specific terminal — a fresh SCAN click is required rather than
     silently trusting stale numbers.

- 2026-09-06: **Fixed the logistics-hub role-assignment KNOWN BUG (logged
  2026-09-04) — two distinct mechanisms in `_candidate_phrases()`
  (`modules/logistics_hub/module.py`), found together auditing a fresh
  debug log against a real live contract (Seraphim Station multi-pickup/
  multi-dropoff: "Collect Pressurized Ice/Processed Food from Seraphim
  Station" → deliveries split across Beautiful Glen, Shallow Fields, and
  Ambitious Dream Station).** App output showed "Ambitious Dream Station"
  as a *pickup* — it's actually a drop-off, printed under the contract's
  own "DROP OFF LOCATIONS (ANY ORDER)" section header.
  1. **The `own_line` joined-lookahead pass (added 2026-09-04 for the
     "Everus Harbor" line-wrap case) re-scanned the *entire* next line,
     not just the wrapped portion of the current line's own phrase.**
     Line "Collect Processed Food from Seraphim Station." (a real
     own_line pickup keyword) sat directly before the unrelated "Freight
     elevator at Ambitious Dream Station at Crusader's Ll" line purely by
     two-column OCR reordering coincidence — the joined re-scan picked up
     "Ambitious Dream Station" from that second line whole and tagged it
     `pickup` at the highest priority (`own_line`, 3), permanently
     locking out any correct later hint for the same phrase. This is
     exactly the mechanism the original KNOWN BUG entry described for
     "Everus Harbor"/contract `21c7811e`. Fixed by requiring the regex
     match to actually straddle the line join (real characters on both
     sides of the inserted space) before accepting it — a genuinely
     wrapped name always does; an unrelated phrase sitting entirely
     inside the next line never does. Purely restricts false positives;
     the original wrap-catching purpose is untouched (a straddling match
     still qualifies exactly as before).
  2. **A second, previously-undocumented mechanism produced the same
     wrong result even after fix #1**: with the bogus `own_line` hint
     gone, "Freight elevator at Ambitious Dream Station..." (no keyword
     of its own) fell to the 2-line backward-lookback check, which still
     found the same nearby "Collect Processed Food from Seraphim
     Station." pickup line and wrongly inherited its hint — even though
     the line is clearly under the active "DROP OFF LOCATIONS (ANY
     ORDER)" section header opened several lines earlier. The per-line
     hint logic checked lookback *before* the section fallback, so an
     incidental nearby keyword (belonging to a different item's flavor
     text) always won over the much stronger, on-screen structural
     section signal. Fixed by checking section first whenever one is
     active and the line looks like a real section row (contains "at" —
     the same qualifier the section fallback already used); lookback now
     only runs when no section applies. `HINT_PRIORITY` itself (which
     hint wins when the *same* phrase is seen twice) is unchanged — this
     only reorders which check computes a fresh line's *first* hint.
  **Verified** via a standalone backend script (no QApplication, no
  network — `LocationService.ensure_loaded()` read the on-disk
  `locations_cache.json`) against the exact real OCR text of the
  contract that exposed this: Ambitious Dream Station now resolves as a
  drop-off, not a pickup. Regression-checked the same way against the
  session's other two real contracts (Everus Harbor → Baijini Point, and
  the MIC-L2 Long Forest Station 4-drop-off contract) — both produced
  identical pickups/dropoffs to their pre-fix output, no change.
  **Separately noted, not fixed at the time:** the Ambitious Dream Station
  stop's own commodity came back empty (should be 5 SCU Pressurized Ice)
  — its source line is split across *three* OCR lines ("Deliver 0/5 SCU
  of Pressurized" / "to Ambitious Dream" / "Station...") with the word
  "Ice" itself orphaned elsewhere in the raw text entirely, and both
  `_PICKUP_COMMODITY_RE`/`_DROPOFF_COMMODITY_RE` were single-line
  regexes. Confirmed already wrong before this session's role-assignment
  fix too (same value, unrelated bug). **Fixed later the same session —
  see the next entry below.**

- 2026-09-06: **Fixed the commodity-extraction gap logged just above,
  same session.** Two independent problems, both in
  `modules/logistics_hub/module.py`:
  1. **A delivery line split by OCR well before its destination even
     starts is invisible to `_commodity_quantities`/`_extract_commodities`
     entirely, not just truncated.** Both regexes require "to"/the
     destination on the *same* line as "SCU of X"; "Deliver 0/5 SCU of
     Pressurized" has no "to" on its own line at all (it's on the next
     line, "to Ambitious Dream"), so `pattern.search(line)` simply never
     matched — the whole delivery vanished, not just its tail. Fixed with
     a new shared helper, `_find_delivery_match()`: starting from a line,
     progressively fold in up to 2 following lines and retry the pattern
     each time, stopping at the first match. Both commodity functions
     (and the destination-window-widening logic already in
     `_extract_commodities`, which now widens from the match's actual
     last consumed line instead of always `i+1`) were switched onto this
     helper. `_all_commodity_names()` (the "don't treat a commodity name
     as a location" guard, and now also the completion vocabulary below)
     deliberately keeps its own single-line-only matching — see #2.
  2. **Even once the delivery line resolves, its commodity name itself
     can still be truncated with no reachable fix** — "Pressurized" ends
     up alone (missing "Ice"), because "Ice" isn't on the very next line
     either; it's scrambled several lines further down, orphaned among
     unrelated trailing footer/button text ("ABANDON\nSHARE\nTRACK\nIce\n
     point\nbring\nalong:"). No amount of nearby-line joining reaches an
     orphan that far away without a real risk of grabbing the wrong
     word. Instead of chasing it, complete the truncated name against a
     *fuller mention of the same commodity already confirmed elsewhere in
     the same contract* — "Pressurized Ice" is spelled out intact
     earlier in this very contract, on lines that never got split
     ("Deliver 0/6 SCU of Pressurized Ice to Beautiful Glen"). New
     `_complete_commodity_name()`: given a candidate name and the
     contract's own `_all_commodity_names()` vocabulary, only replaces it
     when the candidate is a whole-word prefix of *exactly one* longer
     known name — anything else (already complete, no match, more than
     one candidate) is left untouched rather than guessed.
     `_all_commodity_names()` changed its return type from a bare
     lowercase set to a `{lowercase: original-cased}` dict specifically
     so the completion has real, correctly-cased text to substitute in —
     its one existing call site (`_build_contract`'s fallback-dropoff
     guard) needed no change, since membership testing against a dict
     already checks its keys. Deliberately kept `_all_commodity_names`
     single-line-only rather than also switching it onto
     `_find_delivery_match`: the completion vocabulary needs to only ever
     contain names *already known complete*, or a truncated fragment
     found via joining could end up "completing" a different truncated
     fragment instead of a genuine full name.
  **Verified** via the same standalone backend script (real OCR text, on-
  disk `locations_cache.json`, no QApplication/network): the Ambitious
  Dream Station drop-off now shows `[('Pressurized Ice', '5')]` instead
  of `[]`, and Seraphim's pickup-side Pressurized Ice total correctly
  updated from 6 to 11 (6 to Beautiful Glen + 5 to Ambitious Dream) as a
  direct consequence — both were wired through the same
  `_commodity_quantities()`/`_extract_commodities()` pipeline, so fixing
  the extraction fixed the summed total for free. Regression-checked
  contracts 1 and 3 from the same session (Everus Harbor/Baijini Point;
  the MIC-L2 Long Forest Station 4-commodity contract) — identical
  commodity output to pre-fix, no change.

- 2026-09-06: **Fixed a route-cost bug found live: the CURRENT LOCATION
  picker had resolved to a `terminals`-endpoint kiosk record ("Admin -
  Seraphim") instead of the `space_stations` record ("Seraphim Station")
  that every actual pickup/dropoff at that place resolves to — same real
  place, two different UEX records. `terminal_key()` equality (used for
  "am I already here?") only compares `(endpoint, id)`, so it didn't
  recognize them as the same stop; the real-distance lookup between them
  came back empty (UEX doesn't track a kiosk-to-its-own-station
  distance), falling back to the coarse "+5 estimate" instead of 0 — that
  fake cost made a genuinely farther stop (Ambitious Dream Station, real
  distance 2) look cheaper, sending the route on an avoidable detour.
  **Fixed at the shared root, not just this one case**: new
  `LocationService.same_physical_place()` (`host/locations.py`) also
  recognizes a `terminals` kiosk as the same stop as the
  `space_stations`/`outposts`/`cities` record it structurally belongs to
  (via `id_space_station`/`id_outpost`/`id_city`) — a real FK link
  already present in the data, not a name guess. Wired into
  `LocationService.distance()` itself (the single shared choke point
  every module already calls for travel cost), not just Logistics Hub's
  `_terminal_cost`, so any current or future caller benefits. Confirmed
  this pattern is dataset-wide, not a one-off: 822 terminal kiosks in the
  cached location data carry this same structural-parent link, all with
  their parent record present in the index. Verified it doesn't
  false-merge two *different* shops sharing the same city (only fires
  when one side literally *is* the structural parent record). Verified
  live: cost to the Seraphim pickup dropped from the fake 5 to a correct
  0, and the route no longer detours to Ambitious Dream Station first.

- 2026-09-06: **Fixed a second commodity-misattribution bug, found the
  same way (reviewing a fresh live scan against the raw OCR text) as the
  Ambitious Dream Station one earlier this session.** A contract's Port
  Tressler drop-off showed 13 SCU Corundum; the raw text clearly says 11
  ("Deliver 0/11 SCU of Corundum to Port Tressler above microTech:") —
  13 is actually Everus Harbor's own Corundum amount from a different
  line. Root cause: `_extract_commodities`'s destination-window-widening
  (added earlier to recover a destination name split across a line
  break) appended the *entire* next line and accepted a location match
  found *anywhere* in it. Here, "Deliver 0/13 SCU of Corundum to Everus
  Harbor above" is immediately followed, by pure two-column OCR
  interleaving, by an unrelated "Freight elevator at Port Tressler..."
  listing line — so Port Tressler's own extraction pass wrongly claimed
  this Everus-Harbor-bound delivery (stealing its 13 SCU), which also
  blocked the real 11 SCU Port Tressler line later in the contract via
  the dedup-by-commodity-name check. The pickup-side total (which sums
  across every delivery line regardless of destination) was unaffected —
  only the per-stop breakdown was wrong. Fixed the same way as the
  earlier `_candidate_phrases` line-wrap bug: a match found only in the
  widened (next-line) portion is now trusted only if it genuinely
  straddles the line boundary (part of it already in this line's own
  destination text) — a match sitting entirely inside the next,
  unrelated line no longer counts. A same-line match (the common case)
  is unaffected. Verified against all 3 real contracts in this session's
  debug log: Port Tressler now correctly shows 11 Corundum, and the
  other two, already-correct contracts (Baijini Point/Seraphim single-
  stop; the earlier Seraphim/Shallow Fields/Beautiful Glen/Ambitious
  Dream 4-stop contract) are unchanged.

- 2026-09-06: **Added `tests/test_logistics_hub_parsing.py`, a permanent
  regression suite of real captured contracts** — direct response to
  this session's pattern of fixing one bug, then finding a second,
  unrelated bug in the same area on the next scan (role-assignment,
  then a same-place distance bug, then a commodity-misattribution bug,
  all in `modules/logistics_hub/module.py`/`host/locations.py`). Every
  fixture is the exact raw OCR text of a contract already hand-verified
  against its own text during this session, asserting exact pickups/
  dropoffs/commodities — so a future change can't silently reintroduce
  an earlier fix's bug without a visible test failure. No framework
  dependency (plain asserts); run with `python tests/test_logistics_hub_parsing.py`
  after touching any of `_candidate_phrases`, `_build_contract`,
  `_extract_commodities`, `_commodity_quantities`, or `host/locations.py`'s
  resolution/distance logic. 6 fixtures currently, including both bugs
  found this session (`seraphim_4stop_v1_role_tiebreak_bug`,
  `mic_l2_long_forest_v2_port_tressler_theft_bug`) — deliberately named
  so a future failure names which historical bug came back. One
  additional verified-correct contract (Baijini Point -> Seraphim, 103
  Stims) was NOT added — its raw OCR text was never captured before the
  source debug log entry was wiped, and reconstructing it from memory
  would have meant a "regression fixture" that isn't actually a real
  capture; add it for real next time that shape recurs. Grow this file
  every time a new bug is found and fixed, not just at the end of a
  session — that's what keeps it actually protective.

- 2026-09-06: **Fixed a cross-endpoint id-collision bug in
  `LocationService.same_physical_place()`, caught by a `/code-review`
  pass immediately after committing it.** The FK check
  (`kiosk.get("id_space_station") == structural.get("id")`, etc.) never
  verified `structural` actually came from the endpoint that FK names —
  so a `terminals` kiosk with `id_space_station=27` would wrongly match
  ANY other record with bare `id == 27`, regardless of whether it was
  really a `space_stations` row. Confirmed real with live cache data:
  terminal 259 ("Admin - Seraphim", `id_space_station=27`) wrongly
  matched `outposts` id 27 ("HDMS-Woodruff") — a completely unrelated
  real place. This is exactly the cross-endpoint id-collision class of
  bug `host/locations.py`'s own module docstring exists to warn about
  (see 2026-09-04) — introduced by the same-place fix earlier today
  despite that. Fixed by also requiring `structural.get("_endpoint") ==
  endpoint` (the FK's own named endpoint) before accepting the match.
  Added `kiosk_fk_vs_wrong_endpoint_same_id_not_same_place` to
  `tests/test_logistics_hub_parsing.py`'s `DISTANCE_FIXTURES` using this
  exact real pair — confirmed it fails on the pre-fix code and passes
  after. Four other findings from the same review pass were triaged and
  deliberately not acted on: a `_reprocess_contracts` `route_done`-
  staleness edge case (real, but already a documented accepted
  limitation, just slightly worse than described); a
  `_find_delivery_match` line-fold edge case (real but narrow, needs a
  more careful redesign than a quick patch); and two pure-performance
  redundant-recomputation findings (correct but negligible at this
  project's actual data scale — single-contract text, 4-8 stops per
  route).

- 2026-09-06: **New module: Refinery Finder — picked up BACKLOG.md's Tier
  1.3 "Refinery Yield Calculator," but narrowed scope after live API
  investigation showed a literal calculator isn't buildable from real
  data.** Investigated the actual endpoints before designing anything
  (same discipline as Commodity Prices' `commodities_ranking` dead-end):
  `refineries_yields` gives a per-terminal/per-commodity yield
  **modifier** (confirmed live range -9 to +13), not an absolute yield
  percentage; `refineries_capacities` gives per-terminal max job size;
  `refineries_methods` gives 9 real methods with 1-3 star yield/cost/
  speed ratings; `refineries_audits` (real reported jobs, quantity in ->
  quantity_yield + quantity_inert out) has only **3 rows total** across
  the whole live dataset — checked directly, not assumed. Also checked
  `commodities` itself for any base yield%/purity field on a raw
  commodity record — none exists; raw/refined pairs link only via
  `id_parent`. Building "enter N SCU, get exact output" would require
  inventing the missing composition/base-yield constants ourselves,
  which this project has consistently refused to do. Landed on: rank
  real terminals by their actual reported yield modifier for a chosen
  raw commodity (`commodities` filtered to `is_raw == 1`, 45 real
  entries), show each terminal's capacity, and a static methods
  comparison table — all real UEX data, nothing invented. Confirmed live
  that `refineries_yields`' `id_commodity` query param does **not**
  filter server-side despite looking like a real filter (same "verify,
  don't assume" lesson as Commodity Prices' `commodity_name` substring
  surprise) — filtered client-side instead. Also confirmed terminal
  names from these endpoints ("Refinement Center - Nyx Gateway (Pyro)")
  are already clean, unlike the "Admin -" kiosk-name issue Commodity
  Prices/Trade Route Optimizer both hit, so no nickname-lookup pass was
  needed here. A terminal can report more than one yield value for the
  same commodity over time (confirmed live) — kept only each terminal's
  best reported value before ranking, so the top-5 list isn't dominated
  by one terminal's repeat submissions. Verified end-to-end against live
  data via an offscreen-Qt backend script (no visible UI in this
  environment, same limitation as every other module): 45 raw
  commodities loaded, correct top-5 ranking for Laranite (Raw) across
  Nyx/Pyro/Stanton, correct explicit "no yield data reported yet" state
  for a commodity with zero reports (21 of 45 currently have none),
  system filter narrowing results correctly, settings persisting to a
  real `config.json` on disk, and clean discovery through the real
  `discover_modules()` alongside all 4 existing modules (no duplicate
  `module_id`, contract validation passed). See
  docs/modules/refinery-finder.md for the full writeup.

- 2026-09-06: **Fixed the logistics-hub duplicate-stop KNOWN BUG (logged
  2026-09-05), reusing the same-place infrastructure built earlier this
  session for the CURRENT LOCATION distance bug.** Root cause was
  identical in shape: `_build_contract`'s `merge_resolved` deduped
  candidates by `terminal_key()` alone, so two differently-worded
  mentions of one real place that resolved to *different* UEX records
  (a `terminals` kiosk vs. the `space_stations`/`outposts`/`cities`
  record it belongs to) never merged, producing a duplicate route stop.
  Fixed by checking already-resolved entries for a
  `LocationService.same_physical_place()` match before creating a new
  entry, so both mentions land in the same stop regardless of which
  specific record either one resolved to.
  **Found and fixed a second-order regression from this same fix before
  shipping it**: two existing regression fixtures broke immediately —
  not because the merge was wrong, but because it now *also* correctly
  merges a real, previously-separate pair in those fixtures' own test
  data (`Admin - MIC-L2` kiosk + `MIC-L2 Long Forest Station`, one of
  the 822 real kiosk/station pairs confirmed earlier this session), and
  picked the uglier kiosk name as the display representative purely
  because of merge order. Fixed by preferring a structural record's name
  over a `terminals` kiosk's raw label whenever the two merge, regardless
  of which one resolved first. Verified: all 6 existing parsing fixtures
  plus a new 7th (`duplicate_stop_same_place_two_records_synthetic`)
  pass. That 7th fixture is explicitly labeled **synthetic** in the test
  file, not a real capture — the original real contract that exposed
  this bug (2026-09-05, "Seraphim The"/"Seraphim Station") predates this
  session's regression suite and its raw OCR text was never saved.
  Reproduces the exact same confirmed-live mechanism instead (`Seraphim
  Station` -> `space_stations` id 27, `Seraphim Trade` -> `terminals` id
  259 "Admin - Seraphim", both verified via a live `resolve_all()` call
  before writing the fixture, not guessed) — add the real capture for
  real if this shape ever recurs in a live scan.
  Also noted per user request: the OCR pipeline itself (capture/
  preprocessing/easyocr settings) hasn't been reviewed against the
  user's actual real-world screenshots — logged in PROGRESS.md's Next
  section as a future pass, not started.

- 2026-09-06: **Fixed the logistics-hub single-word-city KNOWN BUG
  (logged 2026-09-05), using Plan Mode to design around a risk found
  during investigation before writing any code.** `_candidate_phrases`'s
  main location regex requires 2+ capitalized words in a row, so a
  location named with one word (real example: "...Teasa Spaceport in
  Lorville." — "Lorville" is a real city) never became a candidate at
  all; only the 2-word "Teasa Spaceport" was tried, which is genuinely
  ambiguous between two different real shops there (New Deal vs.
  Kel-To, confirmed live) rather than resolving to the city itself.
  **A naive fix (any single capitalized word) was investigated and
  rejected before implementation**: confirmed live that bare planet
  names — which appear constantly via "above PLANET" in every real
  template ("above Hurston:", "above Crusader.") — collide with
  unrelated real shops (`resolve_all("Hurston")` wrongly substring-
  matches "Hurston Dynamics Showcase - Lorville"; `resolve_all("Crusader")`
  is ambiguous across 3 unrelated shops). Planets aren't part of
  `LocationService`'s indexed endpoints at all, so nothing already
  filters them out — a broad single-word pass would have flooded
  contracts with false planet-name candidates, a worse regression than
  the bug being fixed. Fixed narrowly instead: the new candidate pass
  only fires after "in " specifically (never "at "/"above "), since
  every real template seen introduces a planet via "above", never "in" —
  this targets the reported bug shape while structurally avoiding the
  planet-collision risk, not just avoiding it by luck.
  Verified live before writing the fix (not after): `resolve_all
  ("Lorville")` returns exactly one real match ("Landing Services -
  Lorville"), confirming the fix target genuinely resolves cleanly once
  offered. Verified after: the exact reported bug shape now correctly
  resolves "Lorville" as a real dropoff while "Teasa Spaceport" stays
  honestly flagged ambiguous (a real ambiguity this fix was never meant
  to resolve, not a lingering bug) — confirmed via `_build_contract`
  directly, and via a live re-check that "Hurston"/"Crusader"/"ArcCorp"
  still correctly do NOT become candidates from an "above PLANET" line
  after the fix. Added `single_word_city_lorville_synthetic` to
  `tests/test_logistics_hub_parsing.py` (labeled synthetic — the
  original 2026-09-05 real capture was never saved, same as the
  duplicate-stop fixture above) and confirmed it fails on the pre-fix
  code and passes after. All 13 regression checks pass, no existing
  fixture regressed.
