# Module: Trade Route Optimizer

Status: built and working, host-verified via screenshot. Tier 1 pick from
docs/BACKLOG.md — strongest researched community interest (SC Trade Tools'
headline feature).

**Note on ranking:** sorting by raw `profit` can show the same commodity in
all 5 slots if one commodity dominates a terminal's economy (confirmed real
against the live API for ARC-L1 — Laranite filled every top-5 slot there,
not a bug). Worth considering a "diversify by commodity" or ROI-sort option
later if that turns out to be an unhelpful default in practice.

## Scope

A card that shows the most profitable known trade routes from a chosen
origin terminal, using UEX's pre-computed route data (not custom logic —
`commodities_routes` already returns profit/ROI/score per route).

- Input: origin terminal, single searchable combo across every available
  system at once (see "Card contents" below) = **where you buy** — optional
  as of 2026-09-05 (see "Any Location / BUY IN" below), optional max
  investment budget, optional destination-system filter ("Sell In") =
  **where you're willing to sell** — client-side only, no extra API call,
  same pattern as Commodity Prices' filters
- Output: top routes ranked by profit, each showing origin ("BUY AT"),
  commodity, destination terminal + location ("SELL AT"), profit, ROI%
- Manual refresh + auto-refresh on the module's own interval, when a
  specific origin terminal is picked; a manual SCAN otherwise (see below)

**Buy/sell relationship, spelled out** (added 2026-09-04 after the user
had to ask what a route row actually meant): the origin terminal picker
is the buy side — every row's "SELL AT ..." is the different sell side for
that one commodity. Each row also shows "BUY AT ..." explicitly (added
2026-09-05, alongside "Any Location" below) — necessary once a scan can
mix results from several different origin terminals, and kept in
single-terminal mode too for consistency.

**"Any Location" / BUY IN system filter (2026-09-05)** — a real trader
often doesn't have a fixed starting terminal yet; they want to know the
best trade anywhere (or anywhere in a system they're willing to fly to),
then decide where to go. Origin combo gained an `— Any Location —`
sentinel (first item, default) alongside a new BUY IN system filter:
  - No BUY IN filter, no terminal picked → search every live commodity
    terminal in the game.
  - BUY IN filter set, no terminal picked → search every terminal in that
    one system.
  - Terminal picked → exactly the original single-terminal behavior; BUY
    IN is disabled (moot) while a terminal is selected.

  **`commodities_routes` has no bulk-origin query** — confirmed live:
  `id_star_system_origin` alone returns `missing_one_required_inputs`; the
  endpoint strictly requires one of `id_terminal_origin` / `id_planet_origin`
  / `id_orbit_origin` / `id_commodity` per call. So "Any Location"/BUY IN
  genuinely means calling the endpoint once per candidate terminal (up to
  114 for the whole game, fewer per system) and merging results — there's
  no server-side shortcut. This is why it's a manual **SCAN** button
  (labeled with the live terminal count, e.g. "SCAN 114 TERMINALS" /
  "SCAN 80 TERMINALS (STANTON)"), not automatic: `refresh()` runs
  synchronously on the host's auto-refresh timer and at startup
  (`host/main.py`'s `wrap_refresh`), so a 15-30+s multi-call scan can never
  live there. SCAN is its own `QTimer`-throttled action
  (`SCAN_STEP_INTERVAL_MS = 120`, ~8 req/sec), ported directly from
  Commodity Prices' Retrieve Data pattern
  (`_start_retrieve`/`_retrieve_step`/`_finish_retrieve` →
  `_start_scan`/`_scan_step`/`_finish_scan`): live progress text
  ("SCANNING 12/80"), skip-and-continue on an individual terminal's
  failure, rate-limit-aware abort, and the same 30-min cache-countdown +
  "FORCE UPDATE?" confirm mechanics so a stray click can't re-trigger a
  large scan. `refresh()` is a no-op while origin is Any Location — results
  only ever come from an explicit SCAN in that mode.

## UEX endpoints used (verified live, 2026-09-03)

- Origin terminal picker now reads from the shared `host/locations.py`
  `LocationService.all_locations()` (see Core Location service in
  docs/PROGRESS.md, Phase 4) instead of a per-system `terminals` call —
  filtered client-side to `_endpoint == "terminals"`, `type == "commodity"`,
  `is_available_live`, same predicate the old system-scoped call used, just
  applied across all systems at once. Labeled via
  `LocationService.friendly_label()` (name + short code together, e.g.
  "Baijini Point (ARC-L1)") instead of a bare `nickname` — same clean-name
  fix as before (raw `name` is often kiosk-prefixed, e.g. `"Admin -
  Baijini Point"`), now also searchable by the short code.
  `friendly_label()` (added 2026-09-05, see DECISIONS.md) additionally
  borrows a sibling space_station/outpost/city record's fuller name for
  terminals whose own name/nickname is just a bare Lagrange-point code
  (e.g. "CRU-L5" -> "Beautiful Glen Station (CRU-L5)") — without it, those
  terminals were only searchable by their short code, not their real
  in-game station name.
- `commodities_routes?id_terminal_origin=<id>[&investment=<amt>]` — returns
  routes for ALL commodities sellable from that terminal, not just one.
  Confirmed real response includes (per row): `commodity_name`, `profit`,
  `price_roi`, `distance`, `score`, `origin_terminal_name`,
  `destination_terminal_name`, `destination_star_system_name`,
  `destination_planet_name`. Sort/filter client-side from this one response
  — no separate call per commodity needed. **No `nickname` field here** —
  destination display falls back to stripping the `"Admin - "` prefix by
  hand (`_strip_admin_prefix`) since the cleaner field simply isn't in
  this endpoint's response.

`commodities_routes` requires at least one of `id_terminal_origin`,
`id_planet_origin`, `id_orbit_origin`, or `id_commodity` — an empty query
returns `missing_one_required_inputs`. This module always sends
`id_terminal_origin`.

## Card contents

- Single origin terminal combo (2026-09-05: replaced the old system →
  terminal cascading picker with one searchable combo, matching Logistics
  Hub's CURRENT LOCATION picker UX) — editable with a filtering
  `QCompleter` (`Qt.MatchContains`, case-insensitive, `PopupCompletion`),
  so typing narrows the list by either the terminal's name or its short
  code instead of only scrolling. Connected to `textActivated`, not
  `currentTextChanged` — the latter fires on every keystroke once a combo
  is editable, which would trigger a refresh (and an "unknown terminal"
  error) per character typed instead of only on a committed selection.
  Deliberately terminals-only, not every location type — see
  docs/DECISIONS.md, 2026-09-05. Now includes an `— Any Location —`
  sentinel (see above).
- BUY IN system filter (All Systems default + available systems) — enabled
  only while origin is Any Location; disabled once a specific terminal is
  picked
- SCAN button — visible only while origin is Any Location; hidden once a
  specific terminal is picked (auto-refresh/manual ↻ cover that case)
- Optional investment budget field (numeric, blank = unlimited) — applies
  per terminal call in both single-terminal and scan mode
- "Sell In" destination-system filter (All Systems + systems seen in the
  fetched routes) — filters and re-sorts client-side from the already-
  fetched data, doesn't refetch
- Top 5 routes by profit (after the destination filter), each row: "BUY AT"
  + origin terminal + system/planet, commodity, "SELL AT" + destination
  terminal + system/planet, profit (aUEC), ROI%
- Last-updated timestamp, manual refresh button (single-terminal mode)
- Error state: message + retry, same as Commodity Prices

## Settings (modules.trade_route_optimizer in config.json)

- `origin_terminal_name`: last-selected origin combo label (search-label
  form, e.g. "Baijini Point (ARC-L1)"), restored on relaunch (reset if not
  present in a newly-fetched terminal list). Replaces the old
  `origin_system`/`origin_terminal` pair from the cascading picker. Can
  also legitimately be the `— Any Location —` sentinel (default).
- `buy_system_filter`: last-selected BUY IN system (2026-09-05), default
  "All Systems", reset if not present in the currently-fetched system list
- `investment_budget`: last-entered value, blank by default
- `dest_system_filter`: last-selected "Sell In" system, default "All
  Systems", reset if not present in a newly-fetched route set
- `refresh_interval_seconds`: default 300s (single-terminal mode only —
  SCAN is always manual, never on this timer)

## Done criteria

- Card renders inside the host's card container, respects drag/collapse/close/resize
- Origin combo works and persists selection
- Live route data pulled via shared host HTTP client
- Survives a bad/empty API response (e.g. terminal with no profitable
  routes) without crashing the host
