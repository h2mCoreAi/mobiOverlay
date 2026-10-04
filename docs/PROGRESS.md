# Progress

One-page status. Session notes are in `docs/HISTORY.md`. Older
`docs/DECISIONS.md` entries that say "see PROGRESS.md" mean that archive.

## Version

- Latest tag: **v0.3.1** (`b93ee83`, 2026-10-03), the PR #12 code review: exit/Relaunch, persistence and resilience fixes, hover-to-unlock click-through pill, mobiThrottle hotkeys unset by default. Owner-tested in a `dist-test` build and in-game. The release zip was published by GitHub Actions.
- **v0.3.0** (`a08512f`, 2026-09-30): native taskbar minimize/maximize.
- **v0.2.0** includes pill click-through and crosshair `WS_EX_TRANSPARENT` hardening (`6a494aa`).

## Shipped

Eight modules in one exe (~333 MB, CPU-only torch): Commodity Prices, Trade Route Optimizer, Logistics Hub, Refinery Finder, Multi-Commodity Finder, Crosshair, mobiNotes, mobiThrottle.

Location service phases 1–5 are done. Logistics Hub writes `Config.set_shared_location()`. Commodity Prices and Trade Route Optimizer default their system filters from `shared_location()` when the user has not set one.

Logistics Hub may order stops with greedy nearest-neighbor plus 2-opt on real UEX distances. That is the one exception to the no-custom-pathfinding rule in `AGENTS.md`.

## Open

- Next module candidate: Item Price Lookup / Ship Outfitting (Tier 1.4 in `docs/BACKLOG.md`).
- **Optimization pass is finished on branch `cursor/optimizations-n1-n2-m4` (unmerged, untested by the owner).** Shipped there: N1/N2, M3, M4, L1, L2, L3 (resolves Q5), L4, N3. Details and the evidence for each are in `docs/OPTIMIZATION.md`. Needs an owner test in a `dist-test` build before merge: scans no longer freeze the UI, a stale location cache loads at once, Commodity Prices restores its last download, Logistics Hub still scans/plans/grades, and the new lite exe (`MOBI_LITE=1`, built but never launched) starts.
- Human checks that were never closed are listed in `docs/HISTORY.md` (crosshair over the game, hotkey focus, relaunch after an OCR scan, grid-snap drag). Multi-Commodity Finder has also never been recorded as human-tested. These are unverified follow-ups, not new bugs.

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
