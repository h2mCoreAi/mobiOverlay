# Leveling Guide: research prompts

Prompts for collecting Star Citizen objectives for the `leveling_guide` module
(design: `docs/modules/leveling-guide.md`).

**The prompts you paste are below:**

| Prompt | Paste into |
|------|-----------|
| 1: Gemini Tasks | Gemini, in Task mode |
| 2: Muse fact-check | meta.ai (Muse) |
| 3: backup | Gemini or Muse chat, only if prompt 1 can't write to Sheets |

## Who does what

| AI | Job | Why |
|----|-----|-----|
| **Gemini Tasks** (Task mode in the Gemini app) | Researches the objectives and writes them into a Google Sheet | Runs long jobs in the background, browses the web, can create and edit Google Sheets. Claude reads that Sheet directly, so nothing is copy-pasted |
| **Muse** (meta.ai) | Fact-checks each track | Very large context (whole tracks at once) and its own web research. Its research leans on Facebook, Instagram and Threads posts, so it checks rather than collects, and is told which sources count |
| **Claude** | Merges, orders and builds | Reads the Sheet and Muse's verdicts, fixes or flags disagreements, orders the guide, checks every location against UEX |

## Steps

1. **Pilot first.** In Gemini, switch to **Task** mode, paste **Prompt 1**,
   and set `TRACKS TO DO IN THIS RUN` to `FND` only. When it finishes, tell
   Claude. Claude reads the Sheet and adjusts the prompt if anything came out
   wrong. (Writing to Sheets from Tasks is new and still rolling out; the pilot
   proves it works for your account before the long runs.)
2. **Full runs.** Run Prompt 1 again in the same Sheet, a few tracks per run:
   - Run 2: `HAUL, TRADE, MINE, SALV`
   - Run 3: `SHIP, BNTY, FPS`
   - Run 4: `REP, OUT, EXPL, NEW`
   If a run stops early, paste the same prompt again: it resumes from the
   `Tracks` tab.
3. **Fact-check.** For each track, copy its rows from the `Objectives` and
   `Steps` tabs and paste them into Muse with **Prompt 2**. Save Muse's reply as
   `docs/leveling-guide/research/muse-<TRACK>-check.json` (or paste it to
   Claude).
4. Claude merges everything and runs the gap check if a track looks
   thin.

If Gemini Tasks can't write to Sheets for you, use **Prompt 3** in a normal
Gemini or Muse chat instead. It produces the same data as JSON in the chat.

## Tracks

| Code | Track | Covers |
|------|-------|--------|
| `FND` | Foundations | First hours: hab, ship spawning, quantum travel, landing, contracts app, medical and respawn, insurance and claims, refuel and repair, selling, cargo grid, beacons, party basics |
| `HAUL` | Hauling | Cargo and delivery contracts, and the hauling company reputation ladders |
| `TRADE` | Trading | Commodity buy-low/sell-high loops, from starter ships to large cargo ships, box vs bulk |
| `MINE` | Mining | Hand, ground-vehicle and ship mining, refining, selling, mining reputation if any |
| `SALV` | Salvage | Hull scraping, components, salvage contracts and reputation |
| `SHIP` | Ships & gear | What to buy and when with aUEC, upgrades, components, armor and weapons, rentals |
| `BNTY` | Bounty & security | Ship combat contracts, bounty and security reputation ladders |
| `FPS` | Ground combat | FPS missions, bunkers, derelicts, contested zones, loot runs |
| `REP` | Other factions | Every other faction or career reputation ladder not covered above |
| `OUT` | Outlaw | Piracy, smuggling, illegal contracts, outlaw factions, handling a crimestat |
| `EXPL` | Exploration & events | Exploration, recurring dynamic events, collector and lore chains, achievements |
| `NEW` | Newest systems | Any live system that fits no other track (for example crafting or base building) |

---

## Prompt 1: Gemini Tasks (research into a Google Sheet)

Paste into Gemini in **Task** mode. Change only the `TRACKS TO DO IN THIS RUN`
line.

````text
TRACKS TO DO IN THIS RUN: FND

GOAL
I am building a "leveling guide" for the PC game Star Citizen, in the style of a
World of Warcraft leveling guide: one long, ordered list of small, concrete
objectives, each with step-by-step instructions, that a player checks off one
at a time in an on-screen overlay. Star Citizen has no levels, so the
objectives are things like: earn a reputation rank, reach a money milestone,
learn a core skill, buy a ship, finish a contract chain. Another AI will read
your spreadsheet and merge it into the guide, so the exact layout below
matters more than prose.

YOUR TASK
1. Find or create a Google Sheet in my Drive named exactly:
   mobiOverlay Leveling Guide - Research
   If it already exists, keep everything already in it and add to it. Never
   delete or rewrite rows from earlier runs.
2. Make sure it has these five tabs, with these header rows (row 1), in this
   column order:

   Tab "Patch":
   live_patch | release_date | patch_source_url | playable_systems | removed_or_changed_recently | checked_on

   Tab "Factions":
   faction | ranks_in_order | how_rep_is_earned | track | source_url

   Tab "Tracks":
   track | status | objectives_written | notes

   Tab "Objectives":
   id | track | title | kind | summary | requires_objectives | requires_reputation | requires_ships | requires_gear | auec_min | system | start_location | how_to_start | goal_target | goal_unit | rep_faction | rep_from | rep_to | minutes_min | minutes_max | auec_per_run_min | auec_per_run_max | runs_min | runs_max | pvp_risk | crimestat | ship_loss_risk | risk_notes | group | legal | availability | unlocks | patch_verified | confidence | sources | uncertain

   Tab "Steps":
   objective_id | step | do | where | done_when | tip

3. If the "Patch" tab is empty, fill it first: search for the current LIVE
   patch (not PTU or Evocati), its release date and source, the playable star
   systems, and anything removed or heavily changed in the last two patches
   that would make older guides wrong. Fill the "Factions" tab with every
   faction that has a reputation ladder on live, its exact rank names in order,
   and how reputation is earned.
4. For each track listed at the top of this message, in order:
   a. Set its "Tracks" row to status "in progress".
   b. Research it on the web and write its objectives (rules below), one row
      per objective in "Objectives" and one row per step in "Steps".
   c. Set its "Tracks" row to "done" with the number of objectives written.
   d. If you have to stop before finishing, leave the row "in progress" with a
      note saying where you stopped. If I paste this message again, carry on
      from there.
5. When finished, reply with: the Sheet's link, the live patch you found, and
   for each track the number of objectives written plus anything you could
   not verify.

TRACKS
FND  Foundations: first hours: hab, ship spawning, quantum travel, landing,
     contracts app, medical and respawn, insurance and claims, refuel and
     repair, selling, cargo grid, beacons, party basics
HAUL Hauling: cargo and delivery contracts, and the hauling company reputation ladders
TRADE Trading: commodity buy-low/sell-high loops, from starter ships to large
     cargo ships, box vs bulk
MINE Mining: hand, ground-vehicle and ship mining, refining, selling, mining reputation if any
SALV Salvage: hull scraping, components, salvage contracts and reputation
SHIP Ships & gear: what to buy and when with in-game money (aUEC), upgrades,
     components, armor and weapons, rentals
BNTY Bounty & security: ship combat contracts, bounty and security reputation ladders
FPS  Ground combat: FPS missions, bunkers, derelicts, contested zones, loot runs
REP  Other factions: every other faction or career reputation ladder not covered above
OUT  Outlaw: piracy, smuggling, illegal contracts, outlaw factions, handling a crimestat
EXPL Exploration & events: exploration, recurring dynamic events, collector
     and lore chains, achievements
NEW  Newest systems: any live gameplay system that fits none of the tracks
     above (for example crafting or base building), if one exists

RESEARCH RULES
- Search the web for everything. Do not rely on memory: Star Citizen changes
  every patch.
- Only include what exists on the LIVE servers today. If something may have
  been removed or changed, leave it out, or include it with confidence "low"
  and say why in "uncertain".
- Never guess. Leave a cell empty if you cannot verify it. Give money and time
  as min/max ranges, never invented exact numbers.
- Every objective needs at least one source. Count as sources: official RSI
  patch notes and Spectrum posts, the starcitizen.tools wiki, UEX Corp, and
  written guides or videos dated within the last 6 months. A forum or social
  media post is not enough on its own.
- Write every location, faction, ship, item, mission and rank name exactly as
  it appears in the game.

WHAT A GOOD OBJECTIVE LOOKS LIKE
- Small and checkable: finished in one session or a few, with a clear moment
  when it is done.
- Grinds are split into milestones: one objective per reputation rank or per
  money target, never one giant "grind this to max".
- Written for a player who has never done this activity: 3 to 10 steps, each
  one physical action in imperative form ("Open mobiGlas > Contracts > ...",
  "Quantum travel to ...", "Sell the ore at ..."). No assumed knowledge.
- Every step says where it happens ("where") and how the player can SEE in the
  game that it is done ("done_when": a notification, a rank shown in the
  contracts app, an item in the inventory, a balance change).
- Cover the whole track, from the first time a new player tries it to the
  end-game version. Number objectives in the order a player would do them.
- Include solo and group content, lawful and unlawful where relevant, and all
  playable systems; the columns below flag them so the player can filter.
- Typically 15 to 40 objectives per track. Completeness and accuracy matter
  more than hitting a number.

CELL RULES
- id: track code + 3 digits in order: FND-001, FND-002, ... Never reuse an id.
- kind: one_time | milestone | grind
- Lists inside one cell: separate items with " ; ".
- requires_objectives: ids of earlier objectives, or short plain text.
- requires_reputation: "Faction: Rank" items.
- requires_ships: the minimum ship role, then named example ships.
- goal_target / goal_unit: e.g. 10 / contracts. For a one-time objective: 1 / runs.
  Units: contracts | SCU | aUEC | runs | rank | items
- rep_faction / rep_from / rep_to: empty if no reputation changes.
- pvp_risk and ship_loss_risk: low | medium | high
- crimestat: TRUE or FALSE
- group: solo | solo_ok | group_recommended | group_required
- legal: lawful | unlawful | either
- availability: permanent | recurring_event | limited_event | unknown
- patch_verified: the live patch your sources confirm, or "unknown"
- confidence: high | medium | low
- sources: "url (YYYY-MM-DD)" items separated by " ; "
- Steps tab: step numbers start at 1 for each objective_id.

SAFETY
This is a research-only job. Do not buy anything, sign in anywhere, send
messages, or change anything except this one spreadsheet.
````

---

## Prompt 2: Muse (fact-check one track)

Open a new meta.ai chat, choose the strongest reasoning mode it offers
(Thinking or above), paste this prompt, then paste one track's rows from the
Sheet's `Objectives` and `Steps` tabs (header rows included) where indicated.

````text
You are fact-checking part of a "leveling guide" for the PC game Star Citizen,
written in the style of a World of Warcraft leveling guide: ordered objectives
with step-by-step instructions a player checks off one at a time. Another AI
researched these rows. I need to know which are correct on the CURRENT LIVE
patch.

Search the web for every check; do not rely on memory, because Star Citizen
changes every patch. Start your reply with one line: "PATCH: <live patch
version> (<source url>)".

Sources that count: official RSI patch notes and Spectrum posts, the
starcitizen.tools wiki, UEX Corp, and written guides or videos dated within the
last 6 months. A Facebook, Instagram, Threads, Reddit or other social post can
support a source but never counts on its own.

For each objective, check:
- Does it still exist on the live servers?
- Are location, faction, ship, item, mission and rank names spelled exactly as
  in the game?
- Are the steps complete and in the right order for a player who has never
  done this? Does each "done_when" describe something the player can actually
  see in the game?
- Are the requirements, money ranges and time ranges plausible?
- Are the listed sources real, relevant and recent?

Reply with ONE JSON array in ONE ```json code block, one entry per objective,
in the same order as the rows:

{
  "id": "the objective's id",
  "verdict": "correct | fix | outdated | wrong | cannot_verify",
  "fixes": [{"field": "column name, or steps[N].column", "was": "...", "should_be": "...", "why": "..."}],
  "missing_steps": ["anything a new player needs that the steps skip"],
  "sources": [{"title": "", "url": "", "date": "YYYY-MM-DD"}],
  "notes": "short, or null"
}

Use "cannot_verify" whenever you can't find a qualifying source; never guess.
If the array would be longer than you can write in one reply, stop after a
whole entry, write "NEXT: <id>", and continue when I type "continue".

After the code block, list in plain text any important objectives for this
track that are missing entirely: one line each, with a title and why it
matters.

ROWS TO CHECK:
<PASTE THE OBJECTIVES ROWS, THEN THE STEPS ROWS, HERE>
````

---

## Gap check (Claude runs this, not you)

````text
Below are the titles of every objective in a WoW-style Star Citizen leveling
guide, grouped by track. Search the web for the CURRENT live patch and tell me
what is missing: progression milestones, reputation ranks, money steps,
skills, or ship purchases a player would reasonably expect in a complete guide.

For each gap reply with one line: TRACK | proposed title | why it matters |
source url. Then list any objective below that you believe no longer exists on
live, with a source.

<PASTE THE TITLE LIST HERE>
````

---

## Prompt 3: backup (JSON in a Gemini or Muse chat, one track)

Use this in a normal Gemini or Muse chat if Prompt 1 can't write to Sheets.
Replace `{TRACK}` and `{COVERS}` with a row from the Tracks table. Type
`continue` whenever the reply ends with `NEXT:`. Save the replies as
`docs/leveling-guide/research/<ai>-<TRACK>.json`.

````text
You are helping me build a "leveling guide" for the PC game Star Citizen, in
the style of a World of Warcraft leveling guide: a long, ordered list of small,
concrete objectives, each with step-by-step instructions, that a player checks
off one at a time in an on-screen overlay. Star Citizen has no levels, so the
objectives are things like: earn a reputation rank, reach a money milestone,
learn a core skill, buy a ship, finish a contract chain. Your output will be
machine-read and merged with other AIs' output, so follow the format exactly.

TRACK: {TRACK}
THIS TRACK COVERS: {COVERS}

RESEARCH RULES
1. Search the web for everything; do not rely on memory. Star Citizen changes
   every patch.
2. Only include what exists on the LIVE servers today (not PTU or Evocati). If
   something may have been removed or changed, leave it out, or set
   "confidence": "low" and explain in "uncertain".
3. Never guess. Use null for anything you cannot verify. Give money and time as
   [min, max] ranges, never invented exact numbers.
4. Every objective needs at least one source: official RSI patch notes and
   Spectrum posts, the starcitizen.tools wiki, UEX Corp, or written guides or
   videos dated within the last 6 months. A forum or social media post is not
   enough on its own.
5. Write every location, faction, ship, item, mission and rank name exactly as
   it appears in the game.

WHAT A GOOD OBJECTIVE LOOKS LIKE
- Small and checkable: finished in one session or a few, with a clear moment
  when it is done.
- Grinds are split into milestones: one objective per reputation rank or per
  money target, never one giant "grind this to max".
- Written for a player who has never done this activity: 3 to 10 steps, each
  one physical action in imperative form. No assumed knowledge.
- Every step says where it happens and how the player can SEE in the game that
  it is done (a notification, a rank in the contracts app, an item in the
  inventory, a balance change).
- Cover the whole track from first try to end game, in the order a player
  would do it. Include solo and group, lawful and unlawful where relevant, and
  all playable systems; the fields below flag them.

OUTPUT FORMAT
- The FIRST reply starts with one line: "PATCH: <live patch> (<source url>)".
- Then ONE JSON array in ONE ```json code block, at most 10 objectives per
  reply. After the block write "NEXT: <what comes next>" or "DONE". When I type
  "continue", carry on with no repeats.
- Each objective has exactly these fields:

{
  "id": "{TRACK}-001, {TRACK}-002, ... in order",
  "title": "short imperative, at most 60 characters",
  "kind": "one_time | milestone | grind",
  "summary": "1-2 sentences: what this is and why it matters",
  "requires": {
    "objectives": ["earlier ids, or plain text"],
    "reputation": [{"faction": "exact name", "rank": "exact rank"}],
    "ships": ["minimum ship role, then named examples"],
    "gear": ["items needed"],
    "auec_min": null,
    "system": null
  },
  "start": {"system": "", "location": "exact in-game name or null", "how_to_start": "app, tab, NPC or kiosk"},
  "steps": [{"do": "one action", "where": "exact location or null", "done_when": "what the player sees", "tip": null}],
  "goal": {"target": 1, "unit": "contracts | SCU | aUEC | runs | rank | items"},
  "rep_effect": null,
  "estimates": {"minutes_per_run": [0, 0], "auec_per_run": [0, 0], "runs_to_finish": [0, 0]},
  "risk": {"pvp": "low | medium | high", "crimestat": false, "ship_loss": "low | medium | high", "notes": null},
  "group": "solo | solo_ok | group_recommended | group_required",
  "legal": "lawful | unlawful | either",
  "availability": "permanent | recurring_event | limited_event | unknown",
  "unlocks": ["what finishing this opens up"],
  "patch_verified": "live patch your sources confirm, or unknown",
  "confidence": "high | medium | low",
  "sources": [{"title": "", "url": "", "date": "YYYY-MM-DD"}],
  "uncertain": null
}

"rep_effect", when reputation changes, is
{"faction": "exact name", "from_rank": "rank", "to_rank": "rank"}.
Begin with the first 10 objectives for {TRACK}.
````

---

## Research notes (2026-11-27)

What the prompts are built around, and what is still unconfirmed:

- **Gemini Tasks:** Task mode in the Gemini app, free since 2026-11-17 in the
  US, Japan, South Korea, Canada, Australia and India. It runs on Gemini 4
  Hydrogen (cheaper and a little less capable than Carbon), in an isolated
  virtual machine per account. It works in the background and asks before
  sensitive steps. Google says Gemini can now "create and edit Docs or Sheets",
  rolling out in the US first; whether that works inside Task mode for this
  account is what the pilot run checks. No published run-time or daily limits.
  Sources: [TechCrunch](https://techcrunch.com/2026/11/17/google-expands-access-to-gemini-tasks-which-can-help-with-calls-purchases/),
  [SiliconANGLE](https://siliconangle.com/2026/11/18/google-upgrades-geminis-agentic-task-mode-with-new-model-e-commerce-features/),
  [Android Central](https://www.androidcentral.com/apps-software/ai/google-just-made-its-best-gemini-agent-free-heres-where-you-can-get-it).
- **Gemini Deep Research** still writes cited reports and exports one
  response at a time to Docs (Sheets only when the reply contains a table).
  Third-party sites report daily report quotas. It works as a fallback for
  Prompt 1, but not as the main collector.
  Source: [exploreaitogether.com](https://exploreaitogether.com/export-download-gemini-guide/).
- **Muse (meta.ai):** Meta says Muse Spark 1.1 powers meta.ai (Muse Spark 1.3
  came out on 2026-09-02; whether meta.ai has switched to it is unclear). It has
  a 1M-token context window, a Thinking mode, and a deep research feature that
  cites sources and, by Meta's own description, draws on posts from its own
  apps. It can create documents and slides; no confirmed Google Sheets or
  JSON export, so its output comes back as chat text.
  Sources: [Meta newsroom](https://about.fb.com/news/2026/07/meta-ai-muse-spark-doesnt-just-think-it-acts/),
  [Meta AI blog](https://ai.meta.com/blog/introducing-muse-spark-meta-model-api/),
  [Analytics Insight](https://www.analyticsinsight.net/artificial-intelligence/meta-ai-features-models-apps-use-cases-in-2026).
