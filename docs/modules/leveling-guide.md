# Module: mobiGuide (Leveling Guide)

Status: built 2026-11-27 on `claude/leveling-guide`. Offscreen tests pass
(`tests/test_leveling_guide.py`, 151 checks); not yet run in the live
overlay or in game.

A World of Warcraft–style leveling guide for Star Citizen that works for any
player, at any level, on any patch:

- **Patch packs:** one folder per game version, layered on each other.
- **Categories** for every part of the game.
- **Step-by-step objectives** you check off by hand.
- **Reputation tracking** with the best repeatable contracts for each rank.
- **Goals:** reach a rank, save up aUEC, or buy a ship.
- **Import and export** of guides as data-only files.

## Content structure

```
modules/leveling_guide/packs/<pack-id>/
    pack.json          manifest
    chapters/*.json    one chapter per file
    contracts.json     contract catalog for that build (generated)
```

Bundled packs:

| Pack | Label | Builds on | Contents |
|------|-------|-----------|----------|
| `4.10.3-live` | 4.10.3 (live) | – | 14 chapters, 67 objectives, 1,266 contracts (SCMDB + star-citizen.wiki), 16 categories |
| `5.0-ptu` | 5.0 (PTU) | `4.10.3-live` | adds the Guilds chapter (7 objectives), the Guilds category, and 5.0's 899 contracts |

### pack.json

```json
{
  "schema": 1,
  "id": "5.0-ptu", "label": "5.0 (PTU)", "patch": "5.0.0", "channel": "ptu",
  "game_version": "5.0.0-ptu.13284307",
  "extends": "4.10.3-live",          // optional: inherit that pack's chapters
  "remove": ["objective-id"],        // optional: drop inherited objectives
  "reconfirmed": ["objective-id"],   // inherited objectives this patch's data backs (check_pack --write)
  "also_confirmed": [{"title": "...", "source": "https://..."}],  // contracts confirmed by a second source
  "categories": [...],               // replaces inherited categories
  "categories_add": [...]            // or adds to them
}
```

How inheritance works:
- A pack loads everything it `extends`, base first.
- A chapter file with an existing chapter id adds to that chapter.
- An objective with an existing id replaces the inherited one, in place.
- `remove` drops objectives by id.
- The newest **live** pack is the default; players switch packs in ⚙ → Game version.

### Categories

Categories are defined in the pack manifest, so a new patch can add or remap
them without code changes. Each has:
- `mission_types`: the game data's contract types it collects.
- `ships` (optional): true for contracts that spawn ship encounters (ship combat), false for those that don't (FPS).
- `illegal` (optional): collects every illegal contract.

Chapters list their `categories`; an objective can override them.

Bundled categories:
- Getting Started
- Hauling
- Deliveries & Courier
- Trading
- Mining
- Refining
- Salvage
- Bounty Hunting
- Ship Combat
- FPS Combat
- Investigation & Rescue
- Refuel, Repair & Maintenance
- Collecting & Wikelo
- Events
- Outlaw Work
- Ships & Gear
- Guilds (5.0)

### Objectives (chapter files)

Same schema as before, plus:
- `categories`: overrides the chapter's categories.
- `contracts`: the contract titles the objective names; the pack checker validates them.
- `verified`: the patch its facts were checked on; defaults to the chapter's `patch`.
- `reputation.ladder`: now the game's scope name (`Hauling`, `FactionReputation`, `BountyHunter_BountyHuntersGuild`, `MissionProviderReputation_Battaglia`, `Guild`, ...).

### contracts.json (generated)

Built by `scripts/build_contract_catalog.py` from more than one source, both
read from the game files. Each contract records which sources back it
(`sources`) and any disagreement (`conflicts`); the catalog keeps the
agreement statistics (`cross_check`).

- **SCMDB** (scmdb.net): live and PTU builds; the primary source for mission
  types, ship encounters and ladders.
- **star-citizen.wiki API**: live builds only. Joined on the game's internal
  contract name. It fills gates and reputation SCMDB lacks, adds the 628
  contracts SCMDB doesn't carry (their mission type is inferred from the name
  and marked `type_inferred`), and flags disagreements.
- **The previous patch's catalog** (`--previous`): for a PTU build the wiki
  can't check. Unchanged contracts inherit that catalog's cross-check, and a
  gate present before but missing now is carried over, marked as such.

Each contract records:
- giver and faction
- mission type, systems, legality, whether it repeats
- aUEC reward range
- reputation per faction ladder
- rank gate, and whether it spawns ships

The file also carries the game's ladders (rank thresholds) and every contract
title. Older rank-titled hauls carry their gate only in the title ("Junior
Rank - ..."); the builder infers it and marks it `from_title`.

## Adding a patch (5.0.1, 5.1, ...)

```bash
mkdir -p modules/leveling_guide/packs/5.1-live/chapters
# write pack.json: id, label, patch, channel, "extends": "5.0-ptu" (or the last live pack)
python scripts/build_contract_catalog.py --list
python scripts/build_contract_catalog.py <scmdb version> --label "5.1 (live)" --pack modules/leveling_guide/packs/5.1-live \
    --previous modules/leveling_guide/packs/5.0-ptu/contracts.json   # wiki cross-check is automatic for live builds
# add chapters for what's new; reuse an objective id to replace one; list ids under "remove" to drop them
python scripts/check_pack.py 5.1-live --write
python tests/run_all.py leveling
```

`check_pack.py` fails a pack when:
- its content doesn't load;
- a category it names doesn't exist;
- an objective names a contract that isn't in the pack's data;
- a rank-up's points don't match the game ladder.

It also lists which inherited objectives the new data re-confirms. The card
marks the rest **CHECKED ON <old patch>**. The test suite runs these checks
on every bundled pack.

## Importing and sharing guides

Guides are data only (JSON). Nothing imported is ever executed.

- **⚙ → Import guide** takes either of:
  - a **pack .zip**: a folder with `pack.json` and `chapters/`, optionally `contracts.json`. It's checked (one manifest, a safe id, no paths outside the pack, only `.json` taken, size limits, loads and extends correctly) and installed to `leveling_guide/packs/<id>/` next to `config.json`. It then appears in ⚙ → Game version.
  - a **chapter .json**: installed to `leveling_guide/`. It loads on top of every pack.
- **⚙ → Export my objectives as a chapter** writes your + ADD OBJECTIVE items as one chapter file anyone can import.
- **⚙ → Export pack** zips the active pack.
- **Without the menu:** drop folders and files into the same `leveling_guide/` folder (⚙ → Open my guide folder).

## Card

- **Header:** level and XP bar, and ⚙ (game version, filters, setup, help, import/export, reset).
- **First-run banner → setup:**
  1. game version and experience
  2. ranks already held, per faction ladder (seeds the reputation tracker and ticks off everything up to them)
  3. categories to focus on, outlaw, optional, compact
  4. how to use it
- **GUIDE / CONTRACTS** tabs and a **category** picker, shared by both views.
- **GUIDE:**
  - chapter picker filtered by category;
  - the current objective: badges, why, target, reward, cost, live UEX price for purchases, and a **CHECKED ON** badge when the facts aren't confirmed for the chosen version;
  - steps with **DONE WHEN**;
  - for rank-ups, a **reputation tracker**: current / target, **SET**, and the five best repeatable contracts for that ladder. Each row shows reputation, pay and "≈N to go"; locked ones show "needs <rank>".
  - Clicking a contract logs one finished run: its reputation goes onto every ladder it rewards, and its pay onto earnings.
- **CONTRACTS:**
  - goals: reach a rank, save up aUEC, or buy a ship (live UEX price), with progress and **SET**;
  - the best contracts for the goal, or with no goal, the category's best-paying repeatable contracts, unlocked first.
- **Contract filters:** a row above every contract list (reputation tracker and CONTRACTS):
  - **Type:** every mission type in the data, e.g. Hauling, Delivery, Bounty Hunter, Mercenary, Salvage.
  - **System:** Stanton, Pyro or Nyx.
  - **Unlocked:** hide contracts your known rank can't take yet.

  Choices are remembered. A row's tooltip names its sources, says where an inferred or carried-over gate came from, and shows any disagreement; such rows say "⚠ sources differ".
- **↶ UNDO LAST RUN** takes back the last logged contract.

Completion is always manual. No Game.log, no game input.

## Files

| File | Role |
|------|------|
| `module.py` | card, setup, goal dialog, import/export actions, UEX price refresh |
| `guide.py` | pack discovery and inheritance, chapter layering, validation, setup maths (pure) |
| `contracts.py` | catalog, categories, recommendations, unlock checks (pure) |
| `progress.py` | progress: done/skip/step/count, reputation, logged runs, goals, custom objectives (pure) |
| `packcheck.py` | pack validation against its data (pure; used by the script and the tests) |
| `packio.py` | safe import/export of packs and chapters (pure) |
| `scripts/build_contract_catalog.py` | SCMDB file → `contracts.json` |
| `scripts/check_pack.py` | validate packs, write `reconfirmed` |
| `app_root()/leveling_guide_progress.json` | progress, reputation, logged runs, goals |
| `app_root()/leveling_guide_custom.json` | your objectives |
| `app_root()/leveling_guide/` | drop-in chapters; `packs/` holds imported packs |
| `config.json` → `modules.leveling_guide` | `pack`, `view`, `category`, `goal`, `focus`, `f_type`, `f_system`, `f_unlocked`, `show_optional`, `show_unlawful`, `compact`, `setup_done`, `setup_dismissed` |

## Data and honesty rules

- Reputation and pay figures are the game's **base values** from the game files.
- "≈N to go" is the remaining target divided by the contract's reputation or pay.
- Recommendations are sorting and filtering only. Rank gates and illegality are shown as the data records them.
- Contracts with no "needs" really have no rank gate: both sources agree (for example Foxwell's "Red Level Contract: Clear PAFs..."). The gated Red Level ones carry their gate.
- Unknown ranks show "needs X?" until you set them.

See `docs/leveling-guide/verification.md` for every checked claim.
