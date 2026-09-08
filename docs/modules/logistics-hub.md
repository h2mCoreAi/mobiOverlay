# Module: Logistics Hub

Status: built, working, and human-verified live in the running app across
many rounds of real captured Star Citizen contracts and several real
accept-to-complete cycles. Full design/bug-fix history in DECISIONS.md.

## Scope

OCR-driven hauling logistics helper: capture a screen region over an
in-game mission contract panel, extract pickup(s)/drop-off(s)/reward via
OCR, resolve every location against real UEX data, plan a visiting order
across every accepted contract, grade each scan against your own
preferences, and (optionally) cross-check what OCR found against Star
Citizen's own `Game.log`.

- Input: a user-drawn screen region (SET SCAN AREA) over one contract's
  detail panel per scan; a CURRENT LOCATION picker for where the route
  should start from; a one-time Hauler Profile (ship, preferences,
  cargo capacity, grading scale, Game.log path, accept-reminder delay)
- Output: a running list of contracts (pickups → drop-offs, commodities,
  reward, a 0-100% grade), a suggested visiting order across all of them,
  and a running Freight Manifest
- On-demand scan only (SCAN CONTRACT button) — no auto-rescan, per the
  original design goal of not continuously burning CPU/memory watching a
  region (an opt-in auto-rescan toggle existed briefly but was removed
  2026-09-04, unused)
- Every scan pauses on a review popup (ACCEPT/REJECT) before joining the
  queue — added 2026-09-07, replacing straight-to-queue behavior

## OCR engine

`easyocr` (Apache-2.0, pip-installable, no separate binary). Considered
`pytesseract` first (Aider's initial pick, needs a separate Tesseract
install) and native Windows OCR via `winsdk` (no PyTorch download at
all) — `winsdk` has no prebuilt wheel past Python 3.12 (this machine runs
3.14) and building from source needs Visual Studio's C++ tools, which
aren't installed, so reverted to `easyocr`. Heavy dependency (~500MB,
pulls in PyTorch/torchvision) — distribution is all-inclusive (see
DECISIONS.md) so this is a real part of the app's dependency set, not
opt-in.

## How a contract gets parsed

Location resolution runs against the shared Core `LocationService`
(`host/locations.py`), not module-private logic — see that file's
docstring and DECISIONS.md, 2026-09-04, for the cross-endpoint id-
collision bug that made a shared, endpoint-safe service worth building.

1. `_candidate_phrases()` pulls every plausible location-name phrase out
   of the raw OCR text — capitalized 2-4-word runs, a same-line trailing
   digit/code suffix when present ("ArcCorp Mining Area 061"), and a
   separate pass for single hyphenated station codes ("HDMS-Edmond") the
   word-based pattern can't see. Each candidate gets a role hint
   (pickup/dropoff/neutral) with a **priority** (own-line keyword >
   backward-lookback keyword > section header > neutral) — a later,
   more-trustworthy mention of the same real place (even under different
   OCR-garbled wording) can override an earlier, less-trustworthy one.
   `_PHRASE_STOPWORDS` excludes known chrome/noise phrases up front —
   UI buttons, section headers, and (added 2026-09-08) the mission-giver
   company name "Covalex Shipping"/"Covalex Shippina", which was
   substring-matching a real UEX location ("Covalex Orison") and
   producing a phantom dropoff — see DECISIONS.md for the full writeup.
2. Every candidate is checked against `LocationService.resolve_all()` —
   only phrases that resolve to a real place survive. Ambiguous matches
   (a bare phrase matching several distinct real places) get two
   disambiguation attempts before being surfaced as unresolved: a
   candidate-specific suffix search across the raw text, then "was one
   of these options already confirmed elsewhere in this same contract."
   Genuinely unresolvable ambiguity shows as an amber warning row on the
   card and in the COPY ROUTE export, never a silent guess. A candidate
   with a real pickup/dropoff hint but zero exact/substring matches gets
   one more attempt via `LocationService.resolve_fuzzy()` (a stricter,
   opt-in-only fuzzy match, cutoff 0.85) before being dropped — resolves
   OCR names garbled just enough to miss substring matching ("Seraphim
   Staton"), but visibly flagged with the same amber-warning mechanism
   ("fuzzy-matched to X (NN% confidence) — please verify") rather than
   silently trusted. A location that genuinely isn't in UEX's own cached
   data at all (confirmed real: "HDPC-Cassillo", 2026-09-08) falls back
   to an honest unresolved raw-text entry — still carrying its own
   correctly-extracted commodities, never silently dropped.
3. Resolved pickups/drop-offs (a contract can have several of *either*)
   get their commodity extracted from "Collect X from Y"/"Deliver...of X
   to Y" lines, searched against every raw OCR spelling that resolved to
   that place (not just the winning one). When no commodity can be found
   at all, the entry shows an explicit "cargo unknown — check raw OCR
   text" label rather than a silent blank — a blank read as "confirmed
   nothing to carry," which is never actually true for a real contract.
   A pickup's quantity is the *sum* across every "Deliver...to..." line
   for that commodity, not just one of them.
4. Newly-scanned contracts are checked against every already-added one:
   same reward + at least one resolved location in common (not a full
   exact-set match, which real OCR noise varying scan-to-scan can break)
   flags a duplicate warning inline on the review popup (see below).
5. Route planning is greedy nearest-neighbour from the CURRENT LOCATION
   pick, followed by alternating precedence-aware 2-opt (segment reversal)
   and Or-opt (single-stop relocation) improvement passes, run until
   neither improves further. Hard constraint throughout: a drop-off is
   ineligible until every pickup on its own contract has been visited.

## UEX endpoints used (via the shared LocationService)

- `star_systems`, then `terminals`/`space_stations`/`outposts`/`cities`
  per available system — one name → location-record index, endpoint-
  tagged so dedup/lookup never collides two unrelated real places
  sharing a bare numeric id across endpoints.
- `terminals_distances` (terminal-to-terminal) and `orbits_distances`
  (any location, including cross-system) — the primary route cost
  (`LocationService.distance()`, queried lazily per pair, cached
  per-session). Falls back to a coarse same-terminal/body/system/
  different-system tier only when a real distance can't be determined.

## Scan → review → accept flow

Every SCAN CONTRACT capture builds a candidate contract, then pauses on
`_ReviewPopup` (a real `Qt.Window`, not `Qt.Popup` — the latter auto-
closes on any outside click/focus loss, wrong for a popup needing a
deliberate decision) showing pickups → dropoffs, reward, SCU, a duplicate
warning when relevant, the contract's grade (see below), and any
unrated ship/location compatibility prompts. Nothing joins the queue
until ACCEPT is clicked; REJECT discards it. On ACCEPT:

1. `_verify_against_gamelog()` runs (see Game.log verification below).
2. The contract is appended to the queue, the route replans, and the
   card re-renders.
3. If Game.log didn't confirm the contract immediately, a delayed
   recheck is scheduled (see Accept reminder below).

## Grading and the Hauler Profile

`_grade_contract()` scores every scan 0-100%, shown directly on the
review popup (no letter grades — switched from a 5-band scale
2026-09-07 per user preference). Inputs: reward/SCU efficiency (against
a user-editable **GRADING SCALE** — GREAT ≥ / GOOD ≥ / OK ≥ aUEC/SCU,
`self.settings["grading_thresholds"]`, defaults 500/200/80 but the
project's own real fixture data showed those miscalibrated low, so it's
tunable, not hardcoded), marginal route detour cost, and profile-driven
nudges (cross-system vs. Region preference, Pyro vs. Risk Tolerance).
Reads every setting fresh on each call — a saved profile/threshold
change applies to the very next scan, no restart.

Three things cap the score hard, regardless of how well everything else
scores (a cap never blocks ACCEPT — it only warns, visibly, amber):
- A known-BAD ship/location compatibility rating, or a commodity already
  queued in another contract (via the Freight Manifest logic) —
  `GRADE_CAP_ON_WARNING` (55). Both are things you *can* still physically
  complete, just annoying/risky.
- Combined peak cargo (existing queue + this candidate) exceeding your
  cargo capacity — `CAPACITY_OVERFLOW_CAP` (20), stricter than the above,
  since exceeding your hold means the run is physically impossible to
  complete as queued, not just annoying.

**Hauler Profile** (`PROFILE` button, `_HaulerProfilePopup`, set once and
edited whenever, `self.settings["hauler_profile"]`):
- **Ship** — free text (no reliable static ship-data source exists to
  validate against; doubles as the compatibility-DB key below)
- **Cargo Capacity** (SCU) — manual entry, not a UEX vehicle-data picker
  (a picker can't reflect a customized cargo-grid loadout); feeds both
  the card's summary-line overflow warning and grading's capacity cap
- **Goal / Risk Tolerance / Session Time / Region** — fixed dropdown
  choices, not free text, so grading has a closed set of values to branch
  on
- **Grading Scale** — the GREAT/GOOD/OK aUEC/SCU thresholds above
- **Game.log path** + **BROWSE** — see Game.log verification below
- **Accept Reminder (sec, 0=off)** — see Accept reminder below

**Ship/location compatibility** (`self.settings["ship_location_ratings"]`,
a plain `{"<ship>::<endpoint>:<id>": "good"|"bad"}` dict): starts empty
and only grows from your own GOOD/BAD answers, prompted inline on the
review popup for any pickup/dropoff terminal your current ship hasn't
been rated at yet — never re-asked once answered. No static/AI-generated
compatibility table is used; one was tried and found partly fabricated
against real sources.

## Game.log verification

OCR remains the only scan trigger and primary data source — Game.log
verification is a one-shot correction pass, not a replacement or a live
tracker. See `modules/logistics_hub/gamelog_verify.py` (pure functions,
no Qt/host dependency) and DECISIONS.md, 2026-09-08, for the full
investigation (sc-overlay project) and design writeup.

**Signals used**, both written by Star Citizen itself into `Game.log` the
instant a contract is accepted in-game:
- `Contract Accepted:  <title>` — for the common "<rank> | <DIRECT?>
  <size> Haul | <Origin> > <Destination>" title template, names both
  stops directly, plus the real `MissionId`.
- `New Objective: Deliver <have>/<need> <unit> of <commodity> to
  <destination>` — one per drop-off leg; exact tonnage/commodity/
  destination Game.log actually has, vs. what OCR had to guess from a
  screenshot.

**Matching**: `verify_contract()` scores every recent Game.log haul event
by normalized name-overlap against the contract's own pickup/dropoff
names (2 points each for origin/destination overlap, 1 for each
Deliver-line leg overlap). A match requires **both** origin and
destination overlap (`MIN_MATCH_SCORE = 4`) — a partial, single-sided
match is rejected outright, not accepted as weak-but-good-enough (fixed
2026-09-08 after real evidence of exactly that going wrong on repeat
same-station hauls). Every other contract already in the queue's own
claimed `MissionId` (`contract["gamelog_mission_id"]`, set on a
successful match) is excluded before scoring, so the same real accept
can never be attached to two different scanned contracts.

**Reading window**: `find_recent_haul_events()` reads only the tail of
`Game.log` (it can run into hundreds of MB), within
`window_seconds` (default 1800s/30min — widened from an initial 180s
guess after real evidence it was too tight) of "now." The *byte* budget
that tail read uses **scales with the window** (`_estimate_tail_bytes`,
~100KB/min, floored at 500KB, capped at 20MB) rather than a fixed size —
fixed at 500KB originally, this silently covered as little as ~34
minutes of this project's own real log on average, undercutting even the
already-widened time window. Both `window_seconds` and the game log path
are `config.json` values
(`modules.logistics_hub.game_log_verify_window_seconds` /
`game_log_path`), not hardcoded — the window in particular is expected to
need further real-world tuning.

**What it can and can't do**: Game.log wins whenever it reports something
(destination name, commodity, tonnage) — corrects a matched dropoff's
`commodities` directly. It does **not** resolve a location OCR couldn't
resolve at all (that needs `_build_contract`'s own candidate/fuzzy
matching), doesn't cover reward (never in Game.log until the unrelated,
not-yet-implemented `MissionEnded`/payout lines), and doesn't track live
delivery progress or completion — see sc-overlay for that much larger
surface, deliberately out of scope here.

**Diagnostics**: every verify attempt (matched or not) logs its full
result into the debug log's `gamelog_verify` field — `reason`,
`candidates_considered` (every event scored, highest first),
`events_in_window`, `nearest_haul_event_gap_seconds` (the closest
haul-related log line regardless of window — building a real
distribution over time for tuning `window_seconds` further),
`log_path`/`log_path_source`/`log_file_exists`. The card's status line
after ACCEPT also reports a miss, not just a hit, so a silent failure is
never invisible.

## Accept reminder

If Game.log didn't confirm a contract immediately at ACCEPT (common —
the log line can lag, or the in-game accept genuinely hasn't happened
yet), `_schedule_accept_reminder()` queues a one-shot delayed recheck
(`accept_reminder_seconds`, Hauler Profile, default 30s, 0 disables it
entirely). `_recheck_accept_reminder()` re-runs verification later; a
late match applies silently (exactly like the original check, just
delayed); still-unmatched shows a blinking, click-to-dismiss banner —
mirrored onto **both** the card and the Tracker popout if it's open
(added 2026-09-08 after a real gap: stowing the main window while the
Tracker is open made a card-only banner invisible), since either can
dismiss both. No game input is ever touched or automated — an auto-click
"ACCEPT OFFER" idea was explicitly considered and rejected on account-
risk grounds (synthetic input is flagged by Windows itself, which is
exactly what anti-cheat/monitoring checks for) before landing on this
safer reminder-only design. Confirmed working end-to-end live: a real
accept's immediate check missed by ~2.5s, the recheck caught it 11
seconds later.

Known issue (not yet fixed): the popout's reminder banner clips instead
of wrapping to window width in a narrow Tracker window.

## Card contents

Buttons are grouped into two tabs (`QTabWidget`, added 2026-09-08 to
reduce clutter as the button count grew) — same buttons/handlers as
always, just organized:

- **SCAN tab** (default): status label, SCAN CONTRACT, COPY ROUTE,
  REPROCESS (re-runs parsing against every saved contract's own stored
  raw OCR text and replans, no rescan needed), COMPLETE (logs every
  queued contract's reward/cargo/locations/grade-at-accept to
  `logistics_hub_completed.jsonl`, then clears the queue — distinct from
  CLEAR, which discards without a trace, for mistakes/duplicates), CLEAR
- **SETUP tab**: region status label, SET SCAN AREA, PROFILE, CLEAR LOG
  (wipes `logistics_hub_debug.jsonl` only, for easy re-testing — never
  touches the contract queue or the completed-contracts log)

Outside the tabs (always visible regardless of which tab is active):
- CURRENT LOCATION picker — editable combo + `QCompleter` over the full
  resolved location index
- The accept-reminder banner (hidden unless active)
- An at-a-glance summary line ("4 contracts · 268,750 aUEC · 143 SCU peak
  cargo · ⚠ EXCEEDS N SCU CAPACITY"), always visible without scrolling
- CONTRACTS section (pickups → drop-offs, commodities, reward, grade,
  per-contract remove, amber warning rows for ambiguous locations) in its
  own scroll area
- FREIGHT MANIFEST — running commodity totals across every active
  contract's pickup side; any commodity in 2+ contracts renders as an
  amber warning row (the game makes it very hard to tell two pickups of
  the same commodity apart once both are in the hold)
- ROUTE section (suggested visiting order), its own scroll area; each
  stop click-toggleable done/skipped; can pop out into its own
  always-on-top TRACKER window (no minimize — closing it returns the
  view to the card; the underlying route/done-state lives on the module
  either way)

## Debug log

Always-on, append-only JSON Lines file at `paths.app_root() /
"logistics_hub_debug.jsonl"` (next to `config.json`). One entry per scan
(`pending_review`: raw OCR text, candidate phrases, the built contract, a
per-candidate resolution trace, grade), a second entry per ACCEPT/REJECT
(`review_accepted`/`review_rejected`: grade, compatibility prompts/
answers, and — since 2026-09-08 — the full `gamelog_verify` diagnostic
dict), and a third, optional entry per delayed reminder recheck
(`accept_reminder_recheck`, same `gamelog_verify` shape). A REPROCESS run
logs one entry covering every reprocessed contract at once. No cap/
rotation; a **CLEAR LOG** button on the card wipes it on demand (added
2026-09-08, replacing "close the app and delete the file by hand").

`logistics_hub_completed.jsonl` (separate file, same directory) is a
distinct, durable record — only contracts explicitly marked COMPLETE
land here, never touched by CLEAR LOG.

## Settings (modules.logistics_hub in config.json)

- `region`: `{x, y, w, h}` of the last selected capture rectangle
- `contracts`: accumulated list of parsed contracts, each
  `{id, pickups: [{raw, terminal, commodities}], dropoffs: [...], reward,
  scanned_at, ambiguous, raw_text, grade_at_accept, grade_reason_at_accept,
  gamelog_mission_id}`
- `current_location_name` / `current_location`: the picked starting point
- `route_done`: list of `"{contract_id}:{role}:{index}"` keys for route
  stops toggled done/skipped
- `hauler_profile`: `{ship, goal, risk, time_budget, region_pref}`
- `cargo_capacity_scu`: manual hold size (SCU)
- `grading_thresholds`: `{great, good, ok}` aUEC/SCU
- `ship_location_ratings`: `{"<ship>::<endpoint>:<id>": "good"|"bad"}`
- `game_log_path`: path to `Game.log`, or unset (falls back to the
  common install path if present)
- `game_log_verify_window_seconds`: verify-window size, config-only, no
  UI (expected to need real tuning; see Game.log verification above)
- `accept_reminder_seconds`: delay before the reminder banner can fire,
  0 disables it
- `tracker_geometry` / `tracker_opacity_pct`: Tracker popout window state
- `refresh_interval_seconds`: forced to 0 (no auto-rescan timer)

## Done criteria

- Card renders inside the host's card container, respects drag/collapse/
  close/resize
- Region selection + OCR capture works, degrades gracefully (clear error
  message) if `easyocr`/dependencies aren't installed
- Contracts persist across scans (append, not overwrite) and across app
  restarts
- Route planner never suggests a drop-off before its own contract's
  pickup(s)
- Route cost uses real UEX distance data, not a guessed heuristic
- Human-verified inside the real running app across many rounds of real
  captured contracts, not just backend/API calls
- Human-verified across at least one full real accept-to-complete cycle
  (in-game accept, deliver, in-game complete, app-side complete) with
  Game.log verification live
