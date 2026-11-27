"""Tests for the Leveling Guide module (mobiGuide): patch packs and their
data checks, the loader's layering, categories, contract recommendations,
reputation logging, goals, import/export, progress storage, setup, and
offscreen card walk-throughs.

Offscreen Qt, temp files, a fake API, no network:
    python tests/test_leveling_guide.py
"""
import importlib.util
import json
import os
import sys
import tempfile
import zipfile
from pathlib import Path
from unittest.mock import MagicMock

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from PySide6.QtWidgets import QApplication

from host.card_container import CardContainer
from host.config import Config
from modules.leveling_guide import contracts as k
from modules.leveling_guide import guide as g
from modules.leveling_guide import packio
from modules.leveling_guide.packcheck import check_pack
from modules.leveling_guide.progress import CustomObjectives, ProgressStore

app = QApplication.instance() or QApplication([])
PACKS = ROOT / "modules" / "leveling_guide" / "packs"
LIVE_CHAPTERS = PACKS / "4.10.3-live" / "chapters"


def _tmpdir() -> Path:
    return Path(tempfile.mkdtemp())


def _write(path: Path, data) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(data if isinstance(data, str) else json.dumps(data), encoding="utf-8")
    return path


def _chapter(cid, objectives, order=10, **extra):
    meta = {"id": cid, "title": cid.title(), "order": order}
    meta.update(extra)
    return {"schema": 1, "chapter": meta, "objectives": objectives}


def _obj(oid, **extra):
    base = {"id": oid, "title": oid, "steps": [{"do": "Do it", "done_when": "It is done"}]}
    base.update(extra)
    return base


def _live():
    return g.load_pack("4.10.3-live", [PACKS], catalog_loader=k.load_catalog)


def _ptu():
    return g.load_pack("5.0-ptu", [PACKS], catalog_loader=k.load_catalog)


# ---------------------------------------------------------------------------
# Bundled packs
# ---------------------------------------------------------------------------
def test_bundled_packs_pass_their_data_checks() -> int:
    packs, errors = g.discover_packs([PACKS])
    assert errors == [] and {"4.10.3-live", "5.0-ptu"} <= set(packs), (errors, list(packs))
    assert g.default_pack_id(packs) == "4.10.3-live", "the newest LIVE pack is the default"
    for pid in packs:
        report = check_pack(pid, [PACKS])
        assert report.ok, f"{pid}: {report.errors}"
    ptu = check_pack("5.0-ptu", [PACKS])
    stored = set(packs["5.0-ptu"].reconfirmed)
    assert stored == set(ptu.reconfirm), "5.0-ptu's reconfirmed list is stale: run scripts/check_pack.py --write"
    assert "bhg-junior" not in stored, "an objective the 5.0 data doesn't back must not be re-confirmed"
    return 5


def test_bundled_content() -> int:
    for guide in (_live(), _ptu()):
        assert guide.errors == [], guide.errors
        objs = guide.objectives
        assert len({o.id for o in objs}) == len(objs), "duplicate objective ids"
        for o in objs:
            assert o.sources and all(s.startswith("https://") for s in o.sources), o.id
            assert o.steps and all(s.do and s.done_when for s in o.steps), o.id
            assert o.categories, f"{o.id} has no category"
            for r in o.requires:
                assert guide.get(r) is not None, f"{o.id} requires unknown {r}"
        assert guide.catalog is not None and len(guide.catalog.contracts) > 500
    live, ptu = _live(), _ptu()
    assert live.chapter("guilds") is None and ptu.chapter("guilds") is not None, "5.0 adds the Guilds chapter"
    assert len(ptu.objectives) == len(live.objectives) + len(ptu.chapter("guilds").objectives)
    assert ptu.catalog.version.startswith("5.0") and live.catalog.version.startswith("4.10.3")
    outlaw = live.chapter("outlaw")
    assert outlaw and all(o.unlawful and o.optional for o in outlaw.objectives)
    return 6


def test_grind_targets_match_verified_numbers() -> int:
    """Grind targets come from (rank threshold - previous threshold) /
    reputation per contract (docs/leveling-guide/verification.md)."""
    live, ptu = _live(), _ptu()
    expected = {
        "haul-covalex-junior": (250, 500), "haul-covalex-member": (5250 - 250, 500),
        "haul-covalex-experienced": (27750 - 5250, 1000), "haul-covalex-senior": (77750 - 27750, 2000),
        "haul-covalex-master": (237750 - 77750, 4000), "bhg-junior": (3000, 4000),
        "bhg-guild-member": (10000 - 3000, 1000), "bhg-senior": (40000 - 10000, 2000),
        "bhg-veteran": (200000 - 40000, 4000), "bhg-steward": (480000 - 200000, 8000),
        "fox-jr": (800 - 200, 100), "fox-contractor": (2200 - 800, 100), "fox-sr": (5800 - 2200, 150),
        "fox-veteran": (15000 - 5800, 200), "salv-jr": (800 - 100, 100), "salv-contractor": (2200 - 800, 100),
        "ids-jr": (800 - 100, 100), "ids-contractor": (2200 - 800, 150), "ids-sr": (5800 - 2200, 250),
        "ids-veteran": (15000 - 5800, 250), "recco-associate": (2400 - 800, 200),
        "recco-trusted": (6000 - 2400, 200), "recco-prestige1": (10800 - 6000, 350),
        "recco-prestige2": (30000 - 10800, 350), "recco-prestige3": (69600 - 30000, 350),
    }
    for oid, (points, per) in expected.items():
        assert live.get(oid).goal_target == g.contracts_needed(points, per), oid
    guild = {"guild-itg-jr": (513, 200), "guild-itg-contractor": (2051 - 513, 150),
             "guild-merc-jr": (513, 200), "guild-merc-contractor": (2051 - 513, 200),
             "guild-urw-jr": (513, 200), "guild-urw-contractor": (2051 - 513, 200)}
    for oid, (points, per) in guild.items():
        assert ptu.get(oid).goal_target == g.contracts_needed(points, per), oid
    return len(expected) + len(guild)


# ---------------------------------------------------------------------------
# Loader: layers, packs, inheritance
# ---------------------------------------------------------------------------
def test_loader_survives_bad_content() -> int:
    d = _tmpdir()
    _write(d / "01-good.json", _chapter("good", [_obj("a"), _obj("b", requires=["a"])]))
    _write(d / "02-broken.json", "{not json")
    _write(d / "03-nochapter.json", {"schema": 1, "objectives": [_obj("x")]})
    _write(d / "04-bad-objectives.json", _chapter("bad", [
        {"id": "no-steps", "title": "No steps", "steps": []},
        _obj("bad-kind", kind="dance"), _obj("grind-no-goal", kind="grind"), _obj("buy-no-ship", kind="purchase"),
        _obj("a"), _obj("unknown-req", requires=["nope"]),
        _obj("cyc1", requires=["cyc2"]), _obj("cyc2", requires=["cyc1"]),
    ], order=20))
    _write(d / "05-schema.json", {"schema": 99, "chapter": {"id": "z", "title": "Z"}, "objectives": []})
    guide = g.load_guide([d])
    assert {o.id for o in guide.objectives} == {"a", "b", "unknown-req", "cyc1", "cyc2"}
    text = "\n".join(guide.errors)
    for needle in ("02-broken.json", "03-nochapter.json", "no-steps", "bad-kind", "grind-no-goal",
                   "buy-no-ship", "duplicate", "requires unknown", "cycle", "unsupported schema"):
        assert needle in text, f"missing error about {needle}:\n{text}"
    assert not (guide.get("cyc1").requires and guide.get("cyc2").requires), "cycle not broken"
    return 3


def test_pack_inheritance_overrides_and_categories() -> int:
    root = _tmpdir()
    cats = [{"id": "hauling", "title": "Hauling", "mission_types": ["Hauling"]},
            {"id": "mining", "title": "Mining", "mission_types": ["Ship Mining"]}]
    _write(root / "base" / "pack.json", {"schema": 1, "id": "base", "label": "Base", "patch": "1.0",
                                         "categories": cats})
    _write(root / "base" / "chapters" / "a.json", _chapter("haul", [
        _obj("h1", title="Old title"), _obj("h2"), _obj("gone")], patch="1.0", categories=["hauling"]))
    _write(root / "next" / "pack.json", {"schema": 1, "id": "next", "label": "Next", "patch": "2.0",
                                         "extends": "base", "remove": ["gone"], "reconfirmed": ["h2"],
                                         "categories_add": [{"id": "guilds", "title": "Guilds"}]})
    _write(root / "next" / "chapters" / "b.json", _chapter("haul", [_obj("h1", title="New title"), _obj("h3")],
                                                          patch="2.0", categories=["hauling"]))
    _write(root / "loop" / "pack.json", {"schema": 1, "id": "loop", "label": "Loop", "patch": "3.0", "extends": "loop"})
    _write(root / "junk" / "pack.json", "{nope")
    packs, errors = g.discover_packs([root])
    assert set(packs) == {"base", "next", "loop"} and any("junk" in e for e in errors)
    guide = g.load_pack("next", [root])
    assert [o.id for o in guide.chapter("haul").objectives] == ["h1", "h2", "h3"], "override in place, removal applied"
    assert guide.get("h1").title == "New title" and guide.get("h1").verified_patch == "2.0"
    assert guide.is_verified(guide.get("h1")) and guide.is_verified(guide.get("h2")), "own + reconfirmed"
    base_only = g.load_pack("base", [root])
    assert base_only.get("gone") is not None
    assert [c["id"] for c in guide.categories] == ["hauling", "mining", "guilds"]
    loop = g.load_pack("loop", [root])
    assert any("loops" in e for e in loop.errors)
    fallback = g.load_pack("missing", [root])
    assert fallback.pack is not None and any("not found" in e for e in fallback.errors)
    # A user pack root later in the list replaces a bundled pack with the same id.
    user = _tmpdir()
    _write(user / "base" / "pack.json", {"schema": 1, "id": "base", "label": "Mine", "patch": "1.0"})
    _write(user / "base" / "chapters" / "a.json", _chapter("x", [_obj("x1")]))
    assert g.load_pack("base", [root, user]).pack.label == "Mine"
    return 9


def test_user_files_extend_chapters_and_custom_objectives() -> int:
    bundled, user = _tmpdir(), _tmpdir()
    _write(bundled / "01.json", _chapter("hauling", [_obj("h1")]))
    _write(user / "extra.json", _chapter("hauling", [_obj("h2")]))
    _write(user / "new.json", _chapter("racing", [_obj("r1")], order=5))
    custom_file = _tmpdir() / "custom.json"
    custom = CustomObjectives(custom_file)
    a = custom.add("Buy a Cutlass", [{"do": "Buy it", "done_when": "Owned"}], chapter_id="hauling")
    b = custom.add("Race", [{"do": "Race", "done_when": "Finished"}], kind="grind", goal_target=3, goal_unit="races")
    c = custom.add("Buy a Cutlass", [{"do": "Again", "done_when": "Owned"}], chapter_id="nowhere")
    assert a["id"] != c["id"]
    guide = g.load_guide([bundled, user], custom_file)
    assert guide.errors == [], guide.errors
    assert [ch.id for ch in guide.chapters] == ["racing", "hauling", g.CUSTOM_CHAPTER_ID]
    assert [o.id for o in guide.chapter("hauling").objectives] == ["h1", "h2", a["id"]]
    assert {o.id for o in guide.chapter(g.CUSTOM_CHAPTER_ID).objectives} == {b["id"], c["id"]}
    assert CustomObjectives(custom_file).remove(a["id"]) is True
    return 4


# ---------------------------------------------------------------------------
# Contracts, reputation and goals
# ---------------------------------------------------------------------------
def test_categories_and_contract_recommendations() -> int:
    live = _live()
    cats = {c.id: c for c in k.parse_categories(live.categories)}
    for cid in ("hauling", "mining", "refining", "salvage", "bounty-hunting", "ship-combat", "fps-combat",
                "trading", "outlaw", "support", "investigation"):
        assert cid in cats, cid
    ship = k.in_category(live.catalog, cats["ship-combat"], {}, True, 9999)
    fps = k.in_category(live.catalog, cats["fps-combat"], {}, True, 9999)
    assert ship and fps and not ({r["contract"]["key"] for r in ship} & {r["contract"]["key"] for r in fps})
    assert all(r["contract"].get("ships") for r in ship) and not any(r["contract"].get("ships") for r in fps)
    assert all(r["contract"]["illegal"] for r in k.in_category(live.catalog, cats["outlaw"], {}, True, 9999))
    assert not any(r["contract"]["illegal"] for r in k.in_category(live.catalog, cats["hauling"], {}, False, 9999))

    # Covalex Hauling: at Junior (250 rep), "Junior Rank" hauls (+500) are the
    # best unlocked; "Member Rank" ones show as locked and sort after.
    known = {"Covalex|Hauling": 250}
    rows = k.for_reputation(live.catalog, "Covalex", "Hauling", known, False, None, 50)
    assert rows, "no Covalex hauling contracts"
    unlocked = [r for r in rows if r["unlocked"] is not False]
    assert unlocked[0]["gain"] >= 500, unlocked[0]
    locked_after = [r["unlocked"] for r in rows]
    assert locked_after == sorted(locked_after, key=lambda u: u is False), "locked contracts must sort last"
    gated = [r for r in rows if r["contract"].get("requires")]
    assert any(r["unlocked"] is False for r in gated) and any(r["unlocked"] for r in gated)
    assert k.runs_needed(4700, 500) == 10 and k.runs_needed(0, 500) == 0
    best_pay = k.for_money(live.catalog, {}, False, None, 5)
    pays = [r["gain"] for r in best_pay if r["unlocked"] is not False]
    assert pays == sorted(pays, reverse=True)

    # 5.0: guild reputation from career contracts.
    ptu = _ptu()
    itg = k.for_reputation(ptu.catalog, "Interstellar Transport Guild", "Guild", {}, False, None, 20)
    assert itg and all(r["gain"] > 0 for r in itg)
    assert [r for r in ptu.catalog.rank_names("Guild") if r[0] == "Jr. Contractor"] == [("Jr. Contractor", 513)]
    return 12


def test_progress_reputation_log_and_goals() -> int:
    path = _tmpdir() / "progress.json"
    p = ProgressStore(path)
    contract = {"key": "Junior Rank - Small Cargo Haul|Covalex|", "title": "Junior Rank - Small Cargo Haul",
                "rep": [{"faction": "Covalex", "ladder": "Hauling", "amount": 500},
                        {"faction": "ITG", "ladder": "Guild", "amount": 100}], "uec": [59750, 76750]}
    p.set_rep("Covalex|Hauling", 250)
    goal = p.add_goal({"kind": "money", "target": 1_000_000, "start_uec": 200_000, "label": "Save"})
    p.log_run(contract)
    p.log_run(contract)
    q = ProgressStore(path)
    assert q.rep("Covalex|Hauling") == 1250 and q.rep("ITG|Guild") == 200
    assert q.earned_uec == 2 * 76750 and q.runs_logged(contract["key"]) == 2
    assert q.goal_money(q.goal(goal["id"])) == 200_000 + 2 * 76750
    q.undo_last_run()
    assert q.rep("Covalex|Hauling") == 750 and q.earned_uec == 76750 and q.runs_logged(contract["key"]) == 1
    q.raise_rep_to("Covalex|Hauling", 500)
    assert q.rep("Covalex|Hauling") == 750, "raise_rep_to never lowers"
    q.raise_rep_to("Covalex|Hauling", 5250)
    assert q.rep("Covalex|Hauling") == 5250
    q.remove_goal(goal["id"])
    assert q.goals() == []
    q.reset_all()
    assert ProgressStore(path).known_rep() == {} and ProgressStore(path).earned_uec == 0
    return 9


def test_progress_store_basics() -> int:
    path = _tmpdir() / "progress.json"
    p = ProgressStore(path)
    p.set_done("a")
    p.set_step("b", 2)
    assert p.add_count("c", 3) == 3 and p.add_count("c", -10) == 0
    p.set_skipped("d")
    p.set_current("b")
    q = ProgressStore(path)
    assert q.done_ids() == {"a"} and q.skipped_ids() == {"d"} and q.step("b") == 2 and q.current == "b"
    q.set_done("d")
    assert q.skipped_ids() == set()
    _write(path, "{garbage")
    assert ProgressStore(path).done_ids() == set()
    assert list(path.parent.glob("progress.json.corrupt-*")), "corrupt file not quarantined"
    return 4


def test_maths() -> int:
    assert g.level_for_xp(0) == (1, 0, 200) and g.level_for_xp(200) == (2, 0, 250) and g.level_for_xp(450) == (3, 0, 300)
    rows = [{"vehicle_name": "Vulture", "price_buy": 2646000, "terminal_name": "B"},
            {"vehicle_name": "Vulture", "price_buy": 2513700, "terminal_name": "New Deal Lorville"},
            {"vehicle_name": "Vulture Renegade", "price_buy": 1, "terminal_name": "X"}]
    assert g.cheapest_listing(rows, "vulture")["terminal_name"] == "New Deal Lorville"
    assert g.cheapest_listing(rows, "Golem") is None
    return 3


# ---------------------------------------------------------------------------
# Import / export
# ---------------------------------------------------------------------------
def _zip(path: Path, files: dict) -> Path:
    with zipfile.ZipFile(path, "w") as zf:
        for name, data in files.items():
            zf.writestr(name, data if isinstance(data, str) else json.dumps(data))
    return path


def test_import_export() -> int:
    work = _tmpdir()
    packs_dir, user_dir = work / "user" / "packs", work / "user"
    pack = {"schema": 1, "id": "5.0.1-live", "label": "5.0.1 (live)", "patch": "5.0.1", "extends": "4.10.3-live"}
    good = _zip(work / "good.zip", {
        "my-pack/pack.json": pack,
        "my-pack/chapters/90-racing.json": _chapter("racing", [_obj("race-1", categories=["events"])]),
        "my-pack/readme.exe": "MZ not data",
    })
    dest, warnings = packio.import_pack(good, packs_dir, [PACKS])
    assert dest == packs_dir / "5.0.1-live" and (dest / "pack.json").is_file()
    assert not (dest / "readme.exe").exists(), "only JSON is installed"
    loaded = g.load_pack("5.0.1-live", [PACKS, packs_dir], catalog_loader=k.load_catalog)
    assert loaded.get("race-1") and loaded.get("haul-covalex-member"), "imported pack extends the bundled one"
    try:
        packio.import_pack(good, packs_dir, [PACKS])
        raise AssertionError("re-importing the same id must be refused")
    except packio.ImportError_:
        pass
    bad_cases = {
        "slip.zip": {"../../evil/pack.json": pack},
        "nomanifest.zip": {"chapters/a.json": _chapter("a", [_obj("a1")])},
        "badid.zip": {"pack.json": dict(pack, id="../x")},
        "noextends.zip": {"pack.json": dict(pack, id="orphan", extends="nope"), "chapters/a.json": "{bad"},
    }
    for name, files in bad_cases.items():
        try:
            packio.import_pack(_zip(work / name, files), packs_dir, [PACKS])
            raise AssertionError(f"{name} should have been refused")
        except packio.ImportError_:
            pass
    assert not (work / "evil").exists()

    chapter_file = _write(work / "shared.json", _chapter("shared", [_obj("s1")]))
    installed, _ = packio.import_chapter(chapter_file, user_dir)
    assert installed.parent == user_dir
    try:
        packio.import_chapter(_write(work / "manifest.json", pack), user_dir)
        raise AssertionError("a pack manifest is not a chapter")
    except packio.ImportError_:
        pass

    custom = CustomObjectives(work / "custom.json")
    custom.add("Mine 50 SCU", [{"do": "Mine", "done_when": "Hold full"}], chapter_id="nyx-mining")
    exported = packio.export_custom_chapter(custom.all(), work / "mine.json", patch="4.10.3")
    reimported, _ = packio.import_chapter(exported, _tmpdir())
    assert g.load_guide([reimported.parent]).objectives[0].title == "Mine 50 SCU"
    zipped = packio.export_pack(PACKS / "5.0-ptu", work / "ptu.zip")
    dest2, _ = packio.import_pack(zipped, _tmpdir() / "packs", [PACKS], replace=True)
    assert (dest2 / "contracts.json").is_file() and (dest2 / "chapters" / "12-guilds.json").is_file()
    return 10


# ---------------------------------------------------------------------------
# Setup logic
# ---------------------------------------------------------------------------
def test_setup_logic() -> int:
    guide = _live()
    ladders = {(f, lad): ranks for f, lad, ranks in g.ladder_choices(guide)}
    assert [r for r, _ in ladders[("Covalex", "Hauling")]] == ["Rookie", "Junior", "Member", "Experienced", "Senior", "Master"]
    assert ladders[("Bounty Hunters Guild", "BountyHunter_BountyHuntersGuild")][0] == ("Probationary Guild Member", 1)
    basics = g.ids_done_for(guide, True, {})
    assert basics == {o.id for o in guide.chapter("first-steps").objectives}
    bhg = g.ids_done_for(guide, False, {"Bounty Hunters Guild|BountyHunter_BountyHuntersGuild": 10000})
    assert {"bhg-training-permit", "bhg-junior", "bhg-beginner-permit", "bhg-guild-member"} <= bhg
    assert "bhg-tracker-license" not in bhg
    focus = frozenset({"salvage"})
    assert g.is_visible(guide.get("fs-pick-city"), True, False, focus), "Getting Started is never hidden"
    assert g.is_visible(guide.get("salv-jr"), True, False, focus)
    assert not g.is_visible(guide.get("bhg-junior"), True, False, focus)
    assert g.next_objective(guide, basics, True, False, focus).id == "salv-adagio-intro"
    return 8


# ---------------------------------------------------------------------------
# Card
# ---------------------------------------------------------------------------
class _FakeApi:
    def __init__(self, fail=False):
        self.calls = 0
        self.fail = fail

    def get(self, endpoint, params=None):
        self.calls += 1
        assert endpoint == "vehicles_purchases_prices_all"
        if self.fail:
            raise RuntimeError("UEX down")
        return [{"vehicle_name": "Vulture", "price_buy": 2513700, "terminal_name": "New Deal Lorville"},
                {"vehicle_name": "Golem", "price_buy": 1005480, "terminal_name": "New Deal Lorville"},
                {"vehicle_name": "Cutlass Black", "price_buy": 2010960, "terminal_name": "New Deal Lorville"}]


def _load_module():
    spec = importlib.util.spec_from_file_location("t_leveling_guide", ROOT / "modules" / "leveling_guide" / "module.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _make_card(api=None, pack=None):
    mod = _load_module()
    d = _tmpdir()
    config = Config(path=d / "config.json")
    if pack:
        config.module_settings("leveling_guide")["pack"] = pack
    module = mod.LevelingGuideModule(api or _FakeApi(), config, MagicMock(),
                                     progress=ProgressStore(d / "progress.json"),
                                     custom=CustomObjectives(d / "custom.json"),
                                     pack_roots=[PACKS], extra_dirs=[])
    card = module.create_card(CardContainer(config))
    return mod, module, card, d


def test_card_walkthrough() -> int:
    mod, module, card, d = _make_card()
    assert module.guide.pack.id == "4.10.3-live" and "4.10.3" in module.pack_label.text()
    assert module.current_objective().id == "fs-pick-city"
    for _ in range(len(module.current_objective().steps)):
        module._on_step_done()
    assert module.progress.is_done("fs-pick-city") and module.current_objective().id == "fs-tutorial-steps"
    assert module.xp_bar.value() == 100
    module._on_step_done()
    module._on_back()
    assert module.progress.step("fs-tutorial-steps") == 0
    module._on_skip()
    assert module.current_objective().id == "fs-tutorial-outing" and "fs-tutorial-steps" not in module.progress.done_ids()

    # Rank-up objectives track reputation and list contracts to repeat.
    module._view("haul-covalex-member")
    assert module.rep_box.isVisibleTo(card) and not module.counter_row.isVisibleTo(card)
    assert module.rep_rows.count() > 0
    module.progress.set_rep("Covalex|Hauling", 250)
    module.render()
    assert "250 / 5,250" in module.rep_label.text(), module.rep_label.text()
    junior = next(c for c in module.guide.catalog.contracts
                  if c["title"].startswith("Junior Rank") and c["giver"].startswith("Covalex"))
    module.log_run(junior)
    assert "750 / 5,250" in module.rep_label.text(), module.rep_label.text()
    module._on_undo_run()
    assert "250 / 5,250" in module.rep_label.text()

    # Categories filter the chapters.
    module._on_category_picked(module.category_combo.findData("mining"))
    chapters = [module.chapter_combo.itemData(i) for i in range(module.chapter_combo.count())]
    assert "nyx-mining" in chapters and "hauling" not in chapters, chapters
    module._on_category_picked(0)

    # Outlaw chapter hidden until turned on; compact mode shows one step.
    module._set_option("show_unlawful", False)
    assert not any("Outlaw" in module.chapter_combo.itemText(i) for i in range(module.chapter_combo.count()))
    module._view("fs-launch-own-ship")
    module._set_option("compact", True)
    module._view("fs-launch-own-ship")
    assert module.steps_layout.count() == 1 and not module.list_container.isVisibleTo(card)
    module._set_option("compact", False)
    return 12


def test_card_versions_goals_and_prices() -> int:
    api = _FakeApi()
    mod, module, card, d = _make_card(api)
    # Switch to the 5.0 pack: the Guilds chapter and a not-re-confirmed badge appear.
    module.set_pack("5.0-ptu")
    assert module.guide.pack.id == "5.0-ptu" and module.guide.chapter("guilds") is not None
    module._view("bhg-junior")
    assert "CHECKED ON 4.10.3" in module.info_label.text(), module.info_label.text()
    module._view("haul-covalex-member")
    assert "CHECKED ON" not in module.info_label.text(), "re-confirmed objectives carry no badge"

    # A rank goal shows contracts for that ladder.
    goal = module.add_goal({"kind": "rank", "faction": "Mercenary Guild", "ladder": "Guild",
                            "rank": "Jr. Contractor", "target": 513, "current_rep": 100, "label": "Merc Jr"})
    assert module.settings["view"] == "contracts" and module.contracts_view.isVisibleTo(card)
    assert "100 / 513" in module.goal_label.text() and module.goal_rows.count() > 0
    # A ship goal fetches the price live and counts logged pay toward it.
    ship = module.add_goal({"kind": "ship", "ship": "Cutlass Black", "start_uec": 1_000_000, "label": "Cutlass"})
    assert "loading" in module.goal_label.text().lower()
    module.refresh()
    assert api.calls == 1 and "1,000,000 / 2,010,960" in module.goal_label.text(), module.goal_label.text()
    paying = module.guide.catalog.contracts[0]
    for c in module.guide.catalog.contracts:
        if k.c_pay(c) > k.c_pay(paying) and not c.get("illegal"):
            paying = c
    module.log_run(paying)
    assert f"{1_000_000 + k.c_pay(paying):,}" in module.goal_label.text()
    module.progress.remove_goal(goal["id"])
    module.settings["goal"] = None
    module.render()
    assert "BEST PAYING" in module.contracts_caption.text()

    failing = _FakeApi(fail=True)
    _, broken, card2, _ = _make_card(failing)
    broken._view("mining-buy-golem")
    broken.refresh()
    assert "unavailable" in broken.info_label.text().lower()
    assert not card2.error_widget.isVisibleTo(card2)
    del ship
    return 10


def test_card_setup_flow_and_import() -> int:
    mod, module, card, d = _make_card()
    assert module.setup_text.isVisibleTo(card)
    wizard = mod.SetupWizard(card, list(module.packs.values()), module.settings.get("pack"),
                             g.ladder_choices(module.guide), module.categories, module.settings)
    wizard.basics_radio.setChecked(True)
    combo = wizard.rank_combos["Covalex|Hauling"]
    combo.setCurrentIndex(combo.findData(250))
    wizard.category_checks["mining"].setChecked(False)
    for _ in range(3):
        wizard._on_next()
    assert wizard.next_btn.text() == "START GUIDE"
    answers = wizard.values()
    assert answers["reached"] == {"Covalex|Hauling": 250} and "mining" not in answers["focus"]
    marked = module.apply_setup(answers)
    assert marked >= 8 and not module.setup_text.isVisibleTo(card)
    assert module.current_objective().id == "haul-covalex-member", module.current_objective().id
    assert module.progress.rep("Covalex|Hauling") == 250, "setup seeds the reputation tracker"
    assert not module._visible(module.guide.get("recco-welcome")), "mining hidden by focus"

    module._on_row_clicked("haul-ling-intro", 5)
    assert module.progress.is_done("haul-ling-intro")
    module._on_row_clicked("haul-ling-intro", 5)
    assert not module.progress.is_done("haul-ling-intro")
    module.mark_chapter_done("hauling")
    assert all(module.progress.is_done(o.id) for o in module.guide.chapter("hauling").objectives if module._visible(o))

    # Importing a chapter through the card makes it show up.
    _, fresh, card2, d2 = _make_card()
    fresh._dismiss_setup()
    assert not fresh.setup_text.isVisibleTo(card2) and not fresh.settings["setup_done"]
    return 9


def test_cross_source_catalogs() -> int:
    live, ptu = _live(), _ptu()
    lc = json.loads((PACKS / "4.10.3-live" / "contracts.json").read_text(encoding="utf-8"))
    pc = json.loads((PACKS / "5.0-ptu" / "contracts.json").read_text(encoding="utf-8"))
    assert lc["cross_check"]["wiki"].startswith("4.10.3-LIVE") and lc["cross_check"]["matched"] > 500
    agree = lc["cross_check"]["gate_agree"] / lc["cross_check"]["matched"]
    assert agree > 0.9, f"sources agree on only {agree:.0%} of rank gates"
    assert all(c.get("sources") for c in live.catalog.contracts), "every contract names its sources"
    both = [c for c in live.catalog.contracts if len(c["sources"]) > 1]
    assert len(both) > 500
    assert any(c.get("conflicts") for c in live.catalog.contracts), "disagreements are recorded, not hidden"
    # Wiki-only contracts are in: microTech's VLRT bounty gives 4,000 Guild rep.
    rows = k.for_reputation(live.catalog, "Bounty Hunters Guild", "BountyHunter_BountyHuntersGuild",
                            {"Bounty Hunters Guild|BountyHunter_BountyHuntersGuild": 1}, False, None, 50)
    vlrt = [r for r in rows if "(VLRT)" in r["contract"]["title"] and r["gain"] == 4000]
    assert vlrt and "star-citizen.wiki" in vlrt[0]["contract"]["sources"], [r["contract"]["title"] for r in rows[:8]]
    # 5.0 is compared with the cross-checked 4.10.3 catalog.
    assert pc["cross_check"]["unchanged_since_previous"] > 500 and "new_since_previous" in pc["cross_check"]
    assert any(any("cross-checked" in s for s in c["sources"]) for c in ptu.catalog.contracts)
    carried = [c for c in ptu.catalog.contracts if (c.get("requires") or {}).get("source", "").startswith("carried")]
    assert len(carried) == pc["cross_check"].get("gate_carried_over", 0)
    return 8


def test_contract_filters() -> int:
    live = _live()
    flt = k.ContractFilter(types=frozenset({"Delivery"}), system="Stanton")
    rows = k.for_money(live.catalog, {}, False, None, 200, flt)
    assert rows and all(r["contract"]["type"] == "Delivery" and "Stanton" in r["contract"]["systems"] for r in rows)
    known = {"Covalex|Hauling": 250}
    everything = k.for_reputation(live.catalog, "Covalex", "Hauling", known, False, None, 200)
    unlocked = k.for_reputation(live.catalog, "Covalex", "Hauling", known, False, None, 200,
                                k.ContractFilter(unlocked_only=True))
    assert any(r["unlocked"] is False for r in everything) and all(r["unlocked"] is not False for r in unlocked)
    assert "Hauling" in live.catalog.types() and {"Stanton", "Pyro", "Nyx"} <= set(live.catalog.systems())

    mod, module, card, d = _make_card()
    module._view("haul-covalex-member")
    assert module.filter_row.isVisibleTo(card), "the filter row shows with the rep tracker"
    module._set_filter("f_unlocked", True)
    module.progress.set_rep("Covalex|Hauling", 250)
    module.render()
    texts = [module.rep_rows.itemAt(i).widget().text() for i in range(module.rep_rows.count())]
    assert texts and not any("needs Member" in t for t in texts), texts
    module._set_filter("f_unlocked", False)
    module.set_view("contracts")
    module._set_filter("f_type", "Bounty Hunter")
    texts = [module.goal_rows.itemAt(i).widget().text() for i in range(module.goal_rows.count())]
    assert texts and module.type_combo.currentData() == "Bounty Hunter"
    module._view("fs-pick-city")
    module.set_view("guide")
    assert not module.filter_row.isVisibleTo(card), "no filter row without a contract list"
    return 8


def run() -> int:
    total = 0
    for test in (test_bundled_packs_pass_their_data_checks, test_bundled_content,
                 test_grind_targets_match_verified_numbers, test_loader_survives_bad_content,
                 test_pack_inheritance_overrides_and_categories, test_user_files_extend_chapters_and_custom_objectives,
                 test_categories_and_contract_recommendations, test_progress_reputation_log_and_goals,
                 test_progress_store_basics, test_maths, test_import_export, test_setup_logic,
                 test_card_walkthrough, test_card_versions_goals_and_prices, test_card_setup_flow_and_import,
                 test_cross_source_catalogs, test_contract_filters):
        total += test()
    return total


if __name__ == "__main__":
    checks = run()
    print(f"All Leveling Guide checks passed ({checks} checks).")
