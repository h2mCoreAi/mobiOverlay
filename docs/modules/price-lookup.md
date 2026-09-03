# Module: Price Lookup

Status: built and working, host-verified via screenshot. First module,
built alongside the host to prove the module contract in ARCHITECTURE.md.

## Scope

A card that looks up the best known price for a commodity across terminals.
Best Sell and Best Buy each have their own independent star-system filter
(e.g. buy in Stanton while selling in Pyro, or restrict both to one system).

- Input: pick a commodity (dropdown), optionally filter Best Sell and Best
  Buy to one star system each, independently
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

## Card contents

- Commodity selector
- "Best Sell" row: label + system filter dropdown ("All Systems" + systems
  present in the data), price, terminal/location
- "Best Buy" row: same, independent filter/state from Best Sell
- Last-updated timestamp, manual refresh button
- Error state: message + retry button if the fetch fails; rest of app
  unaffected (host error boundary)

## Settings (modules.price_lookup in config.json)

- `watched_commodity`: last-selected commodity, restored on relaunch
- `sell_system_filter` / `buy_system_filter`: last-selected system per row
  (default `"All Systems"`), restored on relaunch; reset to "All Systems"
  if the saved system isn't present in a newly-fetched commodity's data
- `refresh_interval_seconds`: default 300s (balance against UEX rate limit —
  120 req/min, 172,800/day shared across all modules). Filter changes do
  NOT trigger a new API call — they recompute from the last-fetched rows.

## Done criteria

- Card renders inside the host's card container, respects drag/collapse/close — done
- Live data pulled from UEX API with the shared host HTTP client (not its own) — done
- Survives a bad/empty API response without crashing the host — done
- Independent per-row system filtering — done
