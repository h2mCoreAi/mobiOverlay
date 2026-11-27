"""mobiOverlay entry point."""
import atexit
import ctypes
import logging
import re
import sys
from pathlib import Path

# Allow `python host/main.py` to resolve the `host` and `modules` packages.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from host.config import Config
from host.single_instance import SingleInstance, SingleInstanceError


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
from host.locations import LocationService
from host.main_window import MainWindow
from host.module_loader import discover_modules
from host.price_cache import PriceCache
from host.refresh import ModuleRefresher, timed_call
from host.services import Services
from host.splash import show_splash, set_status

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
logger = logging.getLogger("mobioverlay")

FONTS_DIR = Path(__file__).resolve().parent / "assets" / "fonts"
DEFAULT_REFRESH_SECONDS = 300


def _plain_text(html_or_text: str) -> str:
    """Module display_name values are rich HTML (the mobi<Name> branding —
    see docs/DECISIONS.md) but the splash screen draws plain text only, so a raw display_name would print its literal <span> tags."""
    return re.sub(r"<[^>]+>", "", html_or_text)


def load_fonts():
    for font_file in FONTS_DIR.glob("*.ttf"):
        font_id = QFontDatabase.addApplicationFont(str(font_file))
        if font_id == -1:
            logger.warning("Failed to load bundled font: %s", font_file.name)


def _refresh_interval_seconds(module) -> float:
    try:
        return float(module.settings.get("refresh_interval_seconds", DEFAULT_REFRESH_SECONDS) or 0)
    except (TypeError, ValueError):
        return DEFAULT_REFRESH_SECONDS


def safe_create_card(module, parent):
    """create_card() runs once at startup, before ModuleRefresher's error
    boundary exists for this module — an unguarded exception or a bad
    return type here used to propagate straight out of main() and crash
    the whole app before any other module got a chance to load."""
    try:
        card = timed_call(module, "create_card()", lambda: module.create_card(parent))
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
    Only module refresh() has its own boundary (host/refresh.py); this covers
    everything else so a bug in, say, a drag handler degrades instead of
    silently vanishing.
    """
    def _hook(exc_type, exc_value, exc_tb):
        logger.error("Unhandled exception", exc_info=(exc_type, exc_value, exc_tb))
    sys.excepthook = _hook


def _set_taskbar_identity():
    """A source run is python.exe to Windows, so its taskbar button grouped
    with every other Python window and showed Python's icon. An explicit
    AppUserModelID gives it its own button and the window's own icon.
    Source runs only: the packaged exe already has its own identity, and
    changing it would split the button from any shortcut the user pinned."""
    if sys.platform != "win32" or getattr(sys, "frozen", False):
        return
    try:
        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID("mobiOverlay.Overlay.Source")
    except (AttributeError, OSError):
        logger.debug("Could not set AppUserModelID", exc_info=True)


def _show_already_running_dialog(message: str):
    """Show a blocking error dialog when another instance is already running.
    Must be called before the main QApplication is created, since that's
    when we detect the conflict. Uses a temporary QApplication just for
    the dialog, then exits."""
    from PySide6.QtWidgets import QApplication, QMessageBox
    temp_app = QApplication(sys.argv)
    box = QMessageBox()
    box.setWindowTitle("mobiOverlay")
    box.setIcon(QMessageBox.Warning)
    box.setText("mobiOverlay is already running")
    box.setInformativeText(message)
    box.setStandardButtons(QMessageBox.Ok)
    box.exec()
    temp_app.quit()
    sys.exit(1)


# Global reference kept alive for the process's lifetime — the lock is
# released when this object is garbage-collected or the process exits.
_instance_lock: SingleInstance | None = None


def main():
    global _instance_lock
    _install_excepthook()

    # Single-instance guard: only one mobiOverlay can run at a time.
    # The global keyboard hook can block game input if a second instance
    # races or the process is killed improperly — see single_instance.py.
    try:
        _instance_lock = SingleInstance()
        _instance_lock.__enter__()
        atexit.register(_instance_lock.__exit__, None, None, None)
    except SingleInstanceError as e:
        _show_already_running_dialog(str(e))
        return

    startup_start = time.monotonic()
    _set_taskbar_identity()
    app = QApplication(sys.argv)
    # Without this, closing any popout/detail window a module opens (e.g.
    # Logistics Hub's route popout) while MainWindow itself happens to be
    # minimized would look to Qt like "the last visible window closed" and
    # quit the whole app out from under the still-open main window.
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

    set_status(splash, "Loading location data...")
    app.processEvents()
    locations = LocationService(api_client)
    locations.ensure_loaded(background_refresh_stale=True)

    window = MainWindow(config)

    def _on_module_loading(name):
        set_status(splash, f"Loading {name.replace('_', ' ').title()}...")

    discover_start = time.monotonic()
    services = Services(api_client, config, locations, PriceCache())
    modules = discover_modules(api_client, config, locations, on_module_loading=_on_module_loading, services=services)
    logger.info("discover_modules() took %.2fs total", time.monotonic() - discover_start)
    if not modules:
        logger.warning("No modules loaded — the overlay will show an empty container.")

    refreshers: list[ModuleRefresher] = []  # keep references alive
    for module in modules:
        set_status(splash, f"Starting {_plain_text(module.display_name)}...")
        card = safe_create_card(module, window.card_container)
        if card is None:
            continue
        # Module just populated card.body; the card computed its size before
        # that (CardContainer has no layout manager, so nothing resizes it
        # automatically). Force the layout to recompute now.
        card.apply_size()
        refresher = ModuleRefresher(module, card, _refresh_interval_seconds(module))
        module.request_refresh = refresher.refresh
        refresher.start()  # initial fetch, then the timer
        refreshers.append(refresher)

    def _on_content_hidden_changed(hidden: bool):
        for refresher in refreshers:
            refresher.set_paused(hidden)
    window.content_hidden_changed.connect(_on_content_hidden_changed)

    modules_shut_down = False

    def _shutdown_modules():
        # Runs from aboutToQuit on a normal exit, or from MainWindow.relaunch()
        # (which exits via os._exit and never reaches aboutToQuit) — only once.
        nonlocal modules_shut_down
        if modules_shut_down:
            return
        modules_shut_down = True
        for refresher in refreshers:
            refresher.stop()
        for module in modules:
            try:
                module.shutdown()
            except Exception:
                logger.exception("Module '%s' shutdown() failed", getattr(module, "module_id", "?"))
        # The event loop is ending, so a debounced save_soon() would never fire.
        config.flush()
    app.aboutToQuit.connect(_shutdown_modules)
    window.add_before_exit(_shutdown_modules)
    window.add_before_exit(lambda: _instance_lock.__exit__(None, None, None))

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
