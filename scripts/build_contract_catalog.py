"""Build mobiGuide's contract catalog from game data, cross-checked across sources.

Sources (both read from the game files):
- SCMDB (https://scmdb.net): one file per build, live and PTU. Primary source:
  mission types, ship encounters, ladders.
- star-citizen.wiki API (https://api.star-citizen.wiki): live builds only.
  Joined on the game's internal contract name (debug name). It fills gates and
  reputation SCMDB lacks, adds contracts SCMDB doesn't carry, and flags
  disagreements.

Every contract records which sources back it ("sources") and any
disagreement ("conflicts"); the catalog carries agreement statistics
("cross_check").

    python scripts/build_contract_catalog.py --list
    python scripts/build_contract_catalog.py 4.10.3-live.13220821 --label "4.10.3 (live)" --pack modules/leveling_guide/packs/4.10.3-live
    python scripts/build_contract_catalog.py 5.0.0-ptu.13284307 --label "5.0 (PTU)" --pack modules/leveling_guide/packs/5.0-ptu
    python scripts/build_contract_catalog.py path/to/merged-x.json --wiki path/to/wiki-missions.json ...

--wiki auto (default) uses the wiki's live build for the same patch, if it
has one; --wiki off skips it; --wiki <file> uses a saved /api/missions dump.

--previous <contracts.json> compares against the last patch's catalog (for a
PTU build the wiki can't check): a contract whose title, giver, gate and
reputation are unchanged is marked as backed by that catalog's sources too,
and a gate missing now but present before is carried over, marked as such.
Then run scripts/check_pack.py on the pack.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
import time
import urllib.request
from collections import Counter, defaultdict
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SCMDB = "https://scmdb.net/data"
WIKI = "https://api.star-citizen.wiki/api"
HEADERS = {"User-Agent": "Mozilla/5.0 mobiOverlay-catalog", "Accept": "application/json"}

# Scopes worth tracking as goals, and the name the guide uses for each.
LADDER_NAMES = {
    "FactionReputation": "Standing",
    "Hauling": "Hauling",
    "BountyHunter_BountyHuntersGuild": "Bounty Hunters Guild rank",
    "BountyHunter": "Bounty Hunting career",
    "Security": "Security career",
    "MissionProviderReputation_Battaglia": "Recco Battaglia",
    "Wikelo": "Wikelo customer level",
    "Guild": "Guild rank",
}
_PLACEHOLDER = re.compile(r"^\s*(@|~|<=|\[PH\])|UNINITIALIZED|PLACEHOLDER", re.I)
# Older rank-titled hauls ("Junior Rank - Small Cargo Haul") carry their rank
# gate in the title, not in the data.
_TITLE_RANK = re.compile(r"^(?:[A-Z ]+ - )?(Trainee|Rookie|Junior|Member|Experienced|Senior|Master) Rank\b")
# Wiki records don't carry SCMDB's mission type: infer it for contracts only
# the wiki has (marked type_inferred). First match wins.
_TYPE_RULES = [
    (re.compile(r"bounty|\((?:VLRT|LRT|MRT|HRT|VHRT|ERT)\)|tracker|warrant", re.I), "Bounty Hunter"),
    (re.compile(r"salvage", re.I), "Salvage"),
    (re.compile(r"refuel", re.I), "Refueling"),
    (re.compile(r"repair|maintenance|technician", re.I), "Maintenance"),
    (re.compile(r"handmin|hand.?mined", re.I), "Hand Mining"),
    (re.compile(r"vehicle.?min|roc", re.I), "Ground Vehicle Mining"),
    (re.compile(r"mining|mined|ore\b|scan", re.I), "Ship Mining"),
    (re.compile(r"haulcargo|cargo haul|hauler", re.I), "Hauling"),
    (re.compile(r"deliver|courier|package", re.I), "Delivery"),
    (re.compile(r"blackbox|black box|missing|locate|investigat|recover", re.I), "Investigation"),
    (re.compile(r"collect|wikelo", re.I), "Collection"),
    (re.compile(r"assassin|eliminat|kill|defend|escort|patrol|clear|attack|destroy|ambush|raid|neutrali|protect", re.I), "Mercenary"),
]
_SHIPS = re.compile(r"ship|space|fleet|blockade|escort|intercept|dogfight|killship|vlrt|lrt|mrt|hrt|ert", re.I)


def _get_json(url: str):
    req = urllib.request.Request(url, headers=HEADERS)
    with urllib.request.urlopen(req, timeout=180) as r:
        return json.loads(r.read().decode("utf-8"))


def load_scmdb(arg: str) -> dict:
    path = Path(arg)
    if path.exists():
        return json.loads(path.read_text(encoding="utf-8"))
    return _get_json(f"{SCMDB}/merged-{arg}.json")


def load_wiki(arg: str, patch: str, channel: str) -> tuple[list[dict], str]:
    """(missions, version code) or ([], reason) when there's nothing to use."""
    if arg == "off":
        return [], "skipped"
    path = Path(arg)
    if arg != "auto" and path.exists():
        data = json.loads(path.read_text(encoding="utf-8"))
        missions = data if isinstance(data, list) else data.get("data", [])
        return missions, (missions[0].get("version", "file") if missions else "file")
    if channel != "live":
        return [], "the wiki API only has live builds"
    versions = _get_json(f"{WIKI}/game-versions").get("data", [])
    match = [v["code"] for v in versions if v.get("code", "").startswith(patch + "-")]
    if not match:
        return [], f"no wiki data for {patch}"
    code = match[0]
    missions, page = [], 1
    while True:
        d = _get_json(f"{WIKI}/missions?version={code}&page%5Bsize%5D=200&page%5Bnumber%5D={page}")
        missions += d.get("data", [])
        if page >= d.get("meta", {}).get("last_page", 1):
            break
        page += 1
        time.sleep(0.5)
    return missions, code


def _clean(text) -> str:
    text = re.sub(r"\s+", " ", str(text or "")).strip()
    # SCMDB writes the target token as [TARGET]; the game and the wiki show
    # [TargetName]. Use one spelling so guide references match.
    return text.replace("[TARGET]", "[TargetName]")


def _placeholder(text: str) -> bool:
    return not text or bool(_PLACEHOLDER.search(text))


def _ladder_for(name: str, points: int, ladders: dict) -> str | None:
    """Which ladder a (rank name, points) gate belongs to: the wiki's gates
    don't name their scope."""
    for key, lad in ladders.items():
        if [name, points] in lad["ranks"]:
            return key
    return None


def _rows_from_scmdb(data: dict, ladders: dict) -> list[dict]:
    factions, scopes, pools = data.get("factions", {}), data.get("scopes", {}), data.get("factionRewardsPools", [])
    rows = []
    for c in data.get("contracts", []) + data.get("legacyContracts", []):
        rewards = []
        idx = c.get("factionRewardsIndex")
        if isinstance(idx, int) and 0 <= idx < len(pools):
            for r in pools[idx]:
                scope = scopes.get(r.get("scopeGuid"), {}).get("scopeName")
                fac = factions.get(r.get("factionGuid"), {}).get("name")
                amount = int(r.get("amount") or 0)
                if scope in LADDER_NAMES and fac and not _placeholder(fac) and amount:
                    rewards.append({"faction": fac, "ladder": scope, "amount": amount})
        gate = c.get("minStanding") or {}
        requires = None
        if gate.get("scopeName") in LADDER_NAMES and int(gate.get("minReputation") or 0) > 0:
            requires = {"ladder": gate["scopeName"], "rank": _clean(gate.get("name")),
                        "points": int(gate.get("minReputation") or 0)}
        giver = _clean(c.get("contractorName")) or factions.get(c.get("factionGuid"), {}).get("name", "")
        rows.append({
            "debug": c.get("debugName") or "",
            "title": _clean(c.get("title")),
            "giver": giver,
            "faction": factions.get(c.get("factionGuid"), {}).get("name") or giver,
            "type": _clean(c.get("missionType")),
            "systems": list(c.get("systems") or c.get("availableSystems") or []),
            "illegal": bool(c.get("illegal")),
            "once": bool(c.get("onceOnly")),
            "shareable": bool(c.get("canBeShared")),
            "uec": int(c.get("rewardUEC") or 0),
            "rep": rewards,
            "requires": requires,
            "max_rank": _clean((c.get("maxStanding") or {}).get("name")) or None,
            "buy_in": int(c.get("buyIn") or 0) or None,
            "ships": bool(((c.get("shipEncounters") or {}).get("spawnConfig") or {}).get("groups")),
            "hidden": bool(c.get("hideInMobiGlas")),
            "sources": {"SCMDB"},
            "conflicts": [],
            "type_inferred": False,
        })
    return rows


def _wiki_view(m: dict, ladders: dict) -> dict:
    gate = m.get("min_standing") or {}
    requires = None
    points = gate.get("min_reputation")
    if isinstance(points, int) and points > 0:
        ladder = _ladder_for(_clean(gate.get("name")), points, ladders)
        if ladder:
            requires = {"ladder": ladder, "rank": _clean(gate.get("name")), "points": points}
    rep = [{"faction": g["faction"], "ladder": g["scope"], "amount": int(g["amount"])}
           for g in (m.get("reputation_gained") or []) if g.get("scope") in LADDER_NAMES and g.get("amount")]
    systems = [s if isinstance(s, str) else s.get("name") for s in (m.get("star_systems") or [])]
    return {"requires": requires, "rep": rep, "uec": int(m.get("reward_min") or 0),
            "systems": [s for s in systems if s], "illegal": bool(m.get("illegal")),
            "once": bool(m.get("once_only")), "shareable": bool(m.get("shareable"))}


def _infer_type(m: dict) -> tuple[str, bool]:
    text = f"{m.get('debug_name') or ''} {m.get('title') or ''}"
    kind = next((t for rx, t in _TYPE_RULES if rx.search(text)), "Other")
    return kind, bool(_SHIPS.search(text)) if kind in ("Mercenary", "Bounty Hunter") else False


def cross_check(rows: list[dict], wiki: list[dict], ladders: dict) -> tuple[list[dict], Counter]:
    """Fill gaps from the wiki, record disagreements, add wiki-only contracts."""
    stats = Counter()
    by_debug = {}
    for m in wiki:
        if m.get("debug_name") and m.get("released") and not m.get("not_for_release"):
            by_debug.setdefault(m["debug_name"], m)
    seen = set()
    for row in rows:
        m = by_debug.get(row["debug"])
        if m is None:
            continue
        seen.add(row["debug"])
        stats["matched"] += 1
        row["sources"].add("star-citizen.wiki")
        w = _wiki_view(m, ladders)
        if row["requires"] is None and w["requires"] is not None:
            row["requires"] = dict(w["requires"], source="star-citizen.wiki")
            stats["gate_filled_from_wiki"] += 1
        elif row["requires"] and w["requires"] and row["requires"]["points"] != w["requires"]["points"]:
            row["conflicts"].append(f"rank gate: SCMDB {row['requires']['rank']}, wiki {w['requires']['rank']}")
            stats["gate_conflicts"] += 1
        elif (row["requires"] is None) == (w["requires"] is None):
            stats["gate_agree"] += 1
        else:
            stats["gate_only_scmdb"] += 1
        mine = sorted((r["faction"], r["ladder"], r["amount"]) for r in row["rep"])
        theirs = sorted((r["faction"], r["ladder"], r["amount"]) for r in w["rep"])
        if not mine and theirs:
            row["rep"] = w["rep"]
            stats["rep_filled_from_wiki"] += 1
        elif mine == theirs:
            stats["rep_agree"] += 1
        elif theirs:
            row["conflicts"].append("reputation: sources differ (kept SCMDB)")
            stats["rep_conflicts"] += 1
        if not row["uec"] and w["uec"]:
            row["uec"] = w["uec"]
    for dn, m in by_debug.items():
        if dn in seen:
            continue
        w = _wiki_view(m, ladders)
        kind, ships = _infer_type(m)
        rows.append({
            "debug": dn, "title": _clean(m.get("title")), "giver": _clean(m.get("mission_giver")),
            "faction": _clean((m.get("faction") or {}).get("name")) or _clean(m.get("mission_giver")),
            "type": kind, "systems": w["systems"], "illegal": w["illegal"], "once": w["once"],
            "shareable": w["shareable"], "uec": w["uec"], "rep": w["rep"], "requires": w["requires"],
            "max_rank": _clean((m.get("max_standing") or {}).get("name")) or None,
            "buy_in": int(m.get("cost") or 0) or None, "ships": ships, "hidden": False,
            "sources": {"star-citizen.wiki"}, "conflicts": [], "type_inferred": True,
        })
        stats["added_from_wiki"] += 1
    return rows, stats


def carry_from_previous(contracts: list[dict], previous: dict, stats: Counter) -> None:
    prev_label = previous.get("label") or previous.get("version") or "previous patch"
    by_key = {(c["title"], c["giver"]): c for c in previous.get("contracts", [])}
    for c in contracts:
        old = by_key.get((c["title"], c["giver"]))
        if old is None:
            stats["new_since_previous"] += 1
            continue
        same_rep = sorted((r["faction"], r["ladder"], r["amount"]) for r in c["rep"]) == \
            sorted((r["faction"], r["ladder"], r["amount"]) for r in old.get("rep", []))
        old_req, new_req = old.get("requires"), c.get("requires")
        if new_req is None and old_req is not None:
            c["requires"] = dict(old_req, source=f"carried over from {prev_label}")
            stats["gate_carried_over"] += 1
            new_req = c["requires"]
        same_gate = (old_req or {}).get("points") == (new_req or {}).get("points")
        if same_rep and same_gate:
            stats["unchanged_since_previous"] += 1
            if len(old.get("sources", [])) > 1:
                c["sources"] = sorted(set(c["sources"]) | {f"{prev_label} (cross-checked)"})
        else:
            stats["changed_since_previous"] += 1


def build(data: dict, label: str, wiki: list[dict] | None = None, wiki_version: str = "",
          previous: dict | None = None) -> dict:
    scopes = data.get("scopes", {})
    ladders = {}
    for sc in scopes.values():
        key = sc.get("scopeName")
        if key in LADDER_NAMES:
            ladders[key] = {"name": LADDER_NAMES[key],
                            "ranks": [[_clean(r.get("name")), int(r.get("minReputation") or 0)] for r in sc.get("ranks", [])]}

    rows = _rows_from_scmdb(data, ladders)
    stats = Counter()
    if wiki:
        rows, stats = cross_check(rows, wiki, ladders)

    hauling = ladders.get("Hauling", {}).get("ranks", [])
    merged: dict[tuple, dict] = {}
    all_titles: set[str] = set()
    for row in rows:
        title, giver = row["title"], row["giver"]
        if not _placeholder(title):
            all_titles.add(title)
        if row["hidden"] or _placeholder(title) or _placeholder(giver):
            continue
        requires = row["requires"]
        if requires is None:
            m = _TITLE_RANK.match(title)
            points = next((pts for name, pts in hauling if m and name == m.group(1)), None)
            if m and points:
                requires = {"ladder": "Hauling", "rank": m.group(1), "points": points, "from_title": True}
        key = (title, giver, json.dumps(requires, sort_keys=True),
               json.dumps(sorted((r["faction"], r["ladder"], r["amount"]) for r in row["rep"])))
        entry = merged.get(key)
        if entry is None:
            entry = merged[key] = {
                "title": title, "giver": giver, "faction": row["faction"], "type": row["type"],
                "systems": set(), "illegal": row["illegal"], "repeatable": not row["once"],
                "shareable": row["shareable"], "uec": [0, 0], "rep": row["rep"], "requires": requires,
                "max_rank": row["max_rank"], "buy_in": row["buy_in"],
                # Spawns ship encounters: how packs tell ship combat from on-foot
                # (FPS) work within one mission type.
                "ships": row["ships"], "sources": set(), "conflicts": [], "type_inferred": row["type_inferred"],
                "variants": 0,
            }
        entry["variants"] += 1
        entry["systems"].update(row["systems"])
        entry["sources"].update(row["sources"])
        entry["conflicts"] += [c for c in row["conflicts"] if c not in entry["conflicts"]]
        entry["repeatable"] = entry["repeatable"] or not row["once"]
        uec = row["uec"]
        if uec:
            lo, hi = entry["uec"]
            entry["uec"] = [min(lo, uec) if lo else uec, max(hi, uec)]

    contracts = []
    for e in merged.values():
        if not e["rep"] and not e["uec"][1]:
            continue  # nothing to work toward
        e["systems"] = sorted(e["systems"])
        e["sources"] = sorted(e["sources"])
        if not e["conflicts"]:
            del e["conflicts"]
        if not e["type_inferred"]:
            del e["type_inferred"]
        contracts.append(e)
    contracts.sort(key=lambda e: (e["faction"], e["title"]))
    if previous:
        carry_from_previous(contracts, previous, stats)
    both = sum(1 for c in contracts if len(c["sources"]) > 1)
    return {
        "schema": 1,
        "label": label,
        "version": data.get("version", ""),
        "source": "SCMDB (scmdb.net)" + (f" cross-checked with star-citizen.wiki {wiki_version}" if wiki else ""),
        "built": date.today().isoformat(),
        "cross_check": dict(stats, contracts_backed_by_two_sources=both,
                            wiki=wiki_version or "not available"),
        "ladders": ladders,
        # Every contract title in this build, including ones with no reward
        # (tutorials): what scripts/check_pack.py checks guide references against.
        "titles": sorted(all_titles),
        "contracts": contracts,
    }


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("source", nargs="?", help="SCMDB version (e.g. 5.0.0-ptu.13284307) or a merged-*.json path")
    ap.add_argument("--label", help="Name shown in the card, e.g. '5.0 (PTU)'")
    ap.add_argument("--list", action="store_true", help="List the versions SCMDB has")
    ap.add_argument("--pack", default=".", help="Pack folder to write contracts.json into")
    ap.add_argument("--wiki", default="auto", help="auto | off | path to a saved wiki /api/missions dump")
    ap.add_argument("--previous", help="the last patch's contracts.json, to compare and carry gates over")
    args = ap.parse_args(argv)
    if args.list or not args.source:
        for v in _get_json(f"{SCMDB}/versions.json"):
            print(v.get("version"))
        return 0
    data = load_scmdb(args.source)
    version = data.get("version") or args.source
    m = re.match(r"(\d+\.\d+\.\d+)-(\w+)", version, re.I)
    patch, channel = (m.group(1), m.group(2).lower()) if m else ("", "")
    wiki, wiki_version = load_wiki(args.wiki, patch, channel)
    previous = json.loads(Path(args.previous).read_text(encoding="utf-8")) if args.previous else None
    catalog = build(data, args.label or version, wiki, wiki_version if wiki else "", previous)
    if not wiki:
        catalog["cross_check"]["wiki"] = wiki_version
    out = Path(args.pack) / "contracts.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(catalog, indent=1, ensure_ascii=False) + "\n", encoding="utf-8")
    by_type = defaultdict(int)
    for c in catalog["contracts"]:
        by_type[c["type"]] += 1
    print(f"{out}: {len(catalog['contracts'])} contracts, "
          f"{sum(1 for c in catalog['contracts'] if c['repeatable'])} repeatable")
    print("  cross-check:", json.dumps(catalog["cross_check"]))
    for t, n in sorted(by_type.items(), key=lambda kv: -kv[1])[:12]:
        print(f"  {n:4} {t}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
