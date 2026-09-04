# Module: Logistics Hub

Status: built, working, and human-verified live in the running app across
many rounds of real captured Star Citizen contracts (SELECT REGION + SCAN
CONTRACT on real mission panels, console + COPY ROUTE export reviewed
together each round). Full design/bug-fix history in DECISIONS.md.

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
PyTorch/torchvision) — distribution is all-inclusive (see DECISIONS.md)
so this is a real part of the app's dependency set, not opt-in.

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
   This mattered twice in practice: once for the text-keyed candidate
   list, and again for the separately-keyed resolved-terminal merge
   (differently-worded mentions resolving to the same place don't share
   a text key) — both needed the same priority signal.
2. Every candidate is checked against `LocationService.resolve_all()` —
   only phrases that resolve to a real place survive. Ambiguous matches
   (a bare phrase matching several distinct real places) get two
   disambiguation attempts before being surfaced as unresolved: a
   candidate-specific suffix search across the raw text, then "was one
   of these options already confirmed elsewhere in this same contract."
   Genuinely unresolvable ambiguity shows as an amber warning row on the
   card and in the COPY ROUTE export, never a silent guess.
3. Resolved pickups/drop-offs (a contract can have several of *either*)
   get their commodity extracted from "Collect X from Y"/"Deliver...of X
   to Y" lines, searched against every raw OCR spelling that resolved to
   that place (not just the winning one). When no commodity can be found
   at all, the entry shows an explicit "cargo unknown — check raw OCR
   text" label rather than a silent blank — a blank read as "confirmed
   nothing to carry," which is never actually true for a real contract.
4. Newly-scanned contracts are checked against every already-added one:
   same reward + at least one resolved location in common (not a full
   exact-set match, which real OCR noise varying scan-to-scan can break)
   triggers a themed CONFIRM/DENY popup instead of silently duplicating
   the route.
5. Route planning is greedy nearest-neighbour from the CURRENT LOCATION
   pick, followed by a precedence-aware 2-opt improvement pass (fixes
   backtracking routes the greedy pass alone can produce), with a hard
   constraint throughout: a drop-off is ineligible until every pickup on
   its own contract has been visited.

## UEX endpoints used (via the shared LocationService)

- `star_systems`, then `terminals`/`space_stations`/`outposts`/`cities`
  per available system — one name → location-record index, endpoint-
  tagged so dedup/lookup never collides two unrelated real places
  sharing a bare numeric id across endpoints.
- `terminals_distances` (terminal-to-terminal — finer precision, avoids
  collapsing two different terminals on the same planet to zero) and
  `orbits_distances` (works for any location, including cross-system) —
  **wired in as the primary route cost** (`LocationService.distance()`,
  queried lazily per pair/system-pair, cached per-session). Falls back to
  a coarse same-terminal/body/system/different-system tier, rescaled
  into the same numeric range, only when a real distance can't be
  determined.

## Card contents

- Region status label + SELECT REGION button (drag-draw a capture
  rectangle on any monitor)
- CURRENT LOCATION picker — editable combo + `QCompleter` (`MatchContains`,
  case-insensitive) over the full resolved location index, labeled with
  both name and short code (`"Shallow Frontier Station (MIC-L1)"`) so
  searching by either works
- SCAN CONTRACT button (flips to "SCANNING…" and disables itself while
  OCR/API work runs, since it's fully synchronous on the GUI thread — no
  progress signal without a threading redesign), CLEAR button, and COPY
  ROUTE (exports the full contract list + suggested route + per-edge
  cost/distance + raw OCR text as plain text, to the clipboard)
- AUTO RESCAN checkbox (off by default)
- Scrollable contract list (pickups → drop-offs, commodities, reward) +
  suggested visiting order; amber warning rows for any still-ambiguous
  location
- A themed CONFIRM/DENY popup (same `Qt.Popup` pattern as the app's
  Settings/Tray panels) when a scan looks like a duplicate of an
  already-added contract

## Settings (modules.logistics_hub in config.json)

- `region`: `{x, y, w, h}` of the last selected capture rectangle
- `contracts`: accumulated list of parsed contracts, each
  `{id, pickups: [{raw, terminal, commodities}], dropoffs: [...], reward,
  scanned_at, ambiguous, raw_text}`
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
- Route cost uses real UEX distance data, not a guessed heuristic
- Human-verified inside the real running app across many rounds of real
  captured contracts — not just backend/API calls
