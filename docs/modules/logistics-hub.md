# Module: Logistics Hub

Status: built and working against real captured Star Citizen contract text
(4 different contracts, verified live against the UEX API — see
DECISIONS.md for the full design/bug-fix history). Not yet human-verified
running inside the actual app (SELECT REGION + SCAN CONTRACT on a live
mission panel) — see PROGRESS.md Next.

## Scope

OCR-driven hauling logistics helper: capture a screen region over an
in-game mission contract panel, extract pickup(s)/drop-off(s)/reward via
OCR, resolve every location against real UEX data, and plan a visiting
order across every accepted contract.

- Input: a user-drawn screen region (SELECT REGION) over one contract's
  detail panel per scan; a CURRENT LOCATION picker for where the route
  should start from
- Output: a running list of contracts (pickups → drop-offs, commodities,
  reward) and a suggested visiting order across all of them
- On-demand scan only by default (SCAN CONTRACT button) — an opt-in
  AUTO RESCAN toggle exists but is off by default, per the original design
  goal of not continuously burning CPU/memory watching a region

## OCR engine

`easyocr` (Apache-2.0, pip-installable, no separate binary). Considered
`pytesseract` first (Aider's initial pick, needs a separate Tesseract
install) and native Windows OCR via `winsdk` (no PyTorch download at
all) — `winsdk` has no prebuilt wheel for this machine's Python 3.14 and
building from source needs Visual Studio's C++ tools, which aren't
installed, so reverted to `easyocr`. Heavy dependency (~500MB, pulls in
PyTorch/torchvision) — see DECISIONS.md, distribution is now all-inclusive
so this is a real part of the app's dependency set, not opt-in.

## How a contract gets parsed (see DECISIONS.md for the full bug trail)

1. `_candidate_phrases()` pulls every plausible location-name phrase out
   of the raw OCR text — capitalized 2-4-word runs, plus a separate pass
   for single hyphenated station codes ("HDMS-Edmond") the word-based
   pattern can't see. Each candidate gets a role hint (pickup/dropoff/
   neutral) from nearby keywords ("Collect X from Y", "Deliver...to Y")
   or a "DROP OFF LOCATIONS"/"PICK UP LOCATIONS" section header.
2. Every candidate is checked against real UEX location data
   (`terminals`, `space_stations`, `outposts`, `cities`, all systems) —
   only phrases that resolve to a real place survive. This is more
   robust than trying to regex-parse the narrative text correctly, since
   OCR corrupts any single mention but real contracts repeat each place
   name several times.
3. Resolved pickups/drop-offs (a contract can have several of *either*)
   get their commodity extracted the same way and attached.
4. Route planning is nearest-neighbour from the CURRENT LOCATION pick,
   with a hard constraint: a drop-off is ineligible until every pickup on
   its own contract has been visited.

## UEX endpoints used (verified live, 2026-09-04)

- `star_systems`, then `terminals`/`space_stations`/`outposts`/`cities`
  per available system — built into one name → location-record index.
  **Important:** these four endpoints have independent id sequences (a
  `terminals` id and a `space_stations` id with the same number are
  usually two unrelated real places) — every row is tagged with its
  source endpoint at index-build time, and all dedup/lookup keys on
  `(endpoint, id)`, never a bare id.
- `terminals_distances` (`id_terminal_origin`/`id_terminal_destination`)
  and `orbits_distances` (`id_star_system_origin`/`destination`, via each
  location's `id_orbit`) — verified live to return real point-to-point
  and orbit-to-orbit distances, including cross-system. **Not yet wired
  in** — route cost is currently a coarse same-terminal/same-body/same-
  system/different-system tier with made-up weights. This is the next
  concrete improvement (see PROGRESS.md Next / DECISIONS.md's Location
  service plan).

## Card contents

- Region status label + SELECT REGION button (drag-draw a capture
  rectangle on any monitor)
- CURRENT LOCATION picker — editable combo + `QCompleter` (`MatchContains`,
  case-insensitive) over the full resolved location index, labeled with
  both name and short code (`"Shallow Frontier Station (MIC-L1)"`) so
  searching by either works
- SCAN CONTRACT button (flips to "SCANNING…" and disables itself while
  OCR/API work runs, since it's fully synchronous on the GUI thread — no
  progress signal without a threading redesign) + CLEAR button
- AUTO RESCAN checkbox (off by default)
- Scrollable contract list (pickups → drop-offs, commodities, reward) +
  suggested visiting order

## Settings (modules.logistics_hub in config.json)

- `region`: `{x, y, w, h}` of the last selected capture rectangle
- `contracts`: accumulated list of parsed contracts, each
  `{id, pickups: [{raw, terminal, commodities}], dropoffs: [...], reward,
  scanned_at}`
- `current_location_name` / `current_location`: the picked starting point
  (display label + full resolved terminal record)
- `auto_rescan`: bool, default false

## Done criteria

- Card renders inside the host's card container, respects drag/collapse/
  close/resize
- Region selection + OCR capture works, degrades gracefully (clear error
  message) if `easyocr`/dependencies aren't installed
- Contracts persist across scans (append, not overwrite) and across app
  restarts
- Route planner never suggests a drop-off before its own contract's
  pickup(s)
- **Not yet done:** human-verified inside the real running app (all
  verification so far is direct backend calls against live OCR text +
  the live UEX API); real-distance route cost (still the coarse tier
  heuristic)
