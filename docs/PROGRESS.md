# Progress

One-page status. Session notes are in `docs/HISTORY.md`. Older
`docs/DECISIONS.md` entries that say "see PROGRESS.md" mean that archive.

## Version

- Latest tag: **v0.3.1** (`b93ee83`, 2026-10-03), the PR #12 code review: exit/Relaunch, persistence and resilience fixes, hover-to-unlock click-through pill, mobiThrottle hotkeys unset by default. Owner-tested in a `dist-test` build and in-game. The release zip was published by GitHub Actions.
- **v0.3.0** (`a08512f`, 2026-09-30): native taskbar minimize/maximize.
- **v0.2.0** includes pill click-through and crosshair `WS_EX_TRANSPARENT` hardening (`6a494aa`).

## Shipped

Eight modules in one onedir folder (~333 MB, CPU-only torch): Commodity Prices, Trade Route Optimizer, Logistics Hub, Refinery Finder, Multi-Commodity Finder, Crosshair, mobiNotes, mobiThrottle.

Location service phases 1–5 are done. Logistics Hub writes `Config.set_shared_location()`. Commodity Prices and Trade Route Optimizer default their system filters from `shared_location()` when the user has not set one.

Logistics Hub may order stops with greedy nearest-neighbor plus 2-opt on real UEX distances. That is the one exception to the no-custom-pathfinding rule in `AGENTS.md`.

**Packaging:** onedir only (`dist/mobiOverlay/` = exe + `_internal/`). Release zip ships that folder; users extract once. Onefile / `MOBI_ONEDIR` opt-in removed (see `docs/DECISIONS.md`, 2026-10-18).

## Open

- Next module candidate: Item Price Lookup / Ship Outfitting (Tier 1.4 in `docs/BACKLOG.md`).
- **Unmerged work is consolidated on `claude/taskbar-perf-multiagent`.** It stacks the optimization pass, the startup/onedir work, the reliability fixes and the TheRealKestryl rebrand (all previously on `cursor/...` and `rebrand-therealkestryl` branches, never merged) with the taskbar restore fixes, off-GUI-thread module refreshes, refresh pause while hidden, debounced config saves, the Logistics Hub `results_view.py` split, and the multi-agent docs. Needs an owner `dist-test` of a fresh onedir extract: minimize to taskbar, then restore with tray Show, the hotkey and the taskbar button; stow/deploy; opacity sliders; Settings > Relaunch; Logistics Hub SCAN and route popout; mobiThrottle connect/reconnect.
- `remove-mobithrottle` (mobiThrottle split into its own repo) is a separate, unmerged product decision. It isn't part of the branch above.
- Human checks that were never closed are listed in `docs/HISTORY.md` (crosshair over the game, hotkey focus, relaunch after an OCR scan, grid-snap drag). Multi-Commodity Finder has also never been recorded as human-tested. These are unverified follow-ups, not new bugs.

## In flight

One row per active branch. Add yours in your first commit and remove it when the PR merges (see `AGENTS.md`, Working with multiple agents).

| Agent | Branch | Area / files |
|-------|--------|--------------|
| Claude | `claude/taskbar-perf-multiagent` | `host/main_window.py`, `host/main.py`, `host/refresh.py`, `host/config.py`, `host/module_base.py`, `modules/logistics_hub/results_view.py`, agent docs |
| Claude | `claude/leveling-guide` (stacked on the branch above) | new module `modules/leveling_guide/` (packs, contracts, goals), `scripts/build_contract_catalog.py`, `scripts/check_pack.py`, `docs/modules/leveling-guide.md`, `docs/leveling-guide/`, `tests/test_leveling_guide.py` |

## Working rules that are easy to miss

- Work on an `<agent>/<topic>` PR branch and claim it under "In flight" below. Never push to `master` without the owner's explicit OK in the current session. Multi-agent rules are in `AGENTS.md`.
- Run `python tests/run_all.py` before pushing.
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
