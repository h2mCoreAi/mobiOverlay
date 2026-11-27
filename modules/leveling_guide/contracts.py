"""Contract catalog and goal maths for mobiGuide. Pure Python, no Qt.

A pack's contracts.json (built by scripts/build_contract_catalog.py from game
data) lists every contract with its giver, mission type, aUEC reward,
reputation rewards and rank requirement. This module answers:

- which contracts belong to a category (the pack's category -> mission type
  mapping, so new patches remap without code changes),
- which contracts raise a given faction ladder, best first,
- which pay the most aUEC,
- whether the player's known reputation unlocks a contract,
- how many more runs a goal needs.

Sorting and filtering only: no prices or rewards are invented.
"""
from __future__ import annotations

import json
import math
from dataclasses import dataclass, field
from pathlib import Path

CATALOG_SCHEMA = 1


@dataclass
class Category:
    id: str
    title: str
    summary: str = ""
    mission_types: list[str] = field(default_factory=list)
    ships: bool | None = None   # True: only contracts that spawn ships; False: only those that don't
    illegal: bool = False       # True: every illegal contract (plus any listed types)

    def matches(self, contract: dict) -> bool:
        if self.illegal and contract.get("illegal") and not self.mission_types:
            return True
        if contract.get("type") not in self.mission_types:
            return False
        if self.ships is not None and bool(contract.get("ships")) != self.ships:
            return False
        return True


def parse_categories(raw) -> list[Category]:
    out = []
    for c in raw or []:
        if isinstance(c, dict) and c.get("id") and c.get("title"):
            ships = c.get("ships")
            out.append(Category(id=str(c["id"]), title=str(c["title"]), summary=str(c.get("summary") or ""),
                                mission_types=[str(t) for t in c.get("mission_types") or []],
                                ships=ships if isinstance(ships, bool) else None,
                                illegal=bool(c.get("illegal"))))
    return out


def contract_key(c: dict) -> str:
    req = c.get("requires") or {}
    return f"{c.get('title')}|{c.get('giver')}|{req.get('rank', '')}"


@dataclass
class Catalog:
    label: str
    version: str
    ladders: dict
    contracts: list[dict]
    titles: set[str]

    def rank_names(self, ladder: str) -> list[tuple[str, int]]:
        return [(r[0], int(r[1])) for r in (self.ladders.get(ladder) or {}).get("ranks", [])]

    def rank_for(self, ladder: str, points: int) -> str:
        name = ""
        for rank, threshold in self.rank_names(ladder):
            if points >= threshold:
                name = rank
        return name

    def factions_for(self, ladder: str) -> list[str]:
        return sorted({r["faction"] for c in self.contracts for r in c.get("rep", []) if r["ladder"] == ladder})

    def ladders_for(self, faction: str) -> list[str]:
        found = {r["ladder"] for c in self.contracts for r in c.get("rep", []) if r["faction"] == faction}
        return [k for k in self.ladders if k in found]

    def all_factions(self) -> list[str]:
        return sorted({r["faction"] for c in self.contracts for r in c.get("rep", [])})


def load_catalog(path: Path) -> Catalog:
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(data, dict) or data.get("schema", CATALOG_SCHEMA) != CATALOG_SCHEMA:
        raise ValueError("unsupported catalog schema")
    contracts = [c for c in data.get("contracts", []) if isinstance(c, dict) and c.get("title")]
    for c in contracts:
        c.setdefault("rep", [])
        c.setdefault("uec", [0, 0])
        c["key"] = contract_key(c)
    return Catalog(label=str(data.get("label") or ""), version=str(data.get("version") or ""),
                   ladders=data.get("ladders") or {}, contracts=contracts,
                   titles=set(data.get("titles") or [c["title"] for c in contracts]))


# ---------------------------------------------------------------------------
def rep_gain(contract: dict, faction: str, ladder: str) -> int:
    return sum(r["amount"] for r in contract.get("rep", []) if r["faction"] == faction and r["ladder"] == ladder)


def is_unlocked(contract: dict, known_rep: dict[str, int]) -> bool | None:
    """True / False when the player's reputation for the contract's own gate
    is known; None when it isn't (we don't know their rank)."""
    req = contract.get("requires")
    if not req:
        return True
    have = known_rep.get(f"{contract.get('faction')}|{req['ladder']}")
    if have is None:
        return None
    return have >= req["points"]


def _allowed(c: dict, show_unlawful: bool, repeatable_only: bool) -> bool:
    if c.get("illegal") and not show_unlawful:
        return False
    if repeatable_only and not c.get("repeatable", True):
        return False
    return True


def for_reputation(catalog: Catalog, faction: str, ladder: str, known_rep: dict[str, int],
                   show_unlawful: bool = False, category: Category | None = None, limit: int = 8) -> list[dict]:
    """Repeatable contracts that raise `faction`'s `ladder`, unlocked ones
    first, then by reputation per run, then by pay."""
    rows = []
    for c in catalog.contracts:
        gain = rep_gain(c, faction, ladder)
        if gain <= 0 or not _allowed(c, show_unlawful, True):
            continue
        if category is not None and not category.matches(c):
            continue
        rows.append({"contract": c, "gain": gain, "unlocked": is_unlocked(c, known_rep)})
    rows.sort(key=lambda r: (r["unlocked"] is False, -r["gain"], -c_pay(r["contract"]), r["contract"]["title"]))
    return _dedupe(rows)[:limit]


def for_money(catalog: Catalog, known_rep: dict[str, int], show_unlawful: bool = False,
              category: Category | None = None, limit: int = 8) -> list[dict]:
    """Repeatable contracts by aUEC per run: unlocked (or ungated) first."""
    rows = []
    for c in catalog.contracts:
        if c_pay(c) <= 0 or not _allowed(c, show_unlawful, True):
            continue
        if category is not None and not category.matches(c):
            continue
        rows.append({"contract": c, "gain": c_pay(c), "unlocked": is_unlocked(c, known_rep)})
    rows.sort(key=lambda r: (r["unlocked"] is False, r["unlocked"] is None, -r["gain"], r["contract"]["title"]))
    return _dedupe(rows)[:limit]


def in_category(catalog: Catalog, category: Category, known_rep: dict[str, int],
                show_unlawful: bool = False, limit: int = 12) -> list[dict]:
    """A category's repeatable contracts, unlocked first, best paying first."""
    return for_money(catalog, known_rep, show_unlawful, category, limit)


def c_pay(contract: dict) -> int:
    uec = contract.get("uec") or [0, 0]
    return int(uec[1] or uec[0] or 0)


def _dedupe(rows: list[dict]) -> list[dict]:
    seen, out = set(), []
    for r in rows:
        k = (r["contract"]["title"], r["contract"]["giver"])
        if k not in seen:
            seen.add(k)
            out.append(r)
    return out


def runs_needed(remaining: int, per_run: int) -> int:
    if remaining <= 0:
        return 0
    if per_run <= 0:
        raise ValueError("per_run must be positive")
    return math.ceil(remaining / per_run)


def fmt_uec(contract: dict) -> str:
    lo, hi = (contract.get("uec") or [0, 0])[:2]
    if not hi:
        return ""
    return f"{lo:,} aUEC" if lo == hi or not lo else f"{lo:,}-{hi:,} aUEC"
