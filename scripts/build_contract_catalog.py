"""Build mobiGuide's contract catalog from an SCMDB data file.

SCMDB (https://scmdb.net) publishes contract data read from the game files,
one file per game build (live and PTU). This script reduces one of those
files to what the Goals view needs: each contract's giver, type, systems,
legality, aUEC reward, reputation rewards and rank requirement.

    python scripts/build_contract_catalog.py --list
    python scripts/build_contract_catalog.py 4.10.3-live.13220821 --label "4.10.3 LIVE"
    python scripts/build_contract_catalog.py 5.0.0-ptu.13284307 --label "5.0 PTU"
    python scripts/build_contract_catalog.py path/to/merged-x.json --label "..."

Output: <pack>/contracts.json with --pack modules/leveling_guide/packs/<id>
(default: the current directory). Re-run it when a patch lands, then run
scripts/check_pack.py on the pack.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
import urllib.request
from collections import defaultdict
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SCMDB = "https://scmdb.net/data"
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
# gate in the title, not in minStanding.
_TITLE_RANK = re.compile(r"^(?:[A-Z ]+ - )?(Trainee|Rookie|Junior|Member|Experienced|Senior|Master) Rank\b")


def _get_json(url: str):
    req = urllib.request.Request(url, headers=HEADERS)
    with urllib.request.urlopen(req, timeout=180) as r:
        return json.loads(r.read().decode("utf-8"))


def load_source(arg: str) -> dict:
    path = Path(arg)
    if path.exists():
        return json.loads(path.read_text(encoding="utf-8"))
    return _get_json(f"{SCMDB}/merged-{arg}.json")


def _clean(text) -> str:
    text = re.sub(r"\s+", " ", str(text or "")).strip()
    # SCMDB writes the target token as [TARGET]; the game and the wiki show
    # [TargetName]. Use one spelling so guide references match.
    return text.replace("[TARGET]", "[TargetName]")


def _placeholder(text: str) -> bool:
    return not text or bool(_PLACEHOLDER.search(text))


def build(data: dict, label: str) -> dict:
    factions = data.get("factions", {})
    scopes = data.get("scopes", {})
    pools = data.get("factionRewardsPools", [])

    ladders = {}
    for sc in scopes.values():
        key = sc.get("scopeName")
        if key in LADDER_NAMES:
            ladders[key] = {
                "name": LADDER_NAMES[key],
                "ranks": [[_clean(r.get("name")), int(r.get("minReputation") or 0)] for r in sc.get("ranks", [])],
            }

    merged: dict[tuple, dict] = {}
    all_titles: set[str] = set()
    # SCMDB splits contracts into the newer contract-generator list and the
    # older mission-broker list ("legacyContracts"). Both are offered in game;
    # the rank-titled hauls ("Junior Rank - Small Cargo Haul") are legacy ones.
    sources = [(c, False) for c in data.get("contracts", [])]
    sources += [(c, True) for c in data.get("legacyContracts", [])]
    for c, legacy in sources:
        title = _clean(c.get("title"))
        giver = _clean(c.get("contractorName")) or factions.get(c.get("factionGuid"), {}).get("name", "")
        if not _placeholder(title):
            all_titles.add(title)
        if c.get("hideInMobiGlas") or _placeholder(title) or _placeholder(giver):
            continue
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
        cap = c.get("maxStanding") or {}
        requires = None
        if gate.get("scopeName") in LADDER_NAMES and int(gate.get("minReputation") or 0) > 0:
            requires = {"ladder": gate["scopeName"], "rank": _clean(gate.get("name")),
                        "points": int(gate.get("minReputation") or 0)}
        if requires is None:
            m = _TITLE_RANK.match(title)
            hauling = ladders.get("Hauling", {}).get("ranks", [])
            points = next((pts for name, pts in hauling if name == (m.group(1) if m else None)), None)
            if m and points:
                requires = {"ladder": "Hauling", "rank": m.group(1), "points": points, "from_title": True}
        uec = int(c.get("rewardUEC") or 0)
        key = (title, giver, json.dumps(requires, sort_keys=True), json.dumps(sorted(
            (r["faction"], r["ladder"], r["amount"]) for r in rewards)))
        entry = merged.get(key)
        if entry is None:
            fac_guid = c.get("factionGuid")
            entry = merged[key] = {
                "title": title,
                "giver": giver,
                "faction": factions.get(fac_guid, {}).get("name") or giver,
                "type": _clean(c.get("missionType")),
                "category": c.get("category") or ("legacy" if legacy else ""),
                "systems": set(),
                "illegal": bool(c.get("illegal")),
                "repeatable": not c.get("onceOnly"),
                "shareable": bool(c.get("canBeShared")),
                "uec": [uec, uec] if uec else [0, 0],
                "rep": rewards,
                "requires": requires,
                "max_rank": _clean(cap.get("name")) or None,
                "buy_in": int(c.get("buyIn") or 0) or None,
                # Spawns ship encounters: how packs tell ship combat from
                # on-foot (FPS) work within one mission type.
                "ships": bool(((c.get("shipEncounters") or {}).get("spawnConfig") or {}).get("groups")),
                "variants": 0,
            }
        entry["variants"] += 1
        entry["systems"].update(c.get("systems") or c.get("availableSystems") or [])
        entry["repeatable"] = entry["repeatable"] or not c.get("onceOnly")
        if uec:
            lo, hi = entry["uec"]
            entry["uec"] = [min(lo, uec) if lo else uec, max(hi, uec)]

    titles = sorted(all_titles)
    contracts = []
    for e in merged.values():
        if not e["rep"] and not e["uec"][1]:
            continue  # nothing to work toward
        e["systems"] = sorted(e["systems"])
        contracts.append(e)
    contracts.sort(key=lambda e: (e["faction"], e["title"]))
    return {
        "schema": 1,
        "label": label,
        "version": data.get("version", ""),
        "source": "SCMDB (scmdb.net), read from the game files",
        "built": date.today().isoformat(),
        "ladders": ladders,
        # Every contract title in this build, including ones with no reward
        # (tutorials): what scripts/check_pack.py checks guide references
        # against.
        "titles": titles,
        "contracts": contracts,
    }


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("source", nargs="?", help="SCMDB version (e.g. 5.0.0-ptu.13284307) or a merged-*.json path")
    ap.add_argument("--label", help="Name shown in the card, e.g. '5.0 PTU'")
    ap.add_argument("--list", action="store_true", help="List the versions SCMDB has")
    ap.add_argument("--pack", default=".", help="Pack folder to write contracts.json into")
    args = ap.parse_args(argv)
    if args.list or not args.source:
        for v in _get_json(f"{SCMDB}/versions.json"):
            print(v.get("version"))
        return 0
    data = load_source(args.source)
    version = data.get("version") or args.source
    catalog = build(data, args.label or version)
    out = Path(args.pack) / "contracts.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(catalog, indent=1, ensure_ascii=False) + "\n", encoding="utf-8")
    by_type = defaultdict(int)
    for c in catalog["contracts"]:
        by_type[c["type"]] += 1
    print(f"{out}: {len(catalog['contracts'])} contracts, "
          f"{sum(1 for c in catalog['contracts'] if c['repeatable'])} repeatable")
    for t, n in sorted(by_type.items(), key=lambda kv: -kv[1])[:12]:
        print(f"  {n:4} {t}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
