"""Tests for host/background.py and the scan loops that now use it: results
arrive on the GUI thread, a slow request doesn't freeze the event loop, and a
rate-limit error stops the scan with a Retry cooldown.

Offscreen Qt, a fake API, no network:
    python tests/test_background_scans.py
"""
import importlib.util
import os
import sys
import tempfile
import threading
import time
from pathlib import Path
from unittest.mock import MagicMock

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QApplication

from host import background
from host.api_client import UexApiError, UexRateLimitError
from host.card_container import CardContainer
from host.config import Config

app = QApplication.instance() or QApplication([])


def _spin_until(cond, timeout=10.0):
    end = time.monotonic() + timeout
    while not cond() and time.monotonic() < end:
        app.processEvents()
        time.sleep(0.005)
    return cond()


def test_result_and_error_delivered_on_gui_thread() -> int:
    gui = threading.get_ident()
    got = {}

    def ok(v):
        got["ok"] = (v, threading.get_ident())

    def bad(e):
        got["err"] = (e, threading.get_ident())

    worker = {}
    def work():
        worker["tid"] = threading.get_ident()
        return 42

    background.run_in_background(work, ok, bad)
    background.run_in_background(lambda: (_ for _ in ()).throw(UexApiError("boom")), ok, bad)
    assert _spin_until(lambda: "ok" in got and "err" in got), "callbacks never arrived"
    assert got["ok"] == (42, gui), "result wasn't delivered on the GUI thread"
    assert isinstance(got["err"][0], UexApiError) and got["err"][1] == gui, "error wasn't delivered on the GUI thread"
    assert worker["tid"] != gui, "the call ran on the GUI thread"
    return 4


def _load(name):
    spec = importlib.util.spec_from_file_location(f"t_{name}", ROOT / "modules" / name / "module.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _make_mcf(api):
    mcf = _load("multi_commodity_finder")
    tmp = Path(tempfile.mkdtemp()) / "config.json"
    config = Config(path=tmp)
    module = mcf.MultiCommodityFinderModule(api, config, MagicMock())
    card = module.create_card(CardContainer(config))
    module._selected_commodities = lambda: ["Gold", "Iron", "Quartz"]
    done = {"finished": False}
    module._finish_scan = lambda: (module._scan_timer.stop(), setattr(module, "_scan_timer", None), done.update(finished=True))
    return mcf, module, card, done


class _SlowApi:
    def __init__(self, fail_on=None, rate_limit_on=None):
        self.calls = []
        self.fail_on = fail_on
        self.rate_limit_on = rate_limit_on

    def get(self, endpoint, params=None):
        name = params["commodity_name"]
        self.calls.append(name)
        time.sleep(0.15)
        if name == self.rate_limit_on:
            raise UexRateLimitError("limit")
        if name == self.fail_on:
            raise UexApiError("down")
        return [{"commodity_name": name, "price_buy": 1}]


def test_scan_keeps_event_loop_responsive_and_collects_rows() -> int:
    api = _SlowApi(fail_on="Iron")
    mcf, module, card, done = _make_mcf(api)
    ticks = []
    probe = QTimer()
    probe.timeout.connect(lambda: ticks.append(1))
    probe.start(20)
    module._start_scan()
    assert _spin_until(lambda: done["finished"], timeout=20), "scan never finished"
    probe.stop()
    assert api.calls == ["Gold", "Iron", "Quartz"], api.calls
    assert sorted(module._scanned_data) == ["Gold", "Quartz"], "failed commodity should be skipped, others kept"
    # 3 requests x 0.15s: a frozen event loop would tick ~0 times, a free one ~20+
    assert len(ticks) >= 10, f"event loop was blocked during the scan ({len(ticks)} ticks)"
    return 3


def test_rate_limit_stops_scan_with_retry_cooldown() -> int:
    api = _SlowApi(rate_limit_on="Iron")
    mcf, module, card, done = _make_mcf(api)
    module._start_scan()
    assert _spin_until(lambda: module._scan_timer is None, timeout=20), "scan didn't stop on rate limit"
    app.processEvents()
    assert not done["finished"], "scan finished despite a rate limit"
    assert api.calls == ["Gold", "Iron"], f"requests kept firing after the rate limit: {api.calls}"
    assert card.error_widget.isHidden() is False or card.error_message.text() == "limit"
    assert card.error_message.text() == "limit"
    assert not card._retry_btn.isEnabled(), "Retry should be on cooldown after a rate limit"
    return 4


def test_stale_reply_from_cancelled_scan_is_ignored() -> int:
    api = _SlowApi()
    mcf, module, card, done = _make_mcf(api)
    module._start_scan()
    module._scan_step()  # request in flight
    module._scan_generation += 1  # a new scan started
    stale_before = dict(module._scanned_data)
    _spin_until(lambda: False, timeout=0.4)
    assert module._scanned_data == stale_before, "a reply from a superseded scan was applied"
    return 1


def run() -> int:
    checks = 0
    for t in (test_result_and_error_delivered_on_gui_thread,
              test_scan_keeps_event_loop_responsive_and_collects_rows,
              test_rate_limit_stops_scan_with_retry_cooldown,
              test_stale_reply_from_cancelled_scan_is_ignored):
        checks += t()
        print(f"[PASS] {t.__name__}")
    print(f"\n{checks}/{checks} background scan checks passed")
    return checks


if __name__ == "__main__":
    run()
