"""Leveling Guide content: load, validate and order the guide's chapters and
objectives. Pure Python, no Qt, so tests can exercise it directly.

Content is organised in **patch packs**, one folder per game version:

    packs/<pack-id>/pack.json        manifest (id, label, patch, channel, extends)
    packs/<pack-id>/chapters/*.json  one chapter per file
    packs/<pack-id>/contracts.json   contract catalog (scripts/build_contract_catalog.py)

A pack can `extend` another: it inherits the base pack's chapters, adds its
own, replaces any objective by reusing its id, and drops objectives listed in
`remove`. A new patch is a new folder; nothing in code changes. Packs are
found in the bundled packs/ folder and in app_root()/leveling_guide/packs/.

On top of the active pack, two more layers load:
- user:    app_root()/leveling_guide/*.json (drop-in chapter files, or files
           that add objectives to an existing chapter id)
- custom:  app_root()/leveling_guide_custom.json (objectives added from the
           card's "+ ADD" dialog)

A bad file or objective is skipped and reported in `Guide.errors`; it never
stops the rest of the guide from loading. See docs/modules/leveling-guide.md
for the schema.
"""
from __future__ import annotations

import json
import math
from dataclasses import dataclass, field
from pathlib import Path

SCHEMA_VERSION = 1
KINDS = ("task", "rank", "grind", "purchase")
# Categories that the setup "focus" filter never hides.
ALWAYS_SHOWN_CATEGORIES = {"getting-started"}
# Tag on the objectives a player who already knows how to play can skip.
BASICS_TAG = "basics"
PACK_SCHEMA_VERSION = 1
CUSTOM_CHAPTER_ID = "my-objectives"
CUSTOM_CHAPTER_TITLE = "My Objectives"

_XP_BY_KIND = {"task": 100, "rank": 150, "purchase": 200}


@dataclass
class Step:
    do: str
    done_when: str
    where: str = ""


@dataclass
class Objective:
    id: str
    title: str
    kind: str
    chapter_id: str
    steps: list[Step]
    why: str = ""
    tags: list[str] = field(default_factory=list)
    optional: bool = False
    goal_target: int = 0
    goal_unit: str = ""
    reputation: dict | None = None
    reward: str = ""
    cost: str = ""
    ship: dict | None = None
    requires: list[str] = field(default_factory=list)
    sources: list[str] = field(default_factory=list)
    tips: str = ""
    custom: bool = False
    contracts: list[str] = field(default_factory=list)   # contract titles it names
    verified_patch: str = ""                              # patch its facts were checked on
    categories: list[str] = field(default_factory=list)  # from its chapter unless it sets its own

    @property
    def xp(self) -> int:
        if self.kind == "grind":
            return 100 + 10 * min(self.goal_target, 50)
        return _XP_BY_KIND.get(self.kind, 100)

    @property
    def unlawful(self) -> bool:
        return "unlawful" in self.tags


@dataclass
class Chapter:
    id: str
    title: str
    order: int
    summary: str = ""
    patch: str = ""
    objectives: list[Objective] = field(default_factory=list)
    categories: list[str] = field(default_factory=list)


@dataclass
class Pack:
    id: str
    label: str
    patch: str
    channel: str = "live"
    game_version: str = ""
    extends: str = ""
    remove: list[str] = field(default_factory=list)
    reconfirmed: list[str] = field(default_factory=list)
    notes: str = ""
    path: Path | None = None
    categories: list = field(default_factory=list)   # raw category dicts; see contracts.parse_categories
    categories_add: list = field(default_factory=list)  # added on top of inherited categories
    # Contracts confirmed by a second source when the catalog's source lacks
    # them: [{"title": ..., "source": url}]. Checked like catalog titles.
    also_confirmed: list = field(default_factory=list)

    @property
    def has_catalog(self) -> bool:
        return bool(self.path and (self.path / "contracts.json").is_file())


@dataclass
class Guide:
    chapters: list[Chapter]
    errors: list[str]
    pack: Pack | None = None
    catalog: object | None = None   # contracts.Catalog, kept untyped so guide.py stays standalone
    categories: list = field(default_factory=list)   # raw category dicts from the pack chain

    def chapters_in(self, category_id: str | None) -> list[Chapter]:
        if not category_id:
            return list(self.chapters)
        return [c for c in self.chapters if category_id in c.categories
                or any(category_id in o.categories for o in c.objectives)]

    def is_verified(self, obj: Objective) -> bool:
        """Were this objective's facts checked for the active pack's patch?
        Your own objectives and pack-less guides count as verified."""
        if self.pack is None or obj.custom:
            return True
        return obj.verified_patch == self.pack.patch or obj.id in self.pack.reconfirmed

    @property
    def objectives(self) -> list[Objective]:
        return [o for c in self.chapters for o in c.objectives]

    def get(self, objective_id: str) -> Objective | None:
        return next((o for o in self.objectives if o.id == objective_id), None)

    def chapter(self, chapter_id: str) -> Chapter | None:
        return next((c for c in self.chapters if c.id == chapter_id), None)

    def chapter_of(self, objective_id: str) -> Chapter | None:
        obj = self.get(objective_id)
        return self.chapter(obj.chapter_id) if obj else None


# ---------------------------------------------------------------------------
# Parsing and validation
# ---------------------------------------------------------------------------
def _parse_objective(raw: dict, chapter_id: str, where: str, custom: bool,
                     chapter_patch: str = "", chapter_categories: list[str] | None = None) -> tuple[Objective | None, list[str]]:
    errors = []
    if not isinstance(raw, dict):
        return None, [f"{where}: an objective is not an object"]
    oid = raw.get("id")
    label = f"{where} [{oid or '?'}]"
    if not isinstance(oid, str) or not oid.strip():
        errors.append(f"{label}: missing 'id'")
    title = raw.get("title")
    if not isinstance(title, str) or not title.strip():
        errors.append(f"{label}: missing 'title'")
    kind = raw.get("kind", "task")
    if kind not in KINDS:
        errors.append(f"{label}: 'kind' must be one of {', '.join(KINDS)}")
    raw_steps = raw.get("steps")
    steps = []
    if not isinstance(raw_steps, list) or not raw_steps:
        errors.append(f"{label}: needs at least one step")
    else:
        for i, s in enumerate(raw_steps, 1):
            if not isinstance(s, dict) or not str(s.get("do", "")).strip() or not str(s.get("done_when", "")).strip():
                errors.append(f"{label}: step {i} needs 'do' and 'done_when'")
                continue
            steps.append(Step(do=str(s["do"]).strip(), done_when=str(s["done_when"]).strip(),
                              where=str(s.get("where") or "").strip()))
    goal = raw.get("goal") or {}
    target = goal.get("target", 0) if isinstance(goal, dict) else 0
    if kind == "grind" and (not isinstance(target, int) or target < 1):
        errors.append(f"{label}: a grind needs goal.target >= 1")
    ship = raw.get("ship")
    if kind == "purchase" and not (isinstance(ship, dict) and ship.get("uex_name")):
        errors.append(f"{label}: a purchase needs ship.uex_name")
    rep = raw.get("reputation")
    if rep is not None and not (isinstance(rep, dict) and rep.get("faction") and rep.get("rank")):
        errors.append(f"{label}: 'reputation' needs faction and rank")
    requires = raw.get("requires") or []
    if not isinstance(requires, list) or not all(isinstance(r, str) for r in requires):
        errors.append(f"{label}: 'requires' must be a list of objective ids")
        requires = []
    if errors:
        return None, errors
    return Objective(
        id=oid.strip(),
        title=title.strip(),
        kind=kind,
        chapter_id=chapter_id,
        steps=steps,
        why=str(raw.get("why") or ""),
        tags=[str(t) for t in raw.get("tags") or []],
        optional=bool(raw.get("optional", False)),
        goal_target=int(target) if kind == "grind" else 0,
        goal_unit=str(goal.get("unit") or "") if isinstance(goal, dict) else "",
        reputation=rep,
        reward=str(raw.get("reward") or ""),
        cost=str(raw.get("cost") or ""),
        ship=ship if isinstance(ship, dict) else None,
        requires=list(requires),
        sources=[str(s) for s in raw.get("sources") or []],
        tips=str(raw.get("tips") or ""),
        custom=custom,
        contracts=[str(t) for t in raw.get("contracts") or [] if isinstance(t, str)],
        verified_patch=str(raw.get("verified") or chapter_patch or ""),
        categories=[str(c) for c in raw.get("categories") or chapter_categories or []],
    ), []


def _read_json(path: Path) -> tuple[dict | None, str | None]:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        return None, f"{path.name}: can't be read ({exc})"
    if not isinstance(data, dict):
        return None, f"{path.name}: top level must be an object"
    if data.get("schema", SCHEMA_VERSION) != SCHEMA_VERSION:
        return None, f"{path.name}: unsupported schema {data.get('schema')!r}"
    return data, None


def _chapter_files(directory: Path) -> list[Path]:
    if not directory or not directory.is_dir():
        return []
    return sorted(p for p in directory.glob("*.json") if p.is_file())


def load_guide(dirs: list[Path], custom_path: Path | None = None, remove: set[str] | None = None) -> Guide:
    """Load every chapter file in `dirs` (in order), then the custom
    objectives file. Each directory is a layer: a later layer can add
    objectives to an earlier chapter by reusing its id, and replace an
    earlier objective by reusing the objective's id. The same id twice in one
    layer is an error. `remove` drops objectives by id after loading."""
    errors: list[str] = []
    chapters: dict[str, Chapter] = {}
    seen: dict[str, tuple[int, Chapter]] = {}   # objective id -> (layer, chapter)
    layer = 0

    def add_objectives(raw_list, chapter: Chapter, where: str, custom: bool,
                       file_patch: str | None = None, file_categories: list[str] | None = None):
        # The file's own chapter header supplies the patch and categories, so
        # a newer pack that adds to (or overrides in) an inherited chapter
        # stamps its objectives with its own patch.
        if not isinstance(raw_list, list):
            errors.append(f"{where}: 'objectives' must be a list")
            return
        patch = chapter.patch if file_patch is None else file_patch
        cats = chapter.categories if not file_categories else file_categories
        for raw in raw_list:
            obj, errs = _parse_objective(raw, chapter.id, where, custom, patch, cats)
            errors.extend(errs)
            if obj is None:
                continue
            if obj.id in seen:
                old_layer, old_chapter = seen[obj.id]
                if old_layer == layer:
                    errors.append(f"{where} [{obj.id}]: duplicate objective id, skipped")
                    continue
                # A later layer overrides: replace in place when it stays in
                # the same chapter, otherwise move it.
                index = next(i for i, o in enumerate(old_chapter.objectives) if o.id == obj.id)
                if old_chapter is chapter:
                    chapter.objectives[index] = obj
                else:
                    del old_chapter.objectives[index]
                    chapter.objectives.append(obj)
            else:
                chapter.objectives.append(obj)
            seen[obj.id] = (layer, chapter)

    for layer, directory in enumerate(dirs):
        for path in _chapter_files(directory):
            data, err = _read_json(path)
            if err:
                errors.append(err)
                continue
            meta = data.get("chapter")
            if not isinstance(meta, dict) or not meta.get("id") or not meta.get("title"):
                errors.append(f"{path.name}: needs chapter.id and chapter.title")
                continue
            chapter = chapters.get(meta["id"])
            if chapter is None:
                try:
                    order = int(meta.get("order", 1000))
                except (TypeError, ValueError):
                    order = 1000
                chapter = Chapter(id=str(meta["id"]), title=str(meta["title"]), order=order,
                                  summary=str(meta.get("summary") or ""), patch=str(meta.get("patch") or ""),
                                  categories=[str(c) for c in meta.get("categories") or []])
                chapters[chapter.id] = chapter
            add_objectives(data.get("objectives", []), chapter, path.name, custom=False,
                           file_patch=str(meta.get("patch") or chapter.patch),
                           file_categories=[str(c) for c in meta.get("categories") or []])

    layer = len(dirs)
    if custom_path is not None and custom_path.exists():
        data, err = _read_json(custom_path)
        if err:
            errors.append(err)
        else:
            for raw in data.get("objectives", []) or []:
                target_id = raw.get("chapter") if isinstance(raw, dict) else None
                chapter = chapters.get(target_id) if target_id else None
                if chapter is None:
                    chapter = chapters.get(CUSTOM_CHAPTER_ID)
                    if chapter is None:
                        chapter = Chapter(id=CUSTOM_CHAPTER_ID, title=CUSTOM_CHAPTER_TITLE, order=10_000,
                                          summary="Objectives you added yourself.")
                        chapters[CUSTOM_CHAPTER_ID] = chapter
                add_objectives([raw], chapter, custom_path.name, custom=True)

    if remove:
        for chapter in chapters.values():
            chapter.objectives = [o for o in chapter.objectives if o.id not in remove]
    ordered = sorted(chapters.values(), key=lambda c: (c.order, c.id))
    guide = Guide(chapters=[c for c in ordered if c.objectives], errors=errors)
    _check_requires(guide)
    return guide


def _check_requires(guide: Guide) -> None:
    """Drop requirements on unknown ids, then break any requirement cycle so
    the guide can always pick a next objective."""
    ids = {o.id for o in guide.objectives}
    for obj in guide.objectives:
        unknown = [r for r in obj.requires if r not in ids]
        if unknown:
            guide.errors.append(f"[{obj.id}]: requires unknown objective(s) {', '.join(unknown)}; ignored")
            obj.requires = [r for r in obj.requires if r in ids]
    by_id = {o.id: o for o in guide.objectives}
    state: dict[str, int] = {}  # 1 = visiting, 2 = done

    def visit(oid: str):
        state[oid] = 1
        obj = by_id[oid]
        for req in list(obj.requires):
            if state.get(req) == 1:
                guide.errors.append(f"[{oid}]: requirement cycle through {req}; requirement dropped")
                obj.requires.remove(req)
            elif state.get(req) is None:
                visit(req)
        state[oid] = 2

    for oid in by_id:
        if state.get(oid) is None:
            visit(oid)


# ---------------------------------------------------------------------------
# Filtering, progress maths and live prices
# ---------------------------------------------------------------------------
def is_visible(obj: Objective, show_optional: bool, show_unlawful: bool,
               focus: frozenset[str] | set[str] = frozenset()) -> bool:
    """`focus` is the set of category ids the player chose in setup (empty
    means everything). Objectives with no category, or only always-shown
    ones (Getting Started), are never hidden by it."""
    if obj.optional and not show_optional:
        return False
    if obj.unlawful and not show_unlawful:
        return False
    if focus:
        cats = set(obj.categories) - ALWAYS_SHOWN_CATEGORIES
        if cats and not cats & set(focus):
            return False
    return True


def is_unlocked(obj: Objective, done_ids: set[str]) -> bool:
    return all(r in done_ids for r in obj.requires)


def next_objective(guide: Guide, done_ids: set[str], show_optional: bool, show_unlawful: bool,
                   focus: frozenset[str] | set[str] = frozenset()) -> Objective | None:
    """The first visible, unfinished objective in guide order whose
    requirements are done; if every remaining one is locked, the first
    visible unfinished one."""
    remaining = [o for o in guide.objectives
                 if o.id not in done_ids and is_visible(o, show_optional, show_unlawful, focus)]
    for obj in remaining:
        if is_unlocked(obj, done_ids):
            return obj
    return remaining[0] if remaining else None


def level_for_xp(xp: int) -> tuple[int, int, int]:
    """(level, xp into this level, xp needed for the next). Each level needs
    50 XP more than the one before, starting at 200."""
    level, need = 1, 200
    while xp >= need:
        xp -= need
        level += 1
        need += 50
    return level, xp, need


def total_xp(guide: Guide, done_ids: set[str]) -> int:
    return sum(o.xp for o in guide.objectives if o.id in done_ids)


def chapter_progress(chapter: Chapter, done_ids: set[str], show_optional: bool, show_unlawful: bool,
                     focus: frozenset[str] | set[str] = frozenset()) -> tuple[int, int]:
    visible = [o for o in chapter.objectives if is_visible(o, show_optional, show_unlawful, focus)]
    return sum(1 for o in visible if o.id in done_ids), len(visible)


def cheapest_listing(rows: list[dict], uex_name: str) -> dict | None:
    """The cheapest UEX `vehicles_purchases_prices_all` row for a vehicle,
    matched on its exact UEX vehicle name."""
    wanted = uex_name.strip().lower()
    hits = [r for r in rows or []
            if str(r.get("vehicle_name") or "").strip().lower() == wanted and r.get("price_buy")]
    if not hits:
        return None
    return min(hits, key=lambda r: r["price_buy"])


def contracts_needed(points_needed: int, rep_per_contract: int) -> int:
    """Rounded-up count used for grind targets (see docs/leveling-guide/
    verification.md)."""
    if rep_per_contract <= 0:
        raise ValueError("rep_per_contract must be positive")
    return max(1, math.ceil(points_needed / rep_per_contract))


# ---------------------------------------------------------------------------
# Setup questionnaire: turn "where are you already?" answers into progress
# ---------------------------------------------------------------------------
def ladder_choices(guide: Guide) -> list[tuple[str, str, list[tuple[str, int]]]]:
    """Each faction ladder the guide has rank-up objectives for, with the
    ranks it covers in ascending order: [(faction, ladder, [(rank, points),
    ...]), ...], in the order they first appear in the guide. Built from
    content, so new chapters and packs show up in the questionnaire
    automatically."""
    order: list[tuple[str, str]] = []
    ranks: dict[tuple[str, str], dict[str, int]] = {}
    for obj in guide.objectives:
        rep = obj.reputation
        if not rep or not isinstance(rep.get("points"), int):
            continue
        key = (rep["faction"], rep.get("ladder", ""))
        if key not in ranks:
            order.append(key)
            ranks[key] = {}
        ranks[key][rep["rank"]] = rep["points"]
    return [(f, lad, sorted(ranks[(f, lad)].items(), key=lambda kv: kv[1])) for f, lad in order]


def ancestors(guide: Guide, objective_ids: set[str]) -> set[str]:
    """Every objective the given ones require, directly or indirectly."""
    by_id = {o.id: o for o in guide.objectives}
    out: set[str] = set()
    stack = list(objective_ids)
    while stack:
        obj = by_id.get(stack.pop())
        if obj is None:
            continue
        for req in obj.requires:
            if req not in out:
                out.add(req)
                stack.append(req)
    return out


def ids_done_for(guide: Guide, knows_basics: bool, reached: dict[str, int]) -> set[str]:
    """Objectives to mark done from setup answers. `reached` maps a
    rep_key(faction, ladder) to the reputation points of the rank the player
    already holds. A rank-up objective at or below that is done, and so is
    everything it requires (you can't be a Guild Member without the earlier
    licenses)."""
    done = set()
    if knows_basics:
        done |= {o.id for o in guide.objectives if BASICS_TAG in o.tags}
    for obj in guide.objectives:
        rep = obj.reputation
        if not rep or not isinstance(rep.get("points"), int):
            continue
        have = reached.get(rep_key(rep["faction"], rep.get("ladder", "")))
        if have is not None and rep["points"] <= have:
            done.add(obj.id)
    return done | ancestors(guide, done)


# ---------------------------------------------------------------------------
# Patch packs
# ---------------------------------------------------------------------------
def _version_key(text: str) -> tuple:
    return tuple(int(n) for n in __import__("re").findall(r"\d+", text or "")[:4])


def discover_packs(roots: list[Path]) -> tuple[dict[str, Pack], list[str]]:
    """Every pack folder (a directory with pack.json) under the given roots.
    A later root wins on a duplicate id, so a user pack can replace a
    bundled one."""
    packs: dict[str, Pack] = {}
    errors: list[str] = []
    for root in roots:
        if not root or not Path(root).is_dir():
            continue
        for folder in sorted(Path(root).iterdir()):
            manifest = folder / "pack.json"
            if not manifest.is_file():
                continue
            try:
                data = json.loads(manifest.read_text(encoding="utf-8"))
            except (OSError, ValueError) as exc:
                errors.append(f"{folder.name}/pack.json: can't be read ({exc})")
                continue
            if not isinstance(data, dict) or data.get("schema", PACK_SCHEMA_VERSION) != PACK_SCHEMA_VERSION:
                errors.append(f"{folder.name}/pack.json: unsupported or missing schema")
                continue
            pid, label, patch = data.get("id"), data.get("label"), data.get("patch")
            if not (isinstance(pid, str) and pid and label and patch):
                errors.append(f"{folder.name}/pack.json: needs id, label and patch")
                continue
            packs[pid] = Pack(
                id=pid, label=str(label), patch=str(patch),
                channel=str(data.get("channel") or "live"),
                game_version=str(data.get("game_version") or ""),
                extends=str(data.get("extends") or ""),
                remove=[str(x) for x in data.get("remove") or []],
                reconfirmed=[str(x) for x in data.get("reconfirmed") or []],
                notes=str(data.get("notes") or ""),
                path=folder,
                categories=list(data.get("categories") or []),
                categories_add=list(data.get("categories_add") or []),
                also_confirmed=[x for x in data.get("also_confirmed") or [] if isinstance(x, dict) and x.get("title")],
            )
    return packs, errors


def pack_chain(pack_id: str, packs: dict[str, Pack]) -> tuple[list[Pack], list[str]]:
    """The pack and everything it extends, base first."""
    chain: list[Pack] = []
    errors: list[str] = []
    seen: set[str] = set()
    current = packs.get(pack_id)
    while current is not None:
        if current.id in seen:
            errors.append(f"pack {current.id}: 'extends' loops back to itself; stopped there")
            break
        seen.add(current.id)
        chain.insert(0, current)
        if not current.extends:
            break
        parent = packs.get(current.extends)
        if parent is None:
            errors.append(f"pack {current.id}: extends unknown pack {current.extends!r}")
        current = parent
    return chain, errors


def default_pack_id(packs: dict[str, Pack]) -> str | None:
    """The newest live pack, else the newest pack of any channel."""
    if not packs:
        return None
    live = [p for p in packs.values() if p.channel == "live"]
    pool = live or list(packs.values())
    return max(pool, key=lambda p: (_version_key(p.patch), p.id)).id


def load_pack(pack_id: str | None, roots: list[Path], extra_dirs: list[Path] | None = None,
              custom_path: Path | None = None, catalog_loader=None) -> Guide:
    """Load the active pack (with everything it extends), then the user and
    custom layers. `catalog_loader(path)` reads contracts.json; the nearest
    pack in the chain that has one provides the catalog."""
    packs, errors = discover_packs(roots)
    if pack_id not in packs:
        if pack_id:
            errors.append(f"pack {pack_id!r} not found; using the default")
        pack_id = default_pack_id(packs)
    chain, chain_errors = pack_chain(pack_id, packs) if pack_id else ([], [])
    errors += chain_errors
    dirs = [p.path / "chapters" for p in chain if p.path] + list(extra_dirs or [])
    remove = {oid for p in chain for oid in p.remove}
    guide = load_guide(dirs, custom_path, remove)
    guide.errors = errors + guide.errors
    guide.pack = packs.get(pack_id) if pack_id else None
    guide.categories = resolve_categories(chain)
    if catalog_loader is not None:
        for p in reversed(chain):
            if p.has_catalog:
                try:
                    guide.catalog = catalog_loader(p.path / "contracts.json")
                except (OSError, ValueError) as exc:
                    guide.errors.append(f"pack {p.id}: contracts.json can't be read ({exc})")
                break
    return guide


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


def ladder_name(key: str) -> str:
    return LADDER_NAMES.get(key, key)


def rep_key(faction: str, ladder: str) -> str:
    """How progress stores a reputation value: one number per faction and ladder."""
    return f"{faction}|{ladder}"


def resolve_categories(chain: list[Pack]) -> list:
    """Base first: a pack's `categories` replaces what it inherits, and its
    `categories_add` appends to it (an id already present is replaced)."""
    cats: list = []
    for pack in chain:
        if pack.categories:
            cats = list(pack.categories)
        for extra in pack.categories_add:
            if isinstance(extra, dict) and extra.get("id"):
                cats = [c for c in cats if c.get("id") != extra["id"]] + [extra]
    return cats
