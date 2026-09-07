# Module: Refinery Finder

Status: built. Picked up from docs/BACKLOG.md's Tier 1.3 "Refinery Yield
Calculator" — renamed during scoping (see below) once live API investigation
showed a literal SCU-in/SCU-out calculator isn't buildable from real UEX
data without inventing formula constants.

## Scope decision: "Finder," not a literal calculator

BACKLOG.md cited community demand for a "Refinery Yield Calculator" (multiple
dedicated tools exist — CStone.space, AO Gaming Mining Calculator). Investigated
UEX's actual refinery endpoints live (2026-09-06) before designing anything,
per this project's standing rule (never invent logic UEX doesn't already
compute — see the "most profitable" pivot in docs/modules/commodity-prices.md
for the precedent).

**What the API actually gives us:**
- `refineries_methods` — 9 real refining methods (Cormack, Dinyx Solventation,
  etc.), each with `rating_yield`/`rating_cost`/`rating_speed` on a 1-3 scale.
  Static reference data.
- `refineries_yields` — crowd-reported per-terminal, per-commodity yield
  **modifier** (`value`, confirmed live range -9 to +13) — a bonus/malus
  relative to some baseline, not an absolute percentage.
- `refineries_capacities` — per-terminal max job capacity (SCU), one row per
  terminal, not per-commodity.
- `refineries_audits` — individual real reported jobs (quantity in ->
  quantity_yield + quantity_inert out, cost, time) — only **3 rows exist
  project-wide** (confirmed live), far too sparse to reverse-engineer a
  reliable formula from.

**What's missing:** no base yield%/purity field exists anywhere for a raw
commodity (checked `commodities` directly — raw/refined pairs are linked via
`id_parent` only, no composition data). The real per-job yield depends on the
raw ore's actual composition at time of extraction, which isn't an API value
at all — it's read off the player's own mining scan in-game. Building a
"enter N SCU, get exact output" calculator would mean fabricating constants,
which this project has consistently avoided (see Commodity Prices'
`commodities_ranking` dead-end).

**What this module does instead:** surfaces UEX's own real, pre-aggregated
data directly — which terminal has the best reported yield modifier for a
chosen raw commodity, and what its capacity is — plus a static methods
comparison table. Same "let the API be the answer" philosophy as Trade Route
Optimizer's `commodities_routes` reliance.

## Card contents

- Raw commodity picker (`commodities` where `is_raw == 1`, 45 real entries
  confirmed live — sorted alphabetically)
- Optional star-system filter, same client-side pattern as Commodity Prices'
  sell/buy filters (no extra API call)
- Top 5 terminals for the selected commodity, ranked by yield modifier
  (best/highest first): terminal name, star system, yield modifier
  (`+N%`/`-N%`), capacity (SCU, comma-formatted)
- Explicit "no yield data reported yet for this commodity" state when a raw
  commodity has zero rows in `refineries_yields` (confirmed live: only 24 of
  the 45 raw commodities currently have any reports) — never silently empty
- A static REFINING METHODS reference table (all 9 methods, yield/cost/speed
  ratings as `N/3`) — independent of the commodity picker, always visible
- Manual refresh + auto-refresh on the module's own interval
- Last-updated timestamp, error state on API failure (shared host pattern)

## UEX endpoints used (verified live, 2026-09-06, no auth needed)

- `commodities` — filtered to `is_raw == 1` for the picker
- `refineries_methods` — fetched once, static reference table
- `refineries_yields` — fetched in full each refresh (215 rows, ~20 terminals
  × ~11 commodities avg — confirmed the `id_commodity` query param does
  **not** filter server-side, same "trust nothing until verified" lesson as
  Commodity Prices' `commodity_name` substring-match surprise; filtered
  client-side instead), joined to `refineries_capacities` by `id_terminal`
- `refineries_capacities` — fetched in full each refresh (20 rows, one per
  terminal, no commodity dimension)

Terminal names from these endpoints (e.g. "Refinement Center - Nyx Gateway
(Pyro)", "Refinement Processing - MIC-L2") are already clean, purpose-built
labels — confirmed live no "Admin -" kiosk-name issue like Commodity
Prices/Trade Route Optimizer hit, so no nickname-lookup pass is needed here.

## Settings (modules.refinery_finder in config.json)

- `watched_commodity`: last-selected raw commodity name, restored on
  relaunch (reset if not present in the current commodity list)
- `system_filter`: last-selected star-system filter, default "All Systems"
- `refresh_interval_seconds`: default 300s

## Done criteria

- Card renders inside the host's card container, respects
  drag/collapse/close/resize — done
- Live data pulled from UEX API with the shared host HTTP client — done
- Survives a commodity with zero yield reports without crashing — done
- Methods reference table always visible, independent of commodity
  selection — done
