"""Runs each module's refresh: the error boundary, the network wait off the
GUI thread, the refresh timer, and pausing that timer while the cards
can't be seen.

A module that implements `refresh_job()` (see host/module_base.py) has its
network call run on a worker thread through host/background.py, then
`finish_refresh()` on the GUI thread. A module that doesn't keeps the plain
synchronous `refresh()` path.
"""
import logging
import time

from PySide6.QtCore import QTimer

from host.api_client import RATE_LIMIT_RETRY_COOLDOWN_S, UexRateLimitError
from host.background import run_in_background

logger = logging.getLogger("mobioverlay.refresh")

# Soft, diagnostic-only watchdog for work that runs on the GUI thread —
# there's no preemptive timeout, it just makes a slow module visible in
# the log instead of "the app feels laggy" with no lead.
SLOW_CALL_WARN_SECONDS = 2.0


def timed_call(module, label, fn):
    start = time.monotonic()
    result = fn()
    elapsed = time.monotonic() - start
    if elapsed > SLOW_CALL_WARN_SECONDS:
        logger.warning(
            "Module '%s' %s took %.1fs on the UI thread (see docs/ARCHITECTURE.md, module contract)",
            getattr(module, "module_id", "?"), label, elapsed,
        )
    return result


class ModuleRefresher:
    """One per loaded module. `refresh()` is what the module gets as
    `request_refresh`, what the timer calls, and what RETRY calls."""

    def __init__(self, module, card, interval_s: float):
        self.module = module
        self.card = card
        self._interval_ms = int(interval_s * 1000) if interval_s > 0 else 0
        self._timer = QTimer()
        self._timer.timeout.connect(self.refresh)
        # Bumped by every refresh, so a slow response that a newer refresh
        # (the user picked another commodity) has superseded is dropped
        # instead of overwriting the newer result.
        self._generation = 0
        self._last_started: float | None = None
        self._paused = False

    def start(self):
        self.refresh()
        if self._interval_ms:
            self._timer.start(self._interval_ms)

    def stop(self):
        self._timer.stop()
        self._generation += 1

    def refresh(self):
        self._last_started = time.monotonic()
        self._generation += 1
        generation = self._generation
        try:
            make_job = getattr(self.module, "refresh_job", None)
            job = timed_call(self.module, "refresh_job()", make_job) if make_job else None
            if job is None:
                timed_call(self.module, "refresh()", self.module.refresh)
                self._succeeded()
                return
        except Exception as exc:
            self._failed(exc)
            return
        run_in_background(
            job,
            lambda data: self._job_done(generation, data),
            lambda exc: self._job_failed(generation, exc),
        )

    def _job_done(self, generation, data):
        if generation != self._generation:
            return
        try:
            timed_call(self.module, "finish_refresh()", lambda: self.module.finish_refresh(data))
        except Exception as exc:
            self._failed(exc)
            return
        self._succeeded()

    def _job_failed(self, generation, exc):
        if generation == self._generation:
            self._failed(exc)

    def _succeeded(self):
        self.card.clear_error()

    def _failed(self, exc):
        logger.error(
            "Module '%s' refresh failed", self.module.module_id,
            exc_info=(type(exc), exc, exc.__traceback__),
        )
        cooldown = RATE_LIMIT_RETRY_COOLDOWN_S if isinstance(exc, UexRateLimitError) else 0
        self.card.set_error(str(exc), retry_callback=self.refresh, cooldown_s=cooldown)

    def set_paused(self, paused: bool):
        """Stop the timer while the cards are hidden (stowed or minimized),
        so a stowed overlay makes no UEX calls while the user plays. On
        resume, refresh at once if a tick was missed. Modules whose output
        stays on screen while the cards are hidden (mobiThrottle's bar)
        opt out with `pause_when_hidden = False`."""
        if not self._interval_ms or not getattr(self.module, "pause_when_hidden", True):
            return
        if paused == self._paused:
            return
        self._paused = paused
        if paused:
            self._timer.stop()
            return
        overdue = (
            self._last_started is None
            or (time.monotonic() - self._last_started) * 1000 >= self._interval_ms
        )
        self._timer.start(self._interval_ms)
        if overdue:
            self.refresh()
