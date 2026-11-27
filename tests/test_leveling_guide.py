"""Tests for the Leveling Guide module (mobiGuide): bundled content, loader
robustness, progress and custom-objective storage, guide maths, and an
offscreen card walk-through.

Offscreen Qt, temp files, a fake API, no network:
    python tests/test_leveling_guide.py
"""
import importlib.util
import json
import os
import sys
import tempfile
from pathlib import Path
from unittest.mock import MagicMock

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from PySide6.QtWidgets import QApplication

from host.card_container import CardContainer
from host.config import Config
from modules.leveling_guide import guide as g
from modules.leveling_guide.progress import CustomObjectives, ProgressStore

app = QApplication.instance() or QApplication([])
BUNDLED = ROOT / "modules" / "leveling_guide" / "guides"


def _tmpdir() -> Path:
    return Path(tempfile.mkdtemp())


def _write(path: Path, data) -> Path:
    path.write_text(data if isinstance(data, str) else json.dumps(data), encoding="utf-8")
    return path


def _chapter(cid, objectives, order=10):
    return {"schema": 1, "chapter": {"id": cid, "title": cid.title(), "order": order}, "objectives": objectives}


def _obj(oid, **extra):
    base = {"id": oid, "title": oid, "steps": [{"do": "Do it", "done_when": "It is done"}]}
    base.update(extra)
    return base


# ---------------------------------------------------------------------------
def test_bundled_content() -> int:
    guide = g.load_guide([BUNDLED])
    assert guide.errors == [], guide.errors
    objs = guide.objectives
    assert len(guide.chapters) >= 10 and len(objs) >= 50, (len(guide.chapters), len(objs))
    assert len({o.id for o in objs}) == len(objs), "duplicate objective ids"
    for o in objs:
        assert o.sources, f"{o.id} has no sources"
        assert all(s.startswith("https://") for s in o.sources), f"{o.id} has a non-https source"
        assert o.steps and all(s.do and s.done_when for s in o.steps), f"{o.id} has an incomplete step"
        for r in o.requires:
            assert guide.get(r) is not None, f"{o.id} requires unknown {r}"
    orders = [c.order for c in guide.chapters]
    assert orders == sorted(orders), "chapters out of order"
    # Every chapter file states the patch it was verified on.
    assert all(c.patch == "4.10.3" for c in guide.chapters), [c.patch for c in guide.chapters]
    # The outlaw chapter is all illegal and all optional.
    outlaw = guide.chapter("outlaw")
    assert outlaw and all(o.unlawful and o.optional for o in outlaw.objectives)
    return 6


def test_grind_targets_match_verified_numbers() -> int:
    """Grind targets come from (rank threshold - previous threshold) /
    reputation per contract, per docs/leveling-guide/verification.md. This
    pins them so an edit can't silently drift from the verified data."""
    guide = g.load_guide([BUNDLED])
    expected = {
        "haul-covalex-junior": (250, 500),      # one Trainee Rank haul
        "haul-covalex-member": (5250 - 250, 500),
        "haul-covalex-experienced": (27750 - 5250, 1000),
        "haul-covalex-senior": (77750 - 27750, 2000),
        "haul-covalex-master": (237750 - 77750, 4000),
        "bhg-junior": (3000, 4000),
        "bhg-guild-member": (10000 - 3000, 1000),
        "bhg-senior": (40000 - 10000, 2000),
        "bhg-veteran": (200000 - 40000, 4000),
        "bhg-steward": (480000 - 200000, 8000),
        "fox-jr": (800 - 200, 100),
        "fox-contractor": (2200 - 800, 100),
        "fox-sr": (5800 - 2200, 150),
        "fox-veteran": (15000 - 5800, 200),
        "salv-jr": (800 - 100, 100),
        "salv-contractor": (2200 - 800, 100),
        "ids-jr": (800 - 100, 100),
        "ids-contractor": (2200 - 800, 150),
        "ids-sr": (5800 - 2200, 250),
        "ids-veteran": (15000 - 5800, 250),
        "recco-associate": (2400 - 800, 200),
        "recco-trusted": (6000 - 2400, 200),
        "recco-prestige1": (10800 - 6000, 350),
        "recco-prestige2": (30000 - 10800, 350),
        "recco-prestige3": (69600 - 30000, 350),
    }
    for oid, (points, per) in expected.items():
        obj = guide.get(oid)
        assert obj is not None, oid
        assert obj.kind == "grind", oid
        want = g.contracts_needed(points, per)
        assert obj.goal_target == want, f"{oid}: target {obj.goal_target}, expected {want}"
    # Rank thresholds on rank-up objectives match the game's ladders.
    ladders = {"Junior": 250, "Member": 5250, "Experienced": 27750, "Senior": 77750, "Master": 237750,
               "Junior Guild Member": 3000, "Guild Member": 10000, "Senior Guild Member": 40000,
               "Veteran Guild Member": 200000, "Guild Steward": 480000, "Jr. Contractor": 800,
               "Contractor": 2200, "Sr. Contractor": 5800, "Veteran Contractor": 15000,
               "Associate": 2400, "Trusted Associate": 6000, "Prestige 1": 10800, "Prestige 2": 30000,
               "Prestige 3": 69600, "Rookie": 50, "Probationary Guild Member": 1}
    checked = 0
    for o in guide.objectives:
        if o.reputation and o.reputation.get("rank") in ladders:
            assert o.reputation["points"] == ladders[o.reputation["rank"]], o.id
            checked += 1
    assert checked >= 20, checked
    return len(expected) + 1


def test_loader_survives_bad_content() -> int:
    d = _tmpdir()
    _write(d / "01-good.json", _chapter("good", [_obj("a"), _obj("b", requires=["a"])]))
    _write(d / "02-broken.json", "{not json")
    _write(d / "03-nochapter.json", {"schema": 1, "objectives": [_obj("x")]})
    _write(d / "04-bad-objectives.json", _chapter("bad", [
        {"id": "no-steps", "title": "No steps", "steps": []},
        _obj("bad-kind", kind="dance"),
        _obj("grind-no-goal", kind="grind"),
        _obj("buy-no-ship", kind="purchase"),
        _obj("a"),                                   # duplicate id
        _obj("unknown-req", requires=["nope"]),
        _obj("cyc1", requires=["cyc2"]),
        _obj("cyc2", requires=["cyc1"]),
    ], order=20))
    _write(d / "05-schema.json", {"schema": 99, "chapter": {"id": "z", "title": "Z"}, "objectives": []})
    guide = g.load_guide([d])
    ids = {o.id for o in guide.objectives}
    assert ids == {"a", "b", "unknown-req", "cyc1", "cyc2"}, ids
    text = "\n".join(guide.errors)
    for needle in ("02-broken.json", "03-nochapter.json", "no-steps", "bad-kind", "grind-no-goal",
                   "buy-no-ship", "duplicate", "requires unknown", "cycle", "unsupported schema"):
        assert needle in text, f"missing error about {needle}:\n{text}"
    assert guide.get("unknown-req").requires == []
    assert not (guide.get("cyc1").requires and guide.get("cyc2").requires), "cycle not broken"
    assert g.next_objective(guide, set(), True, True).id == "a"
    return 5


def test_user_files_extend_chapters_and_custom_objectives() -> int:
    bundled, user = _tmpdir(), _tmpdir()
    _write(bundled / "01.json", _chapter("hauling", [_obj("h1")]))
    _write(user / "extra.json", _chapter("hauling", [_obj("h2")]))
    _write(user / "new.json", _chapter("racing", [_obj("r1")], order=5))
    custom_file = _tmpdir() / "custom.json"
    custom = CustomObjectives(custom_file)
    a = custom.add("Buy a Cutlass", [{"do": "Buy it", "done_when": "Owned"}], chapter_id="hauling")
    b = custom.add("Race Old Vanderval", [{"do": "Race", "done_when": "Finished"}], kind="grind",
                   goal_target=3, goal_unit="races")
    c = custom.add("Buy a Cutlass", [{"do": "Again", "done_when": "Owned"}], chapter_id="nowhere")
    assert a["id"] != c["id"], "custom ids must be unique"
    guide = g.load_guide([bundled, user], custom_file)
    assert guide.errors == [], guide.errors
    assert [c.id for c in guide.chapters] == ["racing", "hauling", g.CUSTOM_CHAPTER_ID]
    assert [o.id for o in guide.chapter("hauling").objectives] == ["h1", "h2", a["id"]]
    mine = guide.chapter(g.CUSTOM_CHAPTER_ID).objectives
    assert {o.id for o in mine} == {b["id"], c["id"]} and all(o.custom for o in mine)
    assert guide.get(b["id"]).goal_target == 3
    assert CustomObjectives(custom_file).remove(a["id"]) is True
    assert g.load_guide([bundled, user], custom_file).get(a["id"]) is None
    return 6


def test_progress_store() -> int:
    path = _tmpdir() / "progress.json"
    p = ProgressStore(path)
    p.set_done("a")
    p.set_step("b", 2)
    assert p.add_count("c", 3) == 3 and p.add_count("c", -10) == 0, "count must not go negative"
    p.set_skipped("d")
    p.set_current("b")
    q = ProgressStore(path)
    assert q.done_ids() == {"a"} and q.skipped_ids() == {"d"} and q.passed_ids() == {"a", "d"}
    assert q.step("b") == 2 and q.current == "b"
    q.set_done("d")
    assert q.skipped_ids() == set() and "d" in q.done_ids(), "finishing a skipped objective un-skips it"
    q.reset("a")
    assert not q.is_done("a")
    q.reset_all()
    assert ProgressStore(path).done_ids() == set()
    _write(path, "{garbage")
    r = ProgressStore(path)
    assert r.done_ids() == set()
    assert list(path.parent.glob("progress.json.corrupt-*")), "corrupt file not quarantined"
    return 6


def test_maths_and_prices() -> int:
    assert g.level_for_xp(0) == (1, 0, 200)
    assert g.level_for_xp(199) == (1, 199, 200)
    assert g.level_for_xp(200) == (2, 0, 250)
    assert g.level_for_xp(450) == (3, 0, 300)
    rows = [{"vehicle_name": "Vulture", "price_buy": 2646000, "terminal_name": "Buy and Fly Checkmate"},
            {"vehicle_name": "Vulture", "price_buy": 2513700, "terminal_name": "New Deal Lorville"},
            {"vehicle_name": "Vulture Renegade", "price_buy": 1, "terminal_name": "Elsewhere"},
            {"vehicle_name": "Vulture", "price_buy": None, "terminal_name": "Broken"}]
    best = g.cheapest_listing(rows, "vulture")
    assert best["terminal_name"] == "New Deal Lorville", best
    assert g.cheapest_listing(rows, "Golem") is None
    assert g.contracts_needed(4700, 500) == 10 and g.contracts_needed(1, 4000) == 1
    guide = g.load_guide([BUNDLED])
    lawful_next = g.next_objective(guide, set(), True, False)
    assert lawful_next.id == "fs-pick-city"
    everything = {o.id for o in guide.objectives}
    assert g.next_objective(guide, everything, True, True) is None
    return 7


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
                {"vehicle_name": "Golem", "price_buy": 1005480, "terminal_name": "New Deal Lorville"}]


def _load_module():
    spec = importlib.util.spec_from_file_location("t_leveling_guide", ROOT / "modules" / "leveling_guide" / "module.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _make_card(api=None):
    mod = _load_module()
    d = _tmpdir()
    config = Config(path=d / "config.json")
    module = mod.LevelingGuideModule(api or _FakeApi(), config, MagicMock(),
                                     progress=ProgressStore(d / "progress.json"),
                                     custom=CustomObjectives(d / "custom.json"),
                                     guide_dirs=[BUNDLED])
    card = module.create_card(CardContainer(config))
    return mod, module, card, d


def test_card_walkthrough() -> int:
    mod, module, card, d = _make_card()
    assert module.current_objective().id == "fs-pick-city"
    assert "LVL 1" in module.level_label.text()
    first = module.current_objective()
    for _ in range(len(first.steps)):
        module._on_step_done()
    assert module.progress.is_done("fs-pick-city"), "finishing every step completes the objective"
    assert module.current_objective().id == "fs-tutorial-steps", module.current_objective().id
    assert "XP" in module.xp_label.text() and module.xp_bar.value() == 100

    # Step back and forth inside an objective.
    module._on_step_done()
    assert module.progress.step("fs-tutorial-steps") == 1
    module._on_back()
    assert module.progress.step("fs-tutorial-steps") == 0

    # Skip moves on without XP.
    module._on_skip()
    assert module.current_objective().id == "fs-tutorial-outing"
    assert "fs-tutorial-steps" not in module.progress.done_ids()

    # Grind counter.
    module._view("haul-covalex-member")
    assert module.counter_row.isVisibleTo(card)
    for _ in range(3):
        module._on_count(1)
    module._on_count(-1)
    assert module.progress.count("haul-covalex-member") == 2
    assert module.count_label.text().startswith("2 / 10")

    # Outlaw content is hidden until turned on.
    assert module.guide.get("outlaw-vaughn") is not None
    module._set_option("show_unlawful", False)
    titles = [module.chapter_combo.itemText(i) for i in range(module.chapter_combo.count())]
    assert not any("Outlaw" in t for t in titles), titles
    module._set_option("show_unlawful", True)
    titles = [module.chapter_combo.itemText(i) for i in range(module.chapter_combo.count())]
    assert any("Outlaw" in t for t in titles), titles

    # Compact mode shows one step only.
    module._view("fs-launch-own-ship")
    module._set_option("compact", True)
    module._view("fs-launch-own-ship")
    assert module.steps_layout.count() == 1 and not module.list_container.isVisibleTo(card)
    module._set_option("compact", False)
    return 10


def test_card_prices_and_custom_objective() -> int:
    api = _FakeApi()
    mod, module, card, d = _make_card(api)
    module._view("salv-buy-vulture")
    assert "loading" in module.info_label.text().lower()
    module.refresh()
    assert api.calls == 1 and "2,513,700" in module.info_label.text(), module.info_label.text()
    module.refresh()
    assert api.calls == 1, "fresh prices must not be re-fetched"
    module._view("fs-pick-city")
    module._price_rows = None
    module.refresh()
    assert api.calls == 1, "no fetch when the objective isn't a purchase"

    failing = _FakeApi(fail=True)
    mod2, broken, card2, _ = _make_card(failing)
    broken._view("mining-buy-golem")
    broken.refresh()
    assert "unavailable" in broken.info_label.text().lower(), broken.info_label.text()
    assert not card2.error_widget.isVisibleTo(card2), "a UEX failure must not put the card in its error state"

    obj = module.custom.add("Buy a Cutlass Black", [{"do": "Buy it", "done_when": "Owned"}], chapter_id="salvage",
                            existing_ids={o.id for o in module.guide.objectives})
    module.reload_guide()
    module._view(obj["id"])
    assert module.current_objective().custom and "YOURS" in module.badges_label.text()
    module._on_step_done()
    assert module.progress.is_done(obj["id"])
    return 7


def run() -> int:
    total = 0
    for test in (test_bundled_content, test_grind_targets_match_verified_numbers, test_loader_survives_bad_content,
                 test_user_files_extend_chapters_and_custom_objectives, test_progress_store, test_maths_and_prices,
                 test_card_walkthrough, test_card_prices_and_custom_objective):
        total += test()
    return total


if __name__ == "__main__":
    checks = run()
    print(f"All Leveling Guide checks passed ({checks} checks).")
