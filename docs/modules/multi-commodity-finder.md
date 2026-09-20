# Module: Multi-Commodity Finder

Status: built, not yet human-tested. New module, not from BACKLOG.md's
ranked list — direct user request (2026-09-08): reduce stops by finding one
terminal that trades several commodities at once, even if it isn't the
single best price for any of them individually.

## Problem

Commodity Prices and Trade Route Optimizer both answer "what's the best
price for commodity X" or "what's the best route for one commodity from one
terminal" — neither answers "I'm hauling/buying several different
commodities, which single terminal handles the most of them so I don't have
to make several stops." A terminal covering 4 of 5 commodities at slightly
worse prices can beat visiting 3 different terminals to get the best price
on each, once travel time is the real cost.

## Scope

A card where you build a list of commodities (the cargo you're hauling, or
the raw materials you want to stock up on), pick a mode (SELL — find
terminals that buy them from you — or BUY — find terminals that sell them to
you), optionally restrict to one star system and/or require a facility
(Refinery, Loading Dock, etc. — see "Facility filter" below), then SCAN.
Results rank terminals by **coverage first** (how many of your listed
commodities it trades), **total per-unit value second** (tiebreak among
equal coverage) — not pure best-price, since the whole point is trading a
slightly worse price for fewer stops.

- Input: multi-select commodity list (checkboxes), SELL/BUY mode, optional
  system filter, optional facility filter, SCAN button
- Output: ranked terminal list, each showing coverage ("4/5"), total
  aUEC/SCU across covered commodities, per-commodity price breakdown, and
  which of your listed commodities it does NOT cover — worded per the
  active mode ("doesn't buy from you" in SELL mode, "doesn't sell to you"
  in BUY mode), not a generic "not available here" (see 2026-09-08 fix
  below — that phrasing was genuinely ambiguous about which direction was
  missing)

## Facility filter (2026-09-08)

Every `terminals` row from UEX already carries boolean `is_*`/`has_*` flags
for what that location actually has — Refinery, Cargo Center, Habitation,
Medical, Food, FPS/Vehicle Shop, Refuel, Repair, Jump Point, Loading Dock,
Docking Port, Freight Elevator — confirmed live 2026-09-08 (not a field we
had to guess at or derive). Since a real use case for this module is "find
a multi-buyer terminal that also has a refinery/loading dock," an optional
facility dropdown (default "Any Facility") filters results to terminals
reporting that flag.

This lives in the shared `host/locations.py` (`LocationService.facilities()`
/ `FACILITY_FLAGS`), not hand-rolled in this module — the same
raw-flags-to-clean-names mapping is useful to any future module (Refinery
Finder, Trade Route Optimizer, a future stop planner), so it's centralized
in the same shared-service tier the Phase 1-4 location-service migration
already established, rather than re-derived per module. See
docs/DECISIONS.md, 2026-09-08.
- No auto-refresh — this is an on-demand scan, same reasoning as Commodity
  Prices' Retrieve Data and Trade Route Optimizer's Any-Location SCAN
  (multi-call, shouldn't run silently on a timer or at every app launch)

## UEX endpoints used

- `commodities` — the picker list (same as Commodity Prices)
- `commodities_prices?commodity_name=<name>` — one call per selected
  commodity, same endpoint/gotchas Commodity Prices already documented:
  **substring match, not exact** — every response is filtered to
  `commodity_name == name` before use, same as that module.
- Terminal display names via the shared `host/locations.py`
  `LocationService` (nickname/short-code resolution), same pattern as
  Commodity Prices' `_populate_terminal_nicknames` and Trade Route
  Optimizer's `friendly_label()` — `commodities_prices` only gives the raw
  kiosk `terminal_name`.

No new endpoint, no server-side cross-referencing — UEX has nothing that
answers "which terminal covers this list," this is 100% client-side grouping
over data already available per-commodity from the same endpoint every
other module already uses.

## How the scan works

- One `commodities_prices` call per selected commodity, chunked on a
  `QTimer` (same `RETRIEVE_STEP_INTERVAL_MS`-style throttle as Commodity
  Prices' Retrieve Data / Trade Route Optimizer's SCAN — ~8 req/sec), with
  live progress text and skip-on-individual-failure
- Rows are grouped by `id_terminal`. For each terminal, for each selected
  commodity, take the best valid row at that terminal:
  - SELL mode: `price_sell > 0` (same as Commodity Prices' Best Sell — no
    `scu_sell` gate, since UEX doesn't reliably track sell-side demand caps,
    see docs/DECISIONS.md 2026-09-05)
  - BUY mode: `price_buy > 0 and scu_buy > 0` (same stock gate as Commodity
    Prices' Best Buy)
  - Optional system filter applied before grouping
- Terminals are ranked by `(coverage_count, total_value)` descending, top 8
  shown
- A terminal covering 0 of the selected commodities never appears — no
  reason to show a totally irrelevant terminal

## Card contents

- Search box above the commodity list (2026-09-08) — filters the checkable
  list to names containing the typed text (case-insensitive substring,
  same approach Trade Route Optimizer's terminal picker already uses).
  Checked items stay checked/selected even while hidden by an unrelated
  search — verified live (checked Gold, searched "laranite", Gold still
  came back from `_selected_commodities()`).
- Checkable commodity list (persisted selection)
- SELL / BUY mode toggle
- Optional system filter dropdown (All Systems + systems seen in the last
  scan)
- CLEAR ALL button (2026-09-08) — one click clears the search text, unchecks
  every commodity, and resets both the system and facility filters back to
  "All Systems"/"Any Facility". Deliberately leaves SELL/BUY mode and any
  already-scanned results alone (not "filters," and clearing a visible scan
  while re-picking commodities would be surprising). Verified live.
- SCAN button, with the same countdown/force-update pattern as Commodity
  Prices' Retrieve Data (30-min cache)
- Ranked results list: terminal + location, "X/Y commodities", total
  aUEC/SCU, per-commodity price rows, missing commodities called out
- COPY button (2026-09-08) — copies a plain-text summary (mode, both
  filters, checked commodities, and the full ranked results with
  per-commodity breakdown) to the system clipboard for sharing in
  Discord/chat, same `QGuiApplication.clipboard()` +
  "COPIED"-then-revert pattern Logistics Hub's COPY ROUTE and mobiNotes'
  copy actions already use. Deliberately excludes the commodity search box
  text (per user request, 2026-09-08) — that's a UI narrowing aid, not
  part of the actual query, so it'd be noise in a shared summary. Reads
  from `_last_ranked`/`_last_selected` (set by `_render_results()`) so the
  copy always matches what's on screen, not a re-derivation. Verified live
  (isolated test config, not the user's real config.json — see
  DECISIONS.md, 2026-09-08, testing-hygiene note): real clipboard content
  checked end-to-end after a real scan, matching mode/filters/commodities/
  results exactly and confirmed the search text never appears in it even
  while active.
  **Bug fixed same day**: the mode label in this summary was inverted
  (showed "BUY" for a SELL-mode scan) — line disagreed with every other
  place in the module reading the same combo. Fixed and reverified.
- Error state: message + retry, same host error boundary as every module

## Settings (modules.multi_commodity_finder in config.json)

- `selected_commodities`: list of commodity names, persisted
- `mode`: `"sell"` or `"buy"`, default `"sell"`
- `system_filter`: last-selected system, default "All Systems"
- `facility_filter`: last-selected facility, default "Any Facility"

## Done criteria

- Card renders inside the host's card container, respects
  drag/collapse/close/resize — done
- Live data pulled via the shared host HTTP client — done
- Survives an empty commodity list / empty scan result without crashing the
  host — done
- **Not yet human-tested** — built and code-reviewed this session, needs a
  real launch with the app to confirm the scan and ranking behave correctly
  against live data, same as every module's first pass.
