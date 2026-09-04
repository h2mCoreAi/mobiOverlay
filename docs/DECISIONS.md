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
