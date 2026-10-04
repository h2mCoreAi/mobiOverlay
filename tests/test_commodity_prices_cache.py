"""Commodity Prices restores/saves its RETRIEVE DATA result through
host/price_cache.py (N3): fresh entries resume the countdown, middle-aged ones
are usable but labeled, too-old ones are ignored, and a finished retrieval is
persisted off the GUI thread.

Offscreen Qt, temp SQLite file, no network:
    python tests/test_commodity_prices_cache.py
"""
import importlib.util
import os
import sys
import tempfile
import time
from pathlib import Path
from unittest.mock import MagicMock

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from PySide6.QtWidgets import QApplication

from host.card_container import CardContainer
from host.config import Config
from host.price_cache import PriceCache

app = QApplication.instance() or QApplication([])

_spec = importlib.util.spec_from_file_location("t_cp", ROOT / "modules" / "commodity_prices" / "module.py")
cp = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(cp)

DATA = {"Gold": [{"commodity_name": "Gold", "id_terminal": 1, "price_buy": 5, "price_sell": 9, "scu_buy": 10}]}


def _module(age_seconds=None, payload=DATA):
    tmp = Path(tempfile.mkdtemp())
    cache = PriceCache(tmp / "price_cache.sqlite3")
    if age_seconds is not None:
        cache.save(cp.PRICE_CACHE_KEY, payload, fetched_at=time.time() - age_seconds)
    locations = MagicMock()
    locations.visible_commodity_names.return_value = ["Gold"]
    locations.all_locations.return_value = []
    config = Config(path=tmp / "config.json")
    module = cp.CommodityPricesModule(MagicMock(), config, locations)
    module._price_cache = cache
    module.create_card(CardContainer(config))
    return module, cache


def test_nothing_cached() -> int:
    m, _ = _module()
    assert m._all_commodity_data == {} and not m.profitable_btn.isEnabled()
    return 2


def test_fresh_cache_restored_with_countdown() -> int:
    m, _ = _module(age_seconds=300)
    assert m._all_commodity_data == DATA
    assert m.profitable_btn.isEnabled(), "FIND MOST PROFITABLE should work straight after launch"
    assert m._countdown_timer is not None and m.retrieve_btn.text().startswith("REFRESH IN"), m.retrieve_btn.text()
    assert "saved cache" in m.profitable_btn.toolTip()
    m._stop_countdown()
    return 4


def test_middle_aged_cache_usable_but_refresh_offered() -> int:
    m, _ = _module(age_seconds=cp.REFRESH_CACHE_SECONDS + 600)
    assert m._all_commodity_data == DATA and m.profitable_btn.isEnabled()
    assert m._countdown_timer is None and m.retrieve_btn.text() == "RETRIEVE DATA", "an expired entry must not claim to be fresh"
    assert "min ago" in m.profitable_btn.toolTip()
    return 3


def test_too_old_or_malformed_cache_ignored() -> int:
    m, _ = _module(age_seconds=cp.CACHED_PRICES_MAX_AGE_SECONDS + 60)
    assert m._all_commodity_data == {} and not m.profitable_btn.isEnabled()
    m, _ = _module(age_seconds=60, payload=["not", "a", "dict"])
    assert m._all_commodity_data == {}
    m, _ = _module(age_seconds=-3600)  # timestamp in the future: clock change, don't trust it
    assert m._all_commodity_data == {}
    return 3


def test_finished_retrieval_is_saved() -> int:
    m, cache = _module()
    m._all_commodity_data = dict(DATA)
    m._retrieve_timer = MagicMock()
    m._finish_retrieve()
    end = time.monotonic() + 10
    hit = None
    while time.monotonic() < end and not hit:
        app.processEvents()
        hit = cache.load(cp.PRICE_CACHE_KEY)
        time.sleep(0.01)
    assert hit and hit[1] == DATA, "finished retrieval wasn't persisted"
    assert abs(hit[0] - m._last_retrieve_time) < 1.0
    m._stop_countdown()
    return 2


def run() -> int:
    checks = 0
    for t in (test_nothing_cached, test_fresh_cache_restored_with_countdown,
              test_middle_aged_cache_usable_but_refresh_offered,
              test_too_old_or_malformed_cache_ignored, test_finished_retrieval_is_saved):
        checks += t()
        print(f"[PASS] {t.__name__}")
    print(f"\n{checks}/{checks} commodity price cache checks passed")
    return checks


if __name__ == "__main__":
    run()
