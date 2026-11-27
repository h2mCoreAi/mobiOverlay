"""Check a patch pack against its own game data. Pure Python, no Qt.

Used by scripts/check_pack.py (before shipping a pack) and by the tests (so a
bundled pack that drifts from its data fails the build).

For the active pack, with everything it extends:
- the content loads without errors;
- every category a chapter or objective names exists;
- every contract an objective names is in the pack's catalog;
- every rank-up objective's points match the game's ladder for that rank.

Objectives first checked on an older patch are "reconfirmed" for this one
when the new data backs everything they name; the rest are flagged in the
card as checked on their older patch.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from . import contracts as contracts_mod
from . import guide as guide_mod


@dataclass
class PackReport:
    pack_id: str
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    reconfirm: list[str] = field(default_factory=list)
    stale: list[str] = field(default_factory=list)   # inherited, not backed by this pack's data

    @property
    def ok(self) -> bool:
        return not self.errors


def _ladder_points(catalog, ladder: str, rank: str) -> int | None:
    for name, points in catalog.rank_names(ladder):
        if name == rank:
            return points
    return None


def check_pack(pack_id: str, roots: list[Path]) -> PackReport:
    guide = guide_mod.load_pack(pack_id, roots, catalog_loader=contracts_mod.load_catalog)
    report = PackReport(pack_id=pack_id)
    report.errors += guide.errors
    pack, catalog = guide.pack, guide.catalog
    if pack is None:
        report.errors.append(f"pack {pack_id!r} not found")
        return report
    category_ids = {c.get("id") for c in guide.categories}
    # Only the active pack's own second-source confirmations count: an older
    # pack's confirmations don't carry to a newer patch.
    extra_titles = {x["title"] for x in pack.also_confirmed}
    for chapter in guide.chapters:
        for cid in chapter.categories:
            if cid not in category_ids:
                report.errors.append(f"chapter {chapter.id}: unknown category {cid!r}")
    for obj in guide.objectives:
        own = obj.verified_patch == pack.patch
        problems = []
        for cid in obj.categories:
            if cid not in category_ids:
                report.errors.append(f"[{obj.id}]: unknown category {cid!r}")
        if catalog is not None:
            for title in obj.contracts:
                if title not in catalog.titles and title not in extra_titles:
                    problems.append(f"names contract {title!r}, not in this pack's data")
            rep = obj.reputation
            if rep and isinstance(rep.get("points"), int):
                game = _ladder_points(catalog, rep.get("ladder", ""), rep.get("rank", ""))
                if game is not None and game != rep["points"]:
                    problems.append(f"{rep['rank']} is {game:,} in the game data, not {rep['points']:,}")
        if own:
            report.errors += [f"[{obj.id}]: {p}" for p in problems]
        elif problems:
            report.stale.append(obj.id)
            report.warnings += [f"[{obj.id}] (from {obj.verified_patch}): {p}" for p in problems]
        elif obj.contracts or obj.reputation:
            report.reconfirm.append(obj.id)
        else:
            report.stale.append(obj.id)
    if catalog is None:
        report.warnings.append("no contracts.json in this pack or anything it extends")
    return report
