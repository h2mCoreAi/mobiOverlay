"""Regression suite for host/refresh.py: module refreshes run their network
part off the GUI thread, a superseded response is dropped, errors (incl.
the rate-limit RETRY cooldown) reach the card, and the refresh timer
pauses while the cards are hidden.

No network, no visible window. Plain asserts, run directly:
    python tests/test_module_refresher.py
"""
import os
import sys
import threading
import time
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from PySide6.QtCore import QCoreApplication

from host.api_client import RATE_LIMIT_RETRY_COOLDOWN_S, UexRateLimitError
from host.refresh import ModuleRefresher

app = QCoreApplication.instance() or QCoreApplication(sys.argv)


class FakeCard:
    def __init__(self):
        self.error = None
        self.cooldown = None
        self.cleared = 0

    def set_error(self, message, retry_callback=None, cooldown_s=0):
        self.error, self.cooldown = message, cooldown_s

    def clear_error(self):
        self.error = None
        self.cleared += 1


class AsyncModule:
    module_id = "fake_async"

    def __init__(self):
        self.applied = []
        self.job_threads = []
        self.next_value = "a"
        self.fail_with = None
        self.gate = None  # threading.Event the job waits on, if set

    def refresh_job(self):
        value, fail, gate = self.next_value, self.fail_with, self.gate

        def job():
            self.job_threads.append(threading.current_thread() is threading.main_thread())
            if gate is not None:
                gate.wait(5)
            if fail is not None:
                raise fail
            return value
        return job

    def finish_refresh(self, data):
        self.applied.append(data)


class SyncModule:
    module_id = "fake_sync"

    def __init__(self):
        self.calls = 0

    def refresh(self):
        self.calls += 1


def wait_for(predicate, timeout=5.0):
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        QCoreApplication.processEvents()
        if predicate():
            return True
        time.sleep(0.01)
    return False


def run() -> int:
    checks = 0

    module, card = AsyncModule(), FakeCard()
    refresher = ModuleRefresher(module, card, interval_s=60)
    refresher.refresh()
    assert module.applied == [], "finish_refresh ran before the job could have finished on a worker"
    assert wait_for(lambda: module.applied == ["a"]), "background result never delivered"
    assert module.job_threads == [False], "job ran on the GUI thread"
    assert card.cleared == 1
    checks += 1

    # A slow response superseded by a newer refresh is dropped.
    gate = threading.Event()
    module.gate, module.next_value = gate, "slow"
    refresher.refresh()
    module.gate, module.next_value = None, "fast"
    refresher.refresh()
    assert wait_for(lambda: module.applied[-1] == "fast")
    gate.set()
    wait_for(lambda: False, timeout=0.3)
    assert "slow" not in module.applied, "stale response overwrote a newer one"
    checks += 1

    module.fail_with = RuntimeError("boom")
    refresher.refresh()
    assert wait_for(lambda: card.error == "boom") and card.cooldown == 0
    checks += 1

    module.fail_with = UexRateLimitError("rate limited")
    refresher.refresh()
    assert wait_for(lambda: card.error == "rate limited")
    assert card.cooldown == RATE_LIMIT_RETRY_COOLDOWN_S, "rate-limit error should start the RETRY cooldown"
    module.fail_with = None
    checks += 1

    sync_module, sync_card = SyncModule(), FakeCard()
    sync_refresher = ModuleRefresher(sync_module, sync_card, interval_s=60)
    sync_refresher.refresh()
    assert sync_module.calls == 1 and sync_card.cleared == 1, "module without refresh_job should refresh synchronously"
    checks += 1

    # Pause/resume: timer stops while hidden; resume refreshes only if a tick was missed.
    before_start = len(module.applied)
    refresher.start()
    assert refresher._timer.isActive()
    assert wait_for(lambda: len(module.applied) == before_start + 1), "start() should refresh at once"
    refresher.set_paused(True)
    assert not refresher._timer.isActive(), "timer kept running while hidden"
    count = len(module.applied)
    wait_for(lambda: False, timeout=0.2)
    refresher.set_paused(False)
    assert refresher._timer.isActive()
    wait_for(lambda: False, timeout=0.2)
    assert len(module.applied) == count, "resumed with no missed tick but refreshed anyway"
    refresher.set_paused(True)
    refresher._last_started -= 61
    refresher.set_paused(False)
    assert wait_for(lambda: len(module.applied) == count + 1), "missed tick wasn't caught up on resume"
    checks += 1

    module.pause_when_hidden = False
    refresher.set_paused(True)
    assert refresher._timer.isActive(), "pause_when_hidden=False module was paused"
    checks += 1

    refresher.stop()
    print(f"{checks}/{checks} module refresher checks passed")
    return 0


if __name__ == "__main__":
    sys.exit(run())
