# Module: mobiGuide (Leveling Guide)

Status: built 2026-11-27 on `claude/leveling-guide`. Offscreen tests pass;
not yet run in the live overlay or in game.

A World of Warcraft–style leveling guide for Star Citizen. The card shows one
objective at a time, step by step, and you check each step off by hand.
Chapters, a level and XP bar, grind counters, and objectives you add yourself.

## What's in v1

10 chapters and 57 objectives for live patch **4.10.3**:

| # | Chapter | Covers |
|---|---------|--------|
| 10 | First Steps in Stanton | pick a city, the three tutorial contracts, launch your ship, accept a contract |
| 20 | First Paychecks: Hauling | Covalex intro → Rookie → Junior → Member; Red Wind, Ling and courier intros |
| 30 | Bounty Hunters Guild | Training Permit → Junior → Beginner's Permit → Guild Member → Tracker License |
| 40 | Mercenary: Foxwell | intros → Jr. Contractor → Contractor → Sr. Contractor (Red Level) → Veteran |
| 50 | Salvage: Adagio | intro → Jr. Contractor → Contractor; buy a Vulture |
| 60 | Nyx: InterSec | intro → Vanduul-Tech Smugglers → Retake Boarded Vessel → Sr. → Veteran |
| 70 | Nyx: Recco Battaglia | Welcome to the System → Prestige 1/2/3 (Golem, Prospector and MOLE rewards); or buy a Golem |
| 80 | Advanced Careers | Covalex to Master; BHG to Guild Steward and the Master license |
| 90 | Outlaw Path | Headhunters, Vaughn and Dead Saints entry contracts (illegal, hidden by default) |
| 100 | Wikelo's Emporium | intro trade and a reputation trade |

Every fact was checked against the 4.10.3 game data before it went in. See
`docs/leveling-guide/verification.md` for what was confirmed, what was wrong
in the AI research, and how grind counts are computed.

## Card

- **Level / XP bar.** Each finished objective gives XP (task 100, rank-up
  150, purchase 200, grind 100 + 10 per counted run up to 50). Level *n*
  needs 200 + 50·(n−1) XP. This is for motivation only; nothing in the game
  is calculated.
- **Chapter picker** with done/total per chapter, and **NEXT ▸** to jump to
  the guide's next objective.
- **Current objective:** type badges (TASK / RANK UP / GRIND / BUY, OPTIONAL,
  ILLEGAL, YOURS), why it matters, target rank, reward, cost, and for purchases
  the **live UEX price** at the cheapest shop. A "Usually done after" hint
  appears when its prerequisites aren't done; it's a hint, not a lock.
- **Steps:** done steps dimmed, the current step outlined with its
  **DONE WHEN** check. `✓ STEP DONE` advances; on the last step it reads
  `✓ COMPLETE` and moves to the next objective. `◀ BACK`, `SKIP` (moves on
  without XP), and `↺ UNDO DONE` on a finished one.
- **Grind counter:** `−` / `+1` with "4 / 10 Junior Rank hauls".
- **Chapter checklist:** click to open an objective, right-click to mark it
  done or not done.
- **⚙ menu:** show optional objectives (on by default), show outlaw content
  (off by default), compact mode (current step only, for flying), reset this
  objective, delete one of yours, reload guide files, open my guide folder,
  reset all progress.
- **SOURCES** opens the pages each objective's facts come from.
- **+ ADD OBJECTIVE:** title, chapter, task or grind (with a target), why,
  and steps (one per line; `=>` adds the "done when" check).

Completion is always manual: no Game.log reading, no game input.

## Adding content

There are three ways, all using the same schema. Nothing in `host/` changes.

1. **Bundled chapters** (ship with the app): `modules/leveling_guide/guides/*.json`,
   one chapter per file. The spec bundles `modules/` whole, so new files
   ship automatically.
2. **Drop-in files** (no rebuild): any `*.json` in `leveling_guide/` next to
   `config.json` (⚙ → Open my guide folder). A file can add a new chapter,
   or reuse an existing `chapter.id` to append objectives to that chapter.
3. **In the card:** + ADD OBJECTIVE writes `leveling_guide_custom.json` next
   to `config.json`.

A bad file or objective is skipped and counted in the card's "guide content
problems" line (hover for details); the rest of the guide still loads.

### Schema (v1)

```json
{
  "schema": 1,
  "chapter": {"id": "hauling", "title": "First Paychecks: Hauling", "order": 20,
              "patch": "4.10.3", "summary": "..."},
  "objectives": [
    {
      "id": "haul-covalex-member",            // unique across the whole guide
      "title": "Reach Covalex Member (5,250 rep)",
      "kind": "grind",                        // task | rank | grind | purchase
      "goal": {"target": 10, "unit": "Junior Rank hauls"},   // grind only
      "reputation": {"faction": "Covalex", "ladder": "Hauling", "rank": "Member", "points": 5250},
      "ship": {"uex_name": "Vulture", "display": "Drake Vulture"},  // purchase only
      "optional": false,
      "tags": ["stanton", "solo", "lawful", "hauling"],   // "unlawful" = hidden by default
      "why": "...", "reward": "...", "cost": "...", "tips": "...",
      "requires": ["haul-covalex-junior"],    // ordering hint; cycles are broken on load
      "steps": [{"do": "...", "where": "...", "done_when": "..."}],
      "sources": ["https://..."]
    }
  ]
}
```

New content should follow the same rule as v1: only facts confirmed against
game data or official sources, with the source listed.

## Files

| File | Role |
|------|------|
| `modules/leveling_guide/module.py` | card, actions, UEX price refresh |
| `modules/leveling_guide/guide.py` | load, validate and order content; XP, level and price maths (pure, no Qt) |
| `modules/leveling_guide/progress.py` | progress store and custom objectives (pure) |
| `modules/leveling_guide/guides/*.json` | bundled chapters |
| `app_root()/leveling_guide_progress.json` | done, skipped, current step and counter per objective id |
| `app_root()/leveling_guide_custom.json` | your objectives |
| `app_root()/leveling_guide/*.json` | drop-in chapter files |
| `config.json` → `modules.leveling_guide` | `show_optional`, `show_unlawful`, `compact`, `refresh_interval_seconds` (600) |

Progress is keyed by objective id, so adding, removing or reordering content
keeps it. Both files use `atomic_write_text` and corrupt-file quarantine,
like mobiNotes.

## UEX use

One endpoint, `vehicles_purchases_prices_all`, fetched through
`refresh_job()` (off the GUI thread) only while a purchase objective is on
screen, and cached for 30 minutes. The card shows the cheapest listing as UEX
reports it. A UEX failure only changes the price line ("UEX unavailable, will
retry"); the card never goes into its error state for it.

## Tests

`tests/test_leveling_guide.py` (73 checks):

- **Bundled content:** loads with no errors, ids are unique, every objective
  has https sources and complete steps, and requirements resolve.
- **Pinned to verified data:** grind targets and rank thresholds match the
  verified game data.
- **Bad content is survivable:** broken JSON, a wrong schema, missing fields,
  duplicate ids, unknown requirements and requirement cycles are all skipped
  without breaking the load.
- **User content:** drop-in files and custom objectives merge in correctly.
- **Progress store:** round-trips, handles skip, and quarantines a corrupt file.
- **Maths:** level, prices and next-objective selection.
- **Offscreen card walk-through:** steps, back, skip, counter, filters, compact
  mode, live price, a UEX failure, and a custom objective.

## Not done / next

- Not yet seen in the real overlay or used in game.
- Two facts are left out until they can be confirmed in game: which Covalex
  rank first offers interstellar hauls, and the Wikelo rank gate on
  "Most Special Wolf".
- **5.0 content:** guild ranks, contract boards and Nyx I. Add once 5.0 is
  live and the data has been re-checked.
- **Re-verify on each patch.** The research tooling (the star-citizen.wiki
  mission API) makes this fast. Bump `patch` in each chapter after checking.
