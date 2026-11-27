# Progress

One-page status. Session notes are in `docs/HISTORY.md`. Older
`docs/DECISIONS.md` entries that say "see PROGRESS.md" mean that archive.

## Version

- Latest tag: **v0.3.1** (`b93ee83`, 2026-10-03), the PR #12 code review: exit/Relaunch, persistence and resilience fixes, hover-to-unlock click-through pill, mobiThrottle hotkeys unset by default. Owner-tested in a `dist-test` build and in-game. The release zip was published by GitHub Actions.
- **v0.3.0** (`a08512f`, 2026-09-30): native taskbar minimize/maximize.
- **v0.2.0** includes pill click-through and crosshair `WS_EX_TRANSPARENT` hardening (`6a494aa`).
- **Next: v0.4.0** (owner decision 2026-11-27): mobiGuide, onedir packaging and the mobiThrottle removal ship together. Don't tag `master` before `claude/leveling-guide` merges: `master`'s spec and `release.yml` still build the old single-file exe. v0.3.1's release notes on GitHub are stale for the same reason.

## Shipped

v0.3.1 shipped eight modules as a single-file exe: Commodity Prices, Trade Route Optimizer, Logistics Hub, Refinery Finder, Multi-Commodity Finder, Crosshair, mobiNotes, mobiThrottle. `master` has since dropped mobiThrottle (PR #17, now [h2mCoreAi/mobiThrottle](https://github.com/h2mCoreAi/mobiThrottle)), leaving seven. `claude/leveling-guide` adds mobiGuide (`modules/leveling_guide/`) and still carries the old mobiThrottle folder until it rebases.

Location service phases 1–5 are done. Logistics Hub writes `Config.set_shared_location()`. Commodity Prices and Trade Route Optimizer default their system filters from `shared_location()` when the user has not set one.

Logistics Hub may order stops with greedy nearest-neighbor plus 2-opt on real UEX distances. That is the one exception to the no-custom-pathfinding rule in `AGENTS.md`.

**Packaging (on `claude/leveling-guide`, not yet on `master`):** onedir only (`dist/mobiOverlay/` = exe + `_internal/`, ~333 MB with CPU-only torch). Release zip ships that folder; users extract once. Onefile / `MOBI_ONEDIR` opt-in removed (see `docs/DECISIONS.md`, 2026-10-18).

## Open

- Next module candidate: Item Price Lookup / Ship Outfitting (Tier 1.4 in `docs/BACKLOG.md`).
- **All unmerged work is on `claude/leveling-guide`.** It contains the optimization pass, the startup/onedir work, the reliability fixes and the TheRealKestryl rebrand (from the `cursor/...` and `rebrand-therealkestryl` branches), the taskbar/perf/multi-agent work (the old `claude/taskbar-perf-multiagent`, folded in; that branch is not on GitHub), and mobiGuide. It branches from `06eb2c7`, before PR #17.
- **Merge plan (owner-approved 2026-11-27), in order:**
  1. Rebase `claude/leveling-guide` onto `master`. Drop `modules/mobi_throttle/`, `docs/modules/mobi-throttle.md`, `tests/test_mobi_throttle_reconnect.py`, mobiThrottle's `pause_when_hidden=False` mention and the stale mobiThrottle comments in `host/module_base.py` and `host/refresh.py`. Take `master`'s side of the doc conflicts (AGENTS, README, ARCHITECTURE, DECISIONS, PROGRESS), then re-apply what's unique to the branch, including the 2026-11-27 agent-onboarding doc updates (vision, data charter, rule 4 scope, planned changes).
  2. `python tests/run_all.py` passes.
  3. Owner `dist-test` of a fresh onedir extract: minimize to taskbar, then restore with tray Show, the hotkey and the taskbar button; stow/deploy; opacity sliders; Settings > Relaunch; Logistics Hub SCAN and route popout; mobiGuide NOW view.
  4. One PR to `master`, merged only on the owner's explicit OK. Close PRs #13, #14 and #16 as superseded.
  5. Tag v0.4.0 on `master`; Actions publishes the zip.
- **Planned code changes (owner-approved 2026-11-27, not built yet):**
  - Logistics Hub Game.log check becomes a true opt-in: unset path means off, no default-path fallback (`gamelog_verify.default_game_log_path()`, `logistics_hub/module.py`). Update the Hauler Profile UI and README Privacy to match.
  - mobiGuide NOW view: load ship prices in NOW, fall back to `"now"` not `"guide"`, add rep SET to NOW, stop hidden filters from changing BEST CONTRACT TO REPEAT. Details in `docs/modules/leveling-guide.md`, Planned changes.
  - mobiGuide data: split reputation and earnings for live vs PTU; add a "new character / wipe" action that archives, then resets; label "best paying" as per run.
- **Deferred:** an in-game mobiGuide strip on the primary monitor (needs its own owner decision).
- Human checks that were never closed are listed in `docs/HISTORY.md` (crosshair over the game, hotkey focus, relaunch after an OCR scan, grid-snap drag). Multi-Commodity Finder has also never been recorded as human-tested. These are unverified follow-ups, not new bugs.

## In flight

One row per active branch. Add yours in your first commit and remove it when the PR merges (see `AGENTS.md`, Working with multiple agents).

| Agent | Branch | Area / files |
|-------|--------|--------------|
| Claude | `claude/leveling-guide` (all unmerged work; includes the old `claude/taskbar-perf-multiagent`) | `host/` taskbar/refresh/config work, `modules/logistics_hub/results_view.py`, new module `modules/leveling_guide/` (packs, contracts, goals), `scripts/build_contract_catalog.py`, `scripts/check_pack.py`, `docs/modules/leveling-guide.md`, `docs/leveling-guide/`, `tests/test_leveling_guide.py` |

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
