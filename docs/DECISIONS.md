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
