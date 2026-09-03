"""mobiOverlay entry point."""
import logging
import sys
from pathlib import Path

# Allow `python host/main.py` to resolve the `host` and `modules` packages.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from PySide6.QtCore import QTimer
from PySide6.QtGui import QFontDatabase
from PySide6.QtWidgets import QApplication

from host.api_client import UexApiClient
from host.config import Config
from host.main_window import MainWindow
from host.module_loader import discover_modules

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
logger = logging.getLogger("mobioverlay")

FONTS_DIR = Path(__file__).resolve().parent / "assets" / "fonts"
DEFAULT_REFRESH_SECONDS = 300


def load_fonts():
    for font_file in FONTS_DIR.glob("*.ttf"):
        font_id = QFontDatabase.addApplicationFont(str(font_file))
        if font_id == -1:
            logger.warning("Failed to load bundled font: %s", font_file.name)


def wrap_refresh(module, card):
    def safe_refresh():
        try:
            module.refresh()
            card.clear_error()
        except Exception as exc:
            logger.exception("Module '%s' refresh failed", module.module_id)
            card.set_error(str(exc), retry_callback=safe_refresh)
    return safe_refresh


def main():
    app = QApplication(sys.argv)
    load_fonts()

    config = Config()
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
        card = module.create_card(window.card_container)
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
