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
