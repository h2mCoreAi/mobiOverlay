# Module: Commodity Prices

Status: built and working. First module, built alongside the host to prove
the module contract in ARCHITECTURE.md. Originally named "Price Lookup" —
renamed (2026-09-03) since it's commodities only (ore, agricultural goods,
etc.), not general items/gear/ships — the old name implied broader scope
than it has. Module folder, `module_id`, and class renamed to match
(`price_lookup` → `commodity_prices`).

## Scope

A card that looks up the best known price for a commodity across terminals,
plus a client-side scan (RETRIEVE DATA) to find the single most profitable
commodity right now. Best Sell and Best Buy each have their own independent
star-system filter (e.g. buy in Stanton while selling in Pyro, or restrict
both to one system).

- Input: pick a commodity (dropdown), optionally filter Best Sell and Best
  Buy to one star system each, independently; or click "RETRIEVE DATA" then
  "FIND MOST PROFITABLE" to have it pick the commodity for you
- Output: best sell price + terminal/location, best buy price +
  terminal/location, each respecting its own system filter
- Manual refresh button + auto-refresh on the module's own interval

## UEX endpoints used

- `commodities` — list of commodities for the picker (`GET`, no auth needed)
- `commodities_prices?commodity_name=<name>` — current prices per terminal
  for a given commodity (`GET`, no auth needed). **`commodity_name` is a
  substring match, not exact** (confirmed live, 2026-09-03) — querying
  `"Diamond"` also returns `"Diamond Laminate"` rows. `refresh()` and the
  Retrieve Data loop both filter the response to
  `commodity_name == name` exactly before using it, or the wrong
  commodity's price can silently win "best price."
- Terminal nicknames come from the shared `LocationService.all_locations()`
  (`host/locations.py`) rather than a direct `terminals?type=commodity`
  fetch of this module's own — `_populate_terminal_nicknames()` builds its
  `id_terminal -> nickname` map from that shared, cached index (Phase 4 of
  the Core Location service migration, see DECISIONS.md)

Confirmed via real API calls (2026-09-03): `commodities_prices` rows come
pre-joined with `terminal_name`, `star_system_name`, `planet_name`,
`city_name` — no separate `terminals` lookup is needed for the location
fields themselves. Star-system filter options are derived client-side
from the fetched rows, not a separate systems endpoint.

**`terminal_name` is the raw in-game kiosk label, not a clean display
name** (2026-09-03 bug fix) — e.g. `"Admin - MIC-L2"` or `"TDD - Trade and
Development Division - Area 18"`, not `"MIC-L2"` or `"TDD Area 18"`.
`commodities_prices` has no nickname field of its own, so `_format_location()`
looks the clean name up by `id_terminal` in the `_terminal_nicknames` map
built from `LocationService.all_locations()` (`_populate_terminal_nicknames()`),
falling back to the raw `terminal_name` only if a terminal isn't found in
that map. Same field (`nickname`) `trade_route_optimizer`'s origin-terminal
picker already uses, for consistency — see that module's doc for the same
issue on the `commodities_routes` endpoint (which needed a hand-rolled
prefix strip instead, since it has no `id_terminal` for the destination to
look up by).

**No true "most profitable commodity" endpoint exists.** `commodities_ranking`
is deprecated (confirmed live — returns empty data). Its documented
replacement, `commodities_averages`, requires a bearer token AND is still
per-commodity (`id_commodity` required) — not a discovery/ranking query.
Since the project's hard rule is never embedding our own UEX token in the
distributed app, "RETRIEVE DATA" instead does a client-side brute-force scan
across every commodity, caching the raw results in memory; "FIND MOST
PROFITABLE" is a separate, instant, purely local action that reads that
cached data (and the current Best Sell/Best Buy system filters) with no API
call of its own — see docs/DECISIONS.md for the full reasoning that led
here, and for the bug that motivated splitting the one combined action into
these two (the original combined scan ignored the system filters entirely).

**Stock-aware, not a bare price margin (2026-09-05 fix).** Originally
computed `max(price_sell) - min(price_buy)` per commodity — a pure per-unit
price gap with no regard for how much was actually available to trade.
Real example that surfaced this: it picked a commodity with a huge margin
but only 2 SCU of source stock at the cheapest terminal, over a commodity
with a much smaller per-unit margin but thousands of SCU available (the
realistically better trade — confirmed by cross-checking Trade Route
Optimizer's `commodities_routes`-driven answer for the same origin
terminal, live). Now ranks by
`(price_sell - price_buy) * scu_buy` (best pairing per commodity), capped
by the BUY side's `scu_buy` (source stock). **Deliberately not gated by
`scu_sell`** — checked live across 5 commodities, `scu_sell` (destination
capacity) is 0 despite a real `price_sell` 75-95% of the time (UEX doesn't
reliably track sell-side demand caps the way it tracks source stock;
`commodities_routes`' own `scu_destination` field confirms this — it
mirrors `scu_origin` rather than an independently-tracked demand number).
The regular Best Sell/Best Buy rows (`_apply_filters()`) got the same
`scu_buy > 0` gate on their Best Buy pick, for the same reason — a quoted
buy price with 0 stock isn't real. Best Sell stays a pure price
comparison, same reasoning.

## Card contents

- Commodity selector
- "RETRIEVE DATA" button — runs the brute-force scan across all commodities
  (see below)
- "FIND MOST PROFITABLE" button — instant, local; ranks the data already
  downloaded by RETRIEVE DATA using the current system filters
- "Best Sell" row: label + system filter dropdown ("All Systems" + systems
  present in the data), price, terminal/location
- "Best Buy" row: same, independent filter/state from Best Sell
- Last-updated timestamp, manual refresh button
- Error state: message + retry button if the fetch fails; rest of app
  unaffected (host error boundary). A UEX rate-limit hit shows a distinct,
  specific message ("UEX rate limit reached — wait a moment, then retry")
  rather than a generic failure — see `UexRateLimitError` in
  `host/api_client.py`

## Retrieve Data / Find Most Profitable — how it works

Split into two separate actions (see DECISIONS.md for the bug that
motivated the split: the original combined scan computed margin across ALL
systems, ignoring the Best Sell/Best Buy system filters entirely):

- **RETRIEVE DATA** — the download step:
  - Triggered only by clicking the button — never runs automatically, so it
    never silently burns rate-limit budget on a refresh or app launch
  - Scans commodities one at a time on a `QTimer` (120ms between calls, ~8
    req/sec) rather than one long blocking loop, so the UI stays responsive
    and shows live progress ("RETRIEVING 42/118") instead of freezing
  - A commodity that individually fails to fetch is skipped, not treated as
    a scan-ending error; hitting UEX's actual rate limit mid-scan stops the
    scan and shows the clear rate-limit message with a retry
  - Raw per-commodity rows are cached in memory (`_all_commodity_data`); a
    countdown ("REFRESH IN MM:SS", 30 min) gates re-fetching — clicking
    while it's counting down prompts "FORCE UPDATE?" first rather than
    re-fetching immediately
  - One call per commodity (~200) in one burst — a deliberate, bounded,
    one-time cost per click, not background polling. Note the "120/min"
    limit cited elsewhere in this project is unconfirmed: a real run of 205
    calls in ~25s (~490/min) completed without being rate-limited (see
    `docs/HISTORY.md`). If UEX does rate-limit, the scan stops cleanly with
    the rate-limit message (HTTP 429 is detected too, since 2026-10-03).
- **FIND MOST PROFITABLE** — instant and purely local:
  - Reads the already-downloaded `_all_commodity_data` and the Best
    Sell/Best Buy system filters' current state at click time — no API call
  - Stock-aware ranking (see above) applied over whatever was last
    retrieved; re-run it as many times as you like after changing filters
    with no additional cost

## Settings (modules.commodity_prices in config.json)

- `watched_commodity`: last-selected commodity, restored on relaunch
- `sell_system_filter` / `buy_system_filter`: last-selected system per row
  (default `"All Systems"`), restored on relaunch; reset to "All Systems"
  if the saved system isn't present in a newly-fetched commodity's data
- `refresh_interval_seconds`: default 300s (balance against UEX rate limit —
  120 req/min, 172,800/day shared across all modules). Filter changes do
  NOT trigger a new API call — they recompute from the last-fetched rows.

## Done criteria

- Card renders inside the host's card container, respects drag/collapse/close/resize — done
- Live data pulled from UEX API with the shared host HTTP client (not its own) — done
- Survives a bad/empty API response without crashing the host — done
- Independent per-row system filtering — done
- Retrieve Data scan with progress, caching, and clear rate-limit errors;
  Find Most Profitable as a separate instant/local, stock-aware ranking
  step — done, verified end-to-end (live scan + selection)
