# Module Backlog — Ranked by Community Interest

Modules narrowed to only those that map directly to an existing UEX endpoint
(no custom pathfinding/logic UEX doesn't already compute, no unverified
account/auth requirement — see docs/PROGRESS.md for what was cut and why).

Ranked by researched community interest (2026-09-03), not just endpoint
availability. Evidence tiers:
- **Strong** — named directly as an essential/most-recommended tool or has
  multiple dedicated community tools built solely for it
- **Moderate** — part of what the essential tools do, but not the headline
  feature; real but secondary demand
- **Weak/unconfirmed** — no direct evidence found of standalone community
  demand; plausible utility, not validated

## Tier 1 — Strong evidence

1. **Commodity Prices** — *(built, originally named "Price Lookup")* — foundational to every major tool
   ("SC Trade Tools... shop and commodity browser", "UEX covers commodity
   prices" — both named among the 3 essential community tools alongside
   Erkul)
2. **Trade Route Optimizer** — SC Trade Tools is explicitly "the
   most-recommended trade route planner," with Best Routes/Best Buyer as
   its headline feature
3. **Refinery Yield Calculator** — multiple dedicated standalone community
   tools exist for exactly this (CStone.space, AO Gaming Mining Calculator)
   — strong signal of real, focused demand
4. **Item Price Lookup / Ship Outfitting** — Erkul named as one of the
   3 essential install-first tools ("make them Erkul for loadouts, SC
   Trade Tools and UEX for making credits")

## Tier 2 — Moderate evidence

5. **Vehicle Purchase/Rental Price Finder** — adjacent to the
   Erkul/loadout-shopping category and the pledge-savings tool space
   (CCU Game), but not itself named as essential
6. **Refinery Capacity/Queue Tracker** — same community (miners/industrial
   players) as the yield calculator, but no dedicated tool found for this
   specifically
7. **Terminal Finder / Distance Calculator** — a supporting feature inside
   SC Trade Tools (route/travel-time computation) rather than a standalone
   draw
8. **Fuel Price Finder** — practical, low-friction utility; no dedicated
   tool found, likely folded into trade-route tools already

## Tier 3 — Weak/unconfirmed evidence

9. **Commodity Price Alerts / Market Tracker** — no distinct community
   buzz found; likely covered by checking the trade-route tools directly
   rather than as a standalone alerting product
10. **Commodity Price History / Trends**
11. **Commodity Ranking (most profitable/most traded)** — **dead end,
    confirmed 2026-09-03**: `commodities_ranking` is deprecated (returns
    empty data live), its replacement `commodities_averages` needs a
    bearer token and is per-commodity, not a ranking query. "Most
    profitable" was instead built into Commodity Prices as a client-side
    brute-force scan — see docs/modules/commodity-prices.md and
    DECISIONS.md. Don't re-investigate this endpoint expecting different
    results.
12. **Raw-vs-Refined Comparator**
13. **Ship Loaner Lookup**
14. **Marketplace Listings Browser**
15. **Marketplace Trend/Average Tracker**
16. **Marketplace Watchlist/Favorites**
17. **Marketplace Negotiation Tracker**
18. **Refinery Audit/History Viewer**

## Tier 4 — Pure reference, no evidence of standalone demand

19. **Game Version / Data-Staleness Indicator**
20. **Faction Reference**
21. **Contracts Browser**
22. **Organization Lookup**

## High want, high complexity — not ranked in the tiers above

**Multi-Stop Contract Route Optimizer.** User's own explicit high-priority
want (2026-09-03), not from the community-interest research above — a
different category of ask, so kept separate rather than slotted into a
tier.

- **Problem:** when you've picked up multiple hauling/box-delivery
  contracts, what order should you visit the pickup/dropoff terminals in
  to minimize travel?
- **Why it can't be fully automated:** live mission-board contract data
  (which contracts you're actually holding, their pickup/dropoff points)
  is server-side, per-player, and not exposed by UEX or any public API —
  same root limitation as the original Game.log combat-data problem. The
  user would have to manually enter their current stops; nothing can read
  that state for them.
- **What IS confirmed to work (tested live, 2026-09-03):**
  `terminals_distances?id_terminal_origin=<id>&id_terminal_destination=<id>`
  returns a real distance for exactly one terminal pair per call — e.g.
  ARC-L1 → ArcCorp Mining Area 056 returned `distance: 3`. No bulk/matrix
  mode — an N-stop run needs up to N×(N-1) calls to build a full distance
  matrix (trivial against the 120/min rate limit for realistic stop counts
  of 4-8).
- **Why it's harder than every other module so far:** every other module
  in this backlog just displays data UEX already computed
  (`commodities_routes` literally hands back the best route). This one
  needs actual routing logic written on our side — build a distance
  matrix from pairwise calls, then solve "best order to visit all stops"
  (a small-scale TSP-like problem; brute-force or nearest-neighbor is
  plenty at 4-8 stops, no need for a real solver). It's also the first
  module whose primary input is manual user entry rather than an API
  picker — a different UI shape (an editable stop list, not a dropdown).
- **Not scoped yet.** Revisit when ready — write
  `docs/modules/contract-route-optimizer.md` at that point.

## Sources

- [SC Trade Tools](https://sc-trade.tools/)
- [SC Trade Tools GitHub](https://github.com/EtienneLamoureux/sc-trade-tools)
- [Best Star Citizen Community Tools & Utilities (2026) — citizenfreefly.com](https://www.citizenfreefly.com/star-citizen-community-tools/)
- [UEX Community Tools](https://uexcorp.space/api/community_made/)
- [Erkul](https://erkul.games/)
- [AO Gaming Mining Calculator](https://aogaming.tools/star-citizen/mining-calculator/)
- [CStone.space](https://dutchdemons.com/tool/cstone-space/)
- [Schaulers Trade Route Planner](https://schaulers.space/app)

## Status

Commodity Prices, Trade Route Optimizer, and Refinery Finder (tiers 1.1,
1.2, and 1.3) are all built — see docs/PROGRESS.md. Refinery Finder is a
narrower-scoped "Refinery Yield Calculator": ranks real terminals by
reported yield modifier rather than computing an exact SCU-in/SCU-out
number, since UEX doesn't expose the base composition data a literal
calculator would need (see docs/modules/refinery-finder.md). Item Price
Lookup / Ship Outfitting (1.4) is the strongest remaining Tier 1 pick. The
Multi-Stop Contract Route Optimizer above is a separate high-priority
want, held for later due to its complexity.
