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
