"""mobiOverlay entry point."""
import logging
import sys
from pathlib import Path

# Allow `python host/main.py` to resolve the `host` and `modules` packages.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from PySide6.QtCore import QTimer
from PySide6.QtGui import QFontDatabase
from PySide6.QtWidgets import QApplication

import time

from host import theme
from host.api_client import UexApiClient
from host.card import Card
from host.config import Config
from host.main_window import MainWindow
from host.module_loader import discover_modules

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
logger = logging.getLogger("mobioverlay")

FONTS_DIR = Path(__file__).resolve().parent / "assets" / "fonts"
DEFAULT_REFRESH_SECONDS = 300
# Modules run synchronously on the GUI thread (see docs/ARCHITECTURE.md) —
# there's no preemptive timeout possible without a threading/process
# redesign, so this is a soft, diagnostic-only watchdog: it logs a warning
# after the fact so a slow module is visible in the log rather than just
# manifesting as "the app feels laggy" with no lead.
SLOW_CALL_WARN_SECONDS = 2.0


def load_fonts():
    for font_file in FONTS_DIR.glob("*.ttf"):
        font_id = QFontDatabase.addApplicationFont(str(font_file))
        if font_id == -1:
            logger.warning("Failed to load bundled font: %s", font_file.name)


def _timed_call(module, label, fn):
    start = time.monotonic()
    result = fn()
    elapsed = time.monotonic() - start
    if elapsed > SLOW_CALL_WARN_SECONDS:
        logger.warning(
            "Module '%s' %s took %.1fs — this blocks the whole UI thread "
            "while it runs (see docs/ARCHITECTURE.md, module contract)",
            getattr(module, "module_id", "?"), label, elapsed,
        )
    return result


def wrap_refresh(module, card):
    def safe_refresh():
        try:
            _timed_call(module, "refresh()", module.refresh)
            card.clear_error()
        except Exception as exc:
            logger.exception("Module '%s' refresh failed", module.module_id)
            card.set_error(str(exc), retry_callback=safe_refresh)
    return safe_refresh


def safe_create_card(module, parent):
    """create_card() runs once at startup, before wrap_refresh's error
    boundary exists for this module — an unguarded exception or a bad
    return type here used to propagate straight out of main() and crash
    the whole app before any other module got a chance to load."""
    try:
        card = _timed_call(module, "create_card()", lambda: module.create_card(parent))
    except Exception:
        logger.exception(
            "Module '%s' create_card() raised — skipping this module",
            getattr(module, "module_id", "?"),
        )
        return None
    if not isinstance(card, Card):
        logger.error(
            "Module '%s' create_card() returned %r, expected a host.card.Card "
            "— skipping this module",
            getattr(module, "module_id", "?"), type(card).__name__,
        )
        return None
    return card


def main():
    app = QApplication(sys.argv)
    load_fonts()

    config = Config()
    # Must happen before MainWindow (and before any module is imported) —
    # every stylesheet-building call reads theme.FONT_SCALE at the moment
    # it runs, so this needs to be set first, once, for the whole session.
    theme.set_font_scale(config.data["ui"]["font_scale"])

    api_client = UexApiClient(
        base_url=config.data["api"]["uex_base_url"],
        token=config.data["api"]["uex_token"],
    )

    window = MainWindow(config)
    modules = discover_modules(api_client, config)
    if not modules:
        logger.warning("No modules loaded — the overlay will show an empty container.")

    timers = []  # keep references alive
    for module in modules:
        card = safe_create_card(module, window.card_container)
        if card is None:
            continue
        # Module just populated card.body; the card computed its size before
        # that (CardContainer has no layout manager, so nothing resizes it
        # automatically). Force the layout to recompute now.
        card.apply_size()
        safe_refresh = wrap_refresh(module, card)
        module.request_refresh = safe_refresh

        safe_refresh()  # initial fetch

        interval_s = module.settings.get("refresh_interval_seconds", DEFAULT_REFRESH_SECONDS)
        timer = QTimer()
        timer.timeout.connect(safe_refresh)
        timer.start(interval_s * 1000)
        timers.append(timer)

    window.show()

    # Belt-and-suspenders: re-apply sizing once more after the window has
    # actually been shown and painted once. On some runs the very first
    # paint used a size computed before fonts/layout had fully settled,
    # leaving a card looking header-only until collapse/expand forced a
    # repaint. Re-running apply_size() post-show has fixed that.
    def _resettle_cards():
        for card in window.card_container.cards.values():
            card.apply_size()

    QTimer.singleShot(50, _resettle_cards)

    sys.exit(app.exec())


if __name__ == "__main__":
    main()
