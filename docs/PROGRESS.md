# Progress

One-page status. Session notes are in `docs/HISTORY.md`. Older
`docs/DECISIONS.md` entries that say "see PROGRESS.md" mean that archive.

## Version

- Latest tag: **v0.3.0** (`a08512f`, 2026-09-30), native taskbar minimize/maximize.
- **v0.2.0** includes pill click-through and crosshair `WS_EX_TRANSPARENT` hardening (`6a494aa`).
- `master` is ahead of `v0.3.0` by the 2026-10-03 code review (PR #12): exit/Relaunch, persistence and resilience fixes, hover-to-unlock click-through pill, mobiThrottle hotkeys unset by default. Owner-tested in a `dist-test` build, including an in-game session. **Not tagged yet.** Tagging `v0.3.1` (which publishes the release zip) is the owner's call.

## Shipped

Eight modules in one exe (~333 MB, CPU-only torch): Commodity Prices, Trade Route Optimizer, Logistics Hub, Refinery Finder, Multi-Commodity Finder, Crosshair, mobiNotes, mobiThrottle.

Location service phases 1–5 are done. Logistics Hub writes `Config.set_shared_location()`. Commodity Prices and Trade Route Optimizer default their system filters from `shared_location()` when the user has not set one.

Logistics Hub may order stops with greedy nearest-neighbor plus 2-opt on real UEX distances. That is the one exception to the no-custom-pathfinding rule in `AGENTS.md`.

## Open

- Next module candidate: Item Price Lookup / Ship Outfitting (Tier 1.4 in `docs/BACKLOG.md`).
- Performance work still open: M3, M4, and L1 in `docs/OPTIMIZATION.md`. Q1–Q4, M1, M2, and M5 are shipped.
- Tag `v0.3.1` for the PR #12 changes when the owner decides to release.
- Human checks that were never closed are listed in `docs/HISTORY.md` (crosshair over the game, hotkey focus, relaunch after an OCR scan, grid-snap drag). They are unverified follow-ups, not new bugs.

## Working rules that are easy to miss

- Work on a `cursor/...` PR branch. Never push to `master` without the owner's explicit OK in the current session.
- Keep this file to one page. Add session detail to `docs/HISTORY.md` and dated rationale to `docs/DECISIONS.md` (append-only).
- Build with PyInstaller 6.9+ (Settings > Relaunch depends on it, see `host/paths.py`).
- Local build output (`dist/`, `dist-test/`, `build/`, `freeze-build*.log`) and runtime files (`config.json`, caches, `.mobioverlay.lock`) are not project files. They are gitignored; don't document specific local paths.

## Where to read next

| Need | Doc |
|------|-----|
| Safety rules and how to work | `AGENTS.md` |
| Contracts, config, services | `docs/ARCHITECTURE.md` |
| Why a choice was made | `docs/DECISIONS.md` |
| What to build next | `docs/BACKLOG.md` |
| One module | `docs/modules/<name>.md` |
