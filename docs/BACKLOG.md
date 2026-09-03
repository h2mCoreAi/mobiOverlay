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

1. **Price Lookup** — *(built)* — foundational to every major tool
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
11. **Commodity Ranking (most profitable/most traded)**
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

## Sources

- [SC Trade Tools](https://sc-trade.tools/)
- [SC Trade Tools GitHub](https://github.com/EtienneLamoureux/sc-trade-tools)
- [Best Star Citizen Community Tools & Utilities (2026) — citizenfreefly.com](https://www.citizenfreefly.com/star-citizen-community-tools/)
- [UEX Community Tools](https://uexcorp.space/api/community_made/)
- [Erkul](https://erkul.games/)
- [AO Gaming Mining Calculator](https://aogaming.tools/star-citizen/mining-calculator/)
- [CStone.space](https://dutchdemons.com/tool/cstone-space/)
- [Schaulers Trade Route Planner](https://schaulers.space/app)

## Next pick

Trade Route Optimizer (`commodities_routes`) is the strongest next candidate
by both this research and the original endpoint-availability ranking — write
`docs/modules/trade-route-optimizer.md` when it's picked up.
