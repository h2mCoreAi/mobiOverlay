# Progress

One-page status. Session notes are in `docs/HISTORY.md`. Older
`docs/DECISIONS.md` entries that say "see PROGRESS.md" mean that archive.

## Version

- Latest tag: **v0.3.0** (`a08512f`, 2026-09-30), native taskbar minimize/maximize.
- **v0.2.0** includes pill click-through and crosshair `WS_EX_TRANSPARENT` hardening (`6a494aa`).
- Commits after `v0.3.0` were documentation and repo hygiene only, until the 2026-10-03 code-review fixes on branch `cursor/code-review-fixes-a7c1` (see `docs/DECISIONS.md`). No newer build is tagged.

## Shipped

Eight modules in one exe (~333 MB, CPU-only torch): Commodity Prices, Trade Route Optimizer, Logistics Hub, Refinery Finder, Multi-Commodity Finder, Crosshair, mobiNotes, mobiThrottle.

Location service phases 1–5 are done. Logistics Hub writes `Config.set_shared_location()`. Commodity Prices and Trade Route Optimizer default their system filters from `shared_location()` when the user has not set one.

Logistics Hub may order stops with greedy nearest-neighbor plus 2-opt on real UEX distances. That is the one exception to the no-custom-pathfinding rule in `AGENTS.md`.

## Open

- Next module candidate: Item Price Lookup / Ship Outfitting (Tier 1.4 in `docs/BACKLOG.md`).
- Performance work still open: M3, M4, and L1 in `docs/OPTIMIZATION.md`. Q1–Q4, M1, M2, and M5 are shipped.
- mobiThrottle installs its two global hotkeys (`ctrl+alt+o`, `ctrl+alt+p`) by default, so every user gets a `WH_KEYBOARD_LL` hook even without a throttle. This conflicts with the host's lazy-install rule. Not changed yet; the owner needs to decide.
- Human checks that were never closed are listed in `docs/HISTORY.md` (crosshair over the game, hotkey focus, relaunch after an OCR scan, grid-snap drag). They are unverified follow-ups, not new bugs.

## Working rules that are easy to miss

- Work on a `cursor/...` PR branch. Never push to `master` without the owner's explicit OK in the current session.
- Keep this file to one page. Add session detail to `docs/HISTORY.md` and dated rationale to `docs/DECISIONS.md` (append-only).
- Local build output (`dist/`, `dist-test/`, `build/`, `freeze-build*.log`) and runtime files (`config.json`, caches, `.mobioverlay.lock`) are not project files. They are gitignored; don't document specific local paths.

## Where to read next

| Need | Doc |
|------|-----|
| Safety rules and how to work | `AGENTS.md` |
| Contracts, config, services | `docs/ARCHITECTURE.md` |
| Why a choice was made | `docs/DECISIONS.md` |
| What to build next | `docs/BACKLOG.md` |
| One module | `docs/modules/<name>.md` |
