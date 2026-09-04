# Module: Commodity Prices

Status: built and working. First module, built alongside the host to prove
the module contract in ARCHITECTURE.md. Originally named "Price Lookup" —
renamed (2026-09-03) since it's commodities only (ore, agricultural goods,
etc.), not general items/gear/ships — the old name implied broader scope
than it has. Module folder, `module_id`, and class renamed to match
(`price_lookup` → `commodity_prices`).

## Scope

A card that looks up the best known price for a commodity across terminals,
plus a brute-force scan to find the single most profitable commodity right
now. Best Sell and Best Buy each have their own independent star-system
filter (e.g. buy in Stanton while selling in Pyro, or restrict both to one
system).

- Input: pick a commodity (dropdown), optionally filter Best Sell and Best
  Buy to one star system each, independently; or click "Find Most
  Profitable" to have it pick the commodity for you
- Output: best sell price + terminal/location, best buy price +
  terminal/location, each respecting its own system filter
- Manual refresh button + auto-refresh on the module's own interval

## UEX endpoints used

- `commodities` — list of commodities for the picker (`GET`, no auth needed)
- `commodities_prices?commodity_name=<name>` — current prices per terminal
  for a given commodity (`GET`, no auth needed)

Confirmed via real API calls (2026-09-03): `commodities_prices` rows come
pre-joined with `terminal_name`, `star_system_name`, `planet_name`,
`city_name` — no separate `terminals` lookup is needed for this module.
Star-system filter options are derived client-side from the fetched rows,
not a separate systems endpoint.

**No true "most profitable commodity" endpoint exists.** `commodities_ranking`
is deprecated (confirmed live — returns empty data). Its documented
replacement, `commodities_averages`, requires a bearer token AND is still
per-commodity (`id_commodity` required) — not a discovery/ranking query.
Since the project's hard rule is never embedding our own UEX token in the
distributed app, "Find Most Profitable" is instead a client-side brute-force
scan: call `commodities_prices` once per commodity (~100-150 calls), compute
`max(price_sell) - min(price_buy)` per commodity, pick the winner. See
docs/DECISIONS.md for the full reasoning that led here.

## Card contents

- Commodity selector
- "FIND MOST PROFITABLE" button — runs the brute-force scan (see below)
- "Best Sell" row: label + system filter dropdown ("All Systems" + systems
  present in the data), price, terminal/location
- "Best Buy" row: same, independent filter/state from Best Sell
- Last-updated timestamp, manual refresh button
- Error state: message + retry button if the fetch fails; rest of app
  unaffected (host error boundary). A UEX rate-limit hit shows a distinct,
  specific message ("UEX rate limit reached — wait a moment, then retry")
  rather than a generic failure — see `UexRateLimitError` in
  `host/api_client.py`

## Find Most Profitable — how it works

- Triggered only by clicking the button — never runs automatically, so it
  never silently burns rate-limit budget on a refresh or app launch
- Scans commodities one at a time on a `QTimer` (120ms between calls, ~8
  req/sec) rather than one long blocking loop, so the UI stays responsive
  and shows live progress ("SCANNING 42/118") instead of freezing
- A commodity that individually fails to fetch is skipped, not treated as a
  scan-ending error; hitting UEX's actual rate limit mid-scan stops the
  scan and shows the clear rate-limit message with a retry
- Result is cached in memory for 30 minutes (`SCAN_CACHE_SECONDS`) — a
  second click within that window just re-selects the cached commodity
  instead of re-scanning everything
- ~100-150 calls in one burst is well under the 120/min UEX limit; this is
  a deliberate, bounded, one-time cost per click, not background polling

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
- Find Most Profitable scan with progress, caching, and clear rate-limit
  errors — done, not yet human-tested (built this session)
