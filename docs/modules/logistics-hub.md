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
- On-demand scan only (SCAN CONTRACT button) — no auto-rescan, per the
  original design goal of not continuously burning CPU/memory watching a
  region (an opt-in auto-rescan toggle existed briefly but was removed
  2026-09-04, unused)

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
   card and in the COPY ROUTE export, never a silent guess. A candidate
   with a real pickup/dropoff hint but zero exact/substring matches gets
   one more attempt via `LocationService.resolve_fuzzy()` (a stricter,
   opt-in-only fuzzy match, cutoff 0.85) before being dropped — resolves
   OCR names garbled just enough to miss substring matching ("Seraphim
   Staton"), but visibly flagged with the same amber-warning mechanism
   ("fuzzy-matched to X (NN% confidence) — please verify") rather than
   silently trusted. Never used for `neutral`-hint candidates, and never
   folded into `resolve()`/`resolve_all()` themselves — see
   `host/locations.py`'s docstring for why (other callers have no way to
   show the uncertainty warning).
3. Resolved pickups/drop-offs (a contract can have several of *either*)
   get their commodity extracted from "Collect X from Y"/"Deliver...of X
   to Y" lines, searched against every raw OCR spelling that resolved to
   that place (not just the winning one). When no commodity can be found
   at all, the entry shows an explicit "cargo unknown — check raw OCR
   text" label rather than a silent blank — a blank read as "confirmed
   nothing to carry," which is never actually true for a real contract.
   A pickup's quantity is the *sum* across every "Deliver...to..." line
   for that commodity, not just one of them — a single pickup can feed
   several drop-offs of the same commodity (e.g. 52 SCU Titanium to one
   station, 50 SCU to another, 102 total to actually collect), confirmed
   real and under-reported before this was fixed (see DECISIONS.md,
   2026-09-05). Each drop-off still shows its own individual amount, never
   the combined total.
4. Newly-scanned contracts are checked against every already-added one:
   same reward + at least one resolved location in common (not a full
   exact-set match, which real OCR noise varying scan-to-scan can break)
   triggers a themed CONFIRM/DENY popup instead of silently duplicating
   the route.
5. Route planning is greedy nearest-neighbour from the CURRENT LOCATION
   pick, followed by alternating precedence-aware 2-opt (segment reversal —
   fixes backtracking routes the greedy pass alone can produce) and Or-opt
   (single-stop relocation) improvement passes, run until neither improves
   further. Or-opt added 2026-09-05: 2-opt alone can't merge two
   non-adjacent visits to the same real terminal (once as a pickup for one
   contract, once as a dropoff for another) into a single stop, since that
   requires moving one node past several others without reversing anything
   between them — confirmed missed on live data before the fix (see
   DECISIONS.md). Hard constraint throughout both passes: a drop-off is
   ineligible until every pickup on its own contract has been visited.

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
  progress signal without a threading redesign), COPY ROUTE (exports the
  full contract list + suggested route + per-edge cost/distance + raw OCR
  text as plain text, to the clipboard; briefly shows "COPIED" on click),
  REPROCESS (re-runs parsing — locations + commodities — against every
  saved contract's own stored raw OCR text and replans the route, no
  rescan needed; added 2026-09-05 so a parsing fix can be picked up on
  contracts already sitting in a session, see DECISIONS.md), and CLEAR
  (placed away from SCAN/COPY/REPROCESS since it's destructive and easy to
  hit by reflex reaching for the others)
- An at-a-glance summary line below CONTRACTS' title ("4 contracts ·
  268,750 aUEC · 143 SCU peak cargo") — added 2026-09-05, always visible
  without scrolling either list. Peak cargo is the running max along the
  *planned route* (+SCU on pickup, -SCU on dropoff), not a flat sum of
  every pickup, since some cargo gets delivered before more is picked up.
- The card's own ROUTE area shows only a stop count + prompt to use
  TRACKER — the full stop-by-stop list (with done/skip toggling) lives
  solely in the Tracker popout now. Briefly tried inline on the card too
  (a NEXT STOP banner plus the full row list, both 2026-09-05) — reverted
  same day: went invisible on the card in live testing (root cause not
  pinned down — a scroll-position fix didn't resolve it) and the Tracker
  popout is the tool actually used for working a route anyway, so this
  removes the broken code path instead of continuing to chase it blind.
  See DECISIONS.md.
- A CONTRACTS section (pickups → drop-offs, commodities, reward, each
  with a per-contract remove button, plus amber warning rows for any
  still-ambiguous location) in its own dedicated scroll area on the card.
  Briefly tried as a detached popup window (2026-09-04) — reverted same
  day: the popup's title bar close button triggered
  `quitOnLastWindowClosed`, quitting the whole app (the main window's
  `Qt.Tool` flag excludes it from Qt's "last window" count — fixed at the
  host level regardless, see DECISIONS.md, but the user also didn't want
  a popup for this). Landed on a second, independent `QScrollArea` inside
  the card instead of sharing one with ROUTE below it — the original
  inline version shared one scroll area with ROUTE and a freshly-scanned
  contract could leave that viewport scrolled into ROUTE, hiding
  CONTRACTS; two independent scroll areas can't do that to each other.
- A ROUTE section (suggested visiting order) inline on the card, in its
  own scroll area. Each stop is click-toggleable (marks it done/skipped,
  greyed out with strikethrough) and the whole section can be popped out
  into its own always-on-top window (no minimize button — closing it
  returns the view to the card; the underlying route/done-state lives on
  the module regardless of whether the popout is open)
- A themed CONFIRM/DENY popup (same `Qt.Popup` pattern as the app's
  Settings/Tray panels) when a scan looks like a duplicate of an
  already-added contract
- No auto-rescan — on-demand SCAN CONTRACT only (removed 2026-09-04, see
  DECISIONS.md)

## Debug log

Always-on, append-only JSON Lines file at `paths.app_root() /
"logistics_hub_debug.jsonl"` (next to `config.json`, not inside the module
folder). One JSON object per scan (`_log_scan_debug()`, called from
`refresh()`): timestamp, raw OCR text, candidate phrases with role
hint/priority, the built contract, a per-candidate `resolution_trace` (which
of the five resolution paths won each `resolved` candidate, or why one was
`dropped_no_match`/`ambiguous_unresolved` — including a near-miss fuzzy score
for a dropped candidate even when it missed the cutoff, added 2026-09-05 to
close the "vanished with zero trace" gap; see DECISIONS.md), a `fuzzy_matches`
convenience field derived from that trace, a `route_debug` field (greedy
pre-2-opt route + cost alongside the final route + cost, so a review can tell
whether 2-opt actually improved anything on that scan), and a route snapshot
(reuses `_format_route_text()`, the same text COPY ROUTE produces). No
cap/rotation — user manages the file manually. See DECISIONS.md, 2026-09-04,
for scoping.

A REPROCESS run also logs one entry (`_log_reprocess_debug()`, added
2026-09-05) — same shape, but covering every reprocessed contract at once
(`contracts`, `resolution_traces` as a list of per-contract traces,
`fuzzy_matches`, `route_debug`, `route_snapshot`) rather than one fresh
scan's `raw_text`/`candidates`/`contract`, since REPROCESS re-parses
everything already saved in one pass instead of adding a new contract.
Without this, a REPROCESS run (or a location change picked up by one) left
nothing reviewable in the log at all.

## Settings (modules.logistics_hub in config.json)

- `region`: `{x, y, w, h}` of the last selected capture rectangle
- `contracts`: accumulated list of parsed contracts, each
  `{id, pickups: [{raw, terminal, commodities}], dropoffs: [...], reward,
  scanned_at, ambiguous, raw_text}`
- `current_location_name` / `current_location`: the picked starting point
  (display label + full resolved terminal record)
- `route_done`: list of `"{contract_id}:{role}:{index}"` keys for route
  stops toggled done/skipped (per-stop, not per-contract, since a
  contract can have several pickups or drop-offs)

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
