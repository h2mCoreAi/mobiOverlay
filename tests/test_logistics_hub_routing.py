"""Unit tests for Logistics Hub route ordering (modules/logistics_hub/routing.py).

No Qt, no network — a fake location service with deterministic distances.
    python tests/test_logistics_hub_routing.py
"""
import importlib.util
import random
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
_spec = importlib.util.spec_from_file_location("lh_routing", ROOT / "modules" / "logistics_hub" / "routing.py")
routing = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(routing)


class FakeLoc:
    def display_name(self, t):
        return t["name"]

    def same_physical_place(self, a, b):
        return a["id"] == b["id"]

    def distance(self, a, b):
        if a["id"] == b["id"]:
            return 0.0
        return float(abs(a["id"] * 13 - b["id"] * 7) % 97 + 1)


TERMS = [{"id": i, "name": f"T{i}"} for i in range(10)]


def _contract(rng):
    def e():
        t = rng.choice(TERMS)
        return {"terminal": t, "raw": t["name"]}
    return {"pickups": [e() for _ in range(rng.randint(1, 3))],
            "dropoffs": [e() for _ in range(rng.randint(1, 3))]}


def test_every_stop_visited_once_and_precedence_holds() -> int:
    rng = random.Random(1)
    planner = routing.RoutePlanner(FakeLoc())
    for _ in range(60):
        contracts = [_contract(rng) for _ in range(rng.randint(1, 4))]
        route = planner.plan_route(contracts, rng.choice(TERMS))
        assert sorted(route) == sorted(planner._stop_nodes(contracts)), "a stop was dropped or duplicated"
        needed = [len(c["pickups"]) for c in contracts]
        assert planner._respects_precedence(contracts, route, needed), "a drop-off precedes its pickups"
    return 2


def test_optimized_cost_never_worse_than_greedy() -> int:
    rng = random.Random(2)
    planner = routing.RoutePlanner(FakeLoc())
    for _ in range(60):
        contracts = [_contract(rng) for _ in range(rng.randint(1, 4))]
        start = rng.choice(TERMS)
        debug = {}
        planner.plan_route(contracts, start, route_debug=debug)
        assert debug["optimized_improved_by"] >= -1e-9, debug
    return 1


def test_no_stops_gives_empty_route() -> int:
    assert routing.RoutePlanner(FakeLoc()).plan_route([], None) == []
    return 1


def test_text_cost_tiers() -> int:
    tc = routing.RoutePlanner.text_cost
    assert tc("", "x") == 1.0 and tc("Port Olisar", "port olisar") == 0.0
    assert tc("Port Olisar", "Port Tressler") == 0.5 and tc("Lorville", "Area18") == 1.0
    return 3


def run() -> int:
    checks = 0
    for t in (test_every_stop_visited_once_and_precedence_holds,
              test_optimized_cost_never_worse_than_greedy,
              test_no_stops_gives_empty_route, test_text_cost_tiers):
        checks += t()
        print(f"[PASS] {t.__name__}")
    print(f"\n{checks}/{checks} routing checks passed")
    return checks


if __name__ == "__main__":
    run()
