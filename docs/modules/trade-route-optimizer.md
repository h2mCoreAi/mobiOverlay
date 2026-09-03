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

- Input: star system → origin terminal (two-level picker), optional max
  investment budget
- Output: top routes ranked by profit, each showing commodity, destination
  terminal + location, profit, ROI%
- Manual refresh + auto-refresh on the module's own interval

## UEX endpoints used (verified live, 2026-09-03)

- `star_systems` — system picker; only 3 currently have `is_available: 1`
  (Stanton=68, Pyro=64, Nyx=55) — filter to those, don't show the ~70
  unavailable/unimplemented systems in the picker
- `terminals?id_star_system=<id>&type=commodity` — origin terminal picker,
  scoped to the chosen system (117 terminals for Stanton alone; must be
  system-scoped, not a flat list)
- `commodities_routes?id_terminal_origin=<id>[&investment=<amt>]` — returns
  routes for ALL commodities sellable from that terminal, not just one.
  Confirmed real response includes (per row): `commodity_name`, `profit`,
  `price_roi`, `distance`, `score`, `origin_terminal_name`,
  `destination_terminal_name`, `destination_star_system_name`,
  `destination_planet_name`. Sort/filter client-side from this one response
  — no separate call per commodity needed.

`commodities_routes` requires at least one of `id_terminal_origin`,
`id_planet_origin`, `id_orbit_origin`, or `id_commodity` — an empty query
returns `missing_one_required_inputs`. This module always sends
`id_terminal_origin`.

## Card contents

- System dropdown (Stanton/Pyro/Nyx only)
- Origin terminal dropdown (repopulated when system changes)
- Optional investment budget field (numeric, blank = unlimited)
- Top 5 routes by profit, each row: commodity, destination terminal +
  system/planet, profit (aUEC), ROI%
- Last-updated timestamp, manual refresh button
- Error state: message + retry, same as Price Lookup

## Settings (modules.trade_route_optimizer in config.json)

- `origin_system`: last-selected system name, restored on relaunch
- `origin_terminal`: last-selected terminal name, restored on relaunch
  (reset if not present in a newly-fetched terminal list for the system)
- `investment_budget`: last-entered value, blank by default
- `refresh_interval_seconds`: default 300s

## Done criteria

- Card renders inside the host's card container, respects drag/collapse/close/resize
- System → terminal cascading picker works and persists selection
- Live route data pulled via shared host HTTP client
- Survives a bad/empty API response (e.g. terminal with no profitable
  routes) without crashing the host
