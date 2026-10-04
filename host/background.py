"""Run a blocking call (a UEX request) off the GUI thread and deliver its
result back on it.

The scan loops in Commodity Prices, Trade Route Optimizer and Multi-Commodity
Finder used to call `api.get()` straight from a QTimer tick, so the whole UI
froze for the length of every request (hundreds of them per scan). This keeps
their pacing and state machines as they were but moves the wait to a small
thread pool, without an asyncio/qasync dependency.

Must first be used from the GUI thread (that's where results are delivered).
"""
import atexit
import logging
from concurrent.futures import ThreadPoolExecutor

from PySide6.QtCore import QObject, Signal

logger = logging.getLogger("mobioverlay.background")

MAX_WORKERS = 2


class _Dispatcher(QObject):
    _done = Signal(object)

    def __init__(self):
        super().__init__()
        self._done.connect(self._deliver)
        self._pool = ThreadPoolExecutor(max_workers=MAX_WORKERS, thread_name_prefix="mobi-bg")
        atexit.register(self._pool.shutdown, wait=False, cancel_futures=True)

    def submit(self, fn, on_result, on_error):
        def work():
            try:
                outcome = (fn(), None)
            except Exception as exc:
                outcome = (None, exc)
            self._done.emit((on_result, on_error, outcome))
        self._pool.submit(work)

    def _deliver(self, payload):
        on_result, on_error, (result, exc) = payload
        try:
            if exc is None:
                on_result(result)
            elif on_error is not None:
                on_error(exc)
            else:
                logger.warning("background call failed: %s", exc)
        except Exception:
            logger.exception("background callback raised")


_dispatcher: _Dispatcher | None = None


def run_in_background(fn, on_result, on_error=None):
    """Call `fn()` on a worker thread; then `on_result(value)` — or
    `on_error(exception)` if it raised — on the GUI thread."""
    global _dispatcher
    if _dispatcher is None:
        _dispatcher = _Dispatcher()
    _dispatcher.submit(fn, on_result, on_error)
