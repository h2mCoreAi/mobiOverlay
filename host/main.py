"""mobiOverlay entry point."""
import ctypes
import logging
import re
import sys
from pathlib import Path

# Allow `python host/main.py` to resolve the `host` and `modules` packages.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from host.config import Config


def _maybe_allocate_console():
    """Debug feature: Settings > Debug Console (host/config.py's
    ui.show_console). Only does anything meaningful for the packaged exe
    (mobioverlay.spec builds console=False, so stdout/stderr normally go
    nowhere and every log line is silently dropped) or a source run
    launched with no console already attached (e.g. via a shortcut).
    Running `python host/main.py` from an actual terminal already has a
    console — GetConsoleWindow() catches that and this becomes a no-op.
    Must run before logging.basicConfig() (which grabs sys.stderr at call
    time) and before anything else prints or logs.
    """
    try:
        show_console = Config().data.get("ui", {}).get("show_console", False)
    except Exception:
        show_console = False
    if not show_console or sys.platform != "win32":
        return
    kernel32 = ctypes.windll.kernel32
    if kernel32.GetConsoleWindow():
        return  # already attached to one
    if not kernel32.AllocConsole():
        return
    sys.stdout = open("CONOUT$", "w", encoding="utf-8", errors="replace")
    sys.stderr = open("CONOUT$", "w", encoding="utf-8", errors="replace")
    sys.stdin = open("CONIN$", "r", encoding="utf-8", errors="replace")


_maybe_allocate_console()

from PySide6.QtCore import QTimer
from PySide6.QtGui import QFontDatabase
from PySide6.QtWidgets import QApplication

import time

from host import theme
from host.api_client import UexApiClient
from host.card import Card
from host.main_window import MainWindow
from host.module_loader import discover_modules
from host.splash import show_splash, set_status

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


def _plain_text(html_or_text: str) -> str:
    """Module display_name values are rich HTML (the mobi<Name> branding —
    see docs/DECISIONS.md) but QSplashScreen.showMessage() renders plain
    text only, so a raw display_name would print its literal <span> tags."""
    return re.sub(r"<[^>]+>", "", html_or_text)


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


def _install_excepthook():
    """PySide6 does not stop the process on an exception raised inside a Qt
    slot/callback (button click, timer, drag handler, hotkey signal) — it
    just prints to stderr via sys.excepthook, which the packaged exe
    (console=False) sends nowhere, so these were invisible AND unlogged.
    Only module refresh() has its own boundary (wrap_refresh); this covers
    everything else so a bug in, say, a drag handler degrades instead of
    silently vanishing.
    """
    def _hook(exc_type, exc_value, exc_tb):
        logger.error("Unhandled exception", exc_info=(exc_type, exc_value, exc_tb))
    sys.excepthook = _hook


def main():
    _install_excepthook()
    startup_start = time.monotonic()
    app = QApplication(sys.argv)
    # MainWindow uses Qt.Tool (see main_window.py), which Qt excludes from
    # its "last window" tracking — so without this, closing any ordinary
    # Qt.Window a module opens (e.g. Logistics Hub's popout/detail windows)
    # looks to Qt like the last real window closed, and quits the whole app
    # out from under the still-open, still-Qt.Tool main window.
    app.setQuitOnLastWindowClosed(False)

    splash = show_splash()
    app.processEvents()

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

    def _on_module_loading(name):
        set_status(splash, f"Loading {name.replace('_', ' ').title()}...")

    discover_start = time.monotonic()
    modules = discover_modules(api_client, config, on_module_loading=_on_module_loading)
    logger.info("discover_modules() took %.2fs total", time.monotonic() - discover_start)
    if not modules:
        logger.warning("No modules loaded — the overlay will show an empty container.")

    timers = []  # keep references alive
    for module in modules:
        set_status(splash, f"Starting {_plain_text(module.display_name)}...")
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
        if interval_s:
            timer = QTimer()
            timer.timeout.connect(safe_refresh)
            timer.start(interval_s * 1000)
            timers.append(timer)

    def _shutdown_modules():
        for module in modules:
            try:
                module.shutdown()
            except Exception:
                logger.exception("Module '%s' shutdown() failed", getattr(module, "module_id", "?"))
    app.aboutToQuit.connect(_shutdown_modules)

    window.show()
    splash.finish(window)
    logger.info("Startup (app creation to window.show()) took %.2fs total", time.monotonic() - startup_start)

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
