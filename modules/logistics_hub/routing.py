"""Logistics Hub route ordering: greedy nearest-neighbour construction
followed by precedence-aware 2-opt and Or-opt improvement over real UEX
travel distances (via the shared LocationService).

This is the one documented exception to the "never invent logic UEX doesn't
compute" rule (see AGENTS.md): UEX has no "best order to visit these stops"
endpoint, so the ordering is ours — but every distance it optimizes over is
real UEX data.

No Qt and no module state: RoutePlanner only needs an object with
`display_name`, `same_physical_place` and `distance` (a LocationService).
Loaded by modules/logistics_hub/module.py by file path.
"""
import re

# Real UEX distance (LocationService.distance(), see host/locations.py) is
# the primary travel cost between two resolved locations now — genuine
# point-to-point/orbit-to-orbit numbers, not a guess. These are only the
# *fallback* tiers for when a real distance can't be determined (missing
# orbit/system data, or the UEX distance endpoints themselves failed) —
# scaled to roughly the same numeric range real distances live in (tens to
# low hundreds, per live UEX data) so a fallback-tier edge doesn't look
# artificially cheap next to a real-distance edge in the same route.
COST_SAME_TERMINAL = 0
COST_SAME_BODY = 5        # same planet/moon/space station/city/outpost
COST_SAME_SYSTEM = 50
COST_DIFFERENT_SYSTEM = 200
COST_UNRESOLVED = 3       # at least one side has no API match — text-heuristic territory


class RoutePlanner:
    def __init__(self, locations):
        self._locations = locations

    def _stop_nodes(self, contracts: list[dict]) -> list[tuple[int, str, int]]:
        nodes = []
        for i, c in enumerate(contracts):
            for j in range(len(c.get("pickups", []))):
                nodes.append((i, "pickup", j))
            for j in range(len(c.get("dropoffs", []))):
                nodes.append((i, "dropoff", j))
        return nodes

    def _node_entry(self, contracts: list[dict], node) -> dict:
        i, role, j = node
        key = "pickups" if role == "pickup" else "dropoffs"
        return contracts[i][key][j]

    def _node_terminal(self, contracts: list[dict], node) -> dict | None:
        return self._node_entry(contracts, node).get("terminal")

    def _node_raw(self, contracts: list[dict], node) -> str:
        return self._node_entry(contracts, node).get("raw", "")

    def plan_route(
        self, contracts: list[dict], start_terminal: dict | None, route_debug: dict | None = None
    ) -> list[tuple[int, str, int]]:
        """Visiting order across every contract's pickup and drop-off
        stops: a nearest-neighbour greedy pass to build an initial route,
        then a precedence-aware 2-opt pass to fix the greedy pass's classic
        blind spot — it can't look ahead, so it happily visits a stop early
        even when that forces an expensive backtrack later (confirmed on a
        real 4-contract test: it revisited Port Tressler twice — once for
        its own contract, then again after a detour to Crusader for a
        different contract's pickup — when picking up that Crusader cargo
        *first* and doing every microTech stop in one pass was strictly
        shorter). 2-opt repeatedly tries reversing a sub-segment of the
        route and keeps the reversal if it lowers total cost, which is
        exactly the "should I have done these in the other order" check
        greedy construction can't do on its own.

        Two things a pure "closest next stop" search would get wrong on its
        own, both handled explicitly here:
        - **Starting point.** Without this, the route always started from
          whichever contract's pickup happened to be scanned first — right
          only by coincidence. It now starts from the CURRENT LOCATION
          picker's pick (the CURRENT LOCATION terminal, passed in as `start_terminal`), falling back to
          the old "just start at the first node" behavior only if no
          location has been set yet.
        - **Pickup-before-dropoff.** You can't drop off cargo you haven't
          picked up. Every drop-off node is ineligible to be chosen until
          *all* of its own contract's pickup nodes have already been
          visited — this is a hard constraint, not a cost tiebreaker, so
          the greedy search (and the 2-opt pass afterward) will detour to
          a farther pickup rather than visit a nearer but not-yet-loaded
          drop-off, and 2-opt rejects any reversal that would break it.

        `route_debug`, if given, gets filled with the greedy route (before
        2-opt) alongside the final one plus both total costs — added
        2026-09-05 so a review of the debug log can tell whether 2-opt
        actually improved anything on a given scan, not just see the final
        route in isolation."""
        nodes = self._stop_nodes(contracts)
        n = len(nodes)
        if n == 0:
            return []

        pickups_needed = [len(c.get("pickups", [])) for c in contracts]
        pickups_done = [0] * len(contracts)

        def eligible(idx: int) -> bool:
            i, role, _j = nodes[idx]
            return role == "pickup" or pickups_done[i] >= pickups_needed[i]

        start_raw = self._locations.display_name(start_terminal) if start_terminal else None
        current_terminal, current_raw = start_terminal, start_raw

        visited = [False] * n
        order: list[int] = []

        for step in range(n):
            candidates = [idx for idx in range(n) if not visited[idx] and eligible(idx)]
            if not candidates:
                # Shouldn't happen for well-formed contracts (every dropoff
                # eventually becomes eligible once its pickups are visited),
                # but never hang if it somehow does.
                break

            if current_terminal is not None or current_raw is not None:
                # Tie-break toward drop-off over pickup at equal cost (e.g.
                # two stops at the same real station, "same stop" cost 0) —
                # per user direction, clearing cargo you're already carrying
                # takes priority over loading more while you're standing at
                # a station that needs both. `min` is stable, so without
                # this the winner on a tie was just whichever node happened
                # to come first in `nodes` (pickups are built before
                # drop-offs per contract in `_stop_nodes`, so pickups won
                # every tie by accident, not by design).
                best = min(
                    candidates,
                    key=lambda idx: (
                        self._cost_to_node(contracts, nodes[idx], current_terminal, current_raw),
                        0 if nodes[idx][1] == "dropoff" else 1,
                    ),
                )
            else:
                # No known starting point at all (location never set) — no
                # basis to prefer one node over another for the very first
                # stop, so just take the first eligible one deterministically.
                best = candidates[0]

            visited[best] = True
            order.append(best)
            i, role, _j = nodes[best]
            if role == "pickup":
                pickups_done[i] += 1
            current_terminal = self._node_terminal(contracts, nodes[best])
            current_raw = self._node_raw(contracts, nodes[best])

        route = [nodes[i] for i in order]

        # Alternate 2-opt (segment reversal) and Or-opt (single-stop
        # relocation) until neither improves — 2-opt alone can never merge
        # two non-adjacent visits to the same real terminal (one a pickup
        # for one contract, one a dropoff for another) into a single stop,
        # since that requires moving one node past several others without
        # reversing anything between them, a different move type Or-opt
        # covers. Confirmed real on live data: Everus Harbor got visited
        # twice in one route when only 2-opt ran (see DECISIONS.md,
        # 2026-09-05). Each accepted move in either pass strictly lowers
        # cost, so this converges fast in practice — the round cap is a
        # termination safety net, not expected to bind.
        current = route
        rounds_run = 0
        for rounds_run in range(1, 6):
            after = self._two_opt(contracts, current, start_terminal, start_raw, pickups_needed)
            after = self._or_opt(contracts, after, start_terminal, start_raw, pickups_needed)
            if after == current:
                break
            current = after
        final = current

        if route_debug is not None:
            greedy_cost = self._route_cost(contracts, route, start_terminal, start_raw)
            final_cost = self._route_cost(contracts, final, start_terminal, start_raw)
            route_debug["greedy_order"] = [self._node_label(contracts, node) for node in route]
            route_debug["greedy_cost"] = round(greedy_cost, 1)
            route_debug["final_order"] = [self._node_label(contracts, node) for node in final]
            route_debug["final_cost"] = round(final_cost, 1)
            route_debug["optimized_improved_by"] = round(greedy_cost - final_cost, 1)
            route_debug["rounds_run"] = rounds_run

        return final

    def _node_label(self, contracts: list[dict], node) -> str:
        i, role, _j = node
        terminal = self._node_terminal(contracts, node)
        name = self._locations.display_name(terminal) if terminal else self._node_raw(contracts, node)
        return f"[{role.upper()}] {name} (contract {i})"

    def _route_cost(
        self, contracts: list[dict], seq: list, start_terminal: dict | None, start_raw: str | None
    ) -> float:
        total = 0.0
        prev_terminal, prev_raw = start_terminal, start_raw
        for node in seq:
            term = self._node_terminal(contracts, node)
            raw = self._node_raw(contracts, node)
            if prev_terminal and term:
                total += self.terminal_cost(prev_terminal, term)
            else:
                total += COST_UNRESOLVED + self.text_cost(prev_raw or "", raw)
            prev_terminal, prev_raw = term, raw
        return total

    @staticmethod
    def _respects_precedence(contracts: list[dict], seq: list, pickups_needed: list[int]) -> bool:
        pickups_done = [0] * len(contracts)
        for node in seq:
            i, role, _j = node
            if role == "dropoff":
                if pickups_done[i] < pickups_needed[i]:
                    return False
            else:
                pickups_done[i] += 1
        return True

    def _two_opt(
        self,
        contracts: list[dict],
        seq: list,
        start_terminal: dict | None,
        start_raw: str | None,
        pickups_needed: list[int],
    ) -> list:
        """Standard 2-opt local search over a fixed-start path: repeatedly
        reverse a sub-segment [i:j+1] and keep the reversal if it lowers
        total route cost and doesn't put a drop-off before its own
        contract's pickup. Runs until a full pass finds no improving move.
        Cheap at the stop counts a real scan session produces (a handful
        of contracts, rarely more than ~15-20 stops total) — O(n^2) per
        pass, bounded number of passes since each accepted move strictly
        lowers a bounded integer/float cost."""
        best = list(seq)
        best_cost = self._route_cost(contracts, best, start_terminal, start_raw)
        n = len(best)

        improved = True
        while improved:
            improved = False
            for i in range(n - 1):
                for j in range(i + 1, n):
                    candidate = best[:i] + best[i:j + 1][::-1] + best[j + 1:]
                    if not self._respects_precedence(contracts, candidate, pickups_needed):
                        continue
                    cost = self._route_cost(contracts, candidate, start_terminal, start_raw)
                    if cost < best_cost - 1e-9:
                        best, best_cost = candidate, cost
                        improved = True
        return best

    def _or_opt(
        self,
        contracts: list[dict],
        seq: list,
        start_terminal: dict | None,
        start_raw: str | None,
        pickups_needed: list[int],
    ) -> list:
        """Or-opt local search: repeatedly try relocating a single stop to a
        different position in the route, keeping the move if it lowers total
        cost and doesn't put a drop-off before its own contract's pickup.
        Complements `_two_opt` above, which can only reverse segments — it
        can never merge two non-adjacent visits to the same real terminal
        (once as a pickup for one contract, once as a dropoff for another)
        into one stop, since that means moving one node past several others
        without reversing anything between them. Confirmed real on live data
        (see DECISIONS.md, 2026-09-05): Everus Harbor was visited twice in
        one route, `_two_opt` alone never found the merge. Runs until a full
        pass finds no improving move — same convergence pattern as
        `_two_opt`, same cost bound at real session stop-counts."""
        best = list(seq)
        best_cost = self._route_cost(contracts, best, start_terminal, start_raw)
        n = len(best)

        improved = True
        while improved:
            improved = False
            for i in range(n):
                node = best[i]
                remaining = best[:i] + best[i + 1:]
                # Stop scanning j as soon as `best` changes — `node`/
                # `remaining` were captured from the pre-move sequence, so
                # continuing to build candidates from them after a move
                # would silently discard the just-found improvement instead
                # of building on it. The outer `while improved` loop picks
                # up any further gains in the next full pass, same as
                # `_two_opt`'s own convergence pattern.
                for j in range(len(remaining) + 1):
                    candidate = remaining[:j] + [node] + remaining[j:]
                    if not self._respects_precedence(contracts, candidate, pickups_needed):
                        continue
                    cost = self._route_cost(contracts, candidate, start_terminal, start_raw)
                    if cost < best_cost - 1e-9:
                        best, best_cost = candidate, cost
                        improved = True
                        break
                if improved:
                    break
        return best

    def _cost_to_node(self, contracts: list[dict], node, from_terminal: dict | None, from_raw: str | None) -> float:
        term_b = self._node_terminal(contracts, node)
        if from_terminal and term_b:
            return self.terminal_cost(from_terminal, term_b)
        return COST_UNRESOLVED + self.text_cost(from_raw or "", self._node_raw(contracts, node))

    def terminal_cost(self, a: dict, b: dict) -> float:
        if self._locations.same_physical_place(a, b):
            return COST_SAME_TERMINAL
        distance = self._locations.distance(a, b)
        if distance is not None:
            return distance
        # Real distance unavailable (missing orbit/system data on either
        # side, or the UEX distance endpoints themselves failed) — fall
        # back to the coarse tier, scaled into the same rough numeric
        # range real distances live in (see the COST_* comment above).
        body_keys = ("planet_name", "moon_name", "space_station_name", "city_name", "outpost_name")
        if any(a.get(k) and a.get(k) == b.get(k) for k in body_keys):
            return COST_SAME_BODY
        if a.get("star_system_name") and a.get("star_system_name") == b.get("star_system_name"):
            return COST_SAME_SYSTEM
        return COST_DIFFERENT_SYSTEM

    @staticmethod
    def text_cost(a: str, b: str) -> float:
        if not a or not b:
            return 1.0
        a_low, b_low = a.lower(), b.lower()
        if a_low == b_low:
            return 0.0
        tokens_a = set(re.findall(r"[a-z0-9']+", a_low))
        tokens_b = set(re.findall(r"[a-z0-9']+", b_low))
        return 0.5 if (tokens_a & tokens_b) else 1.0
