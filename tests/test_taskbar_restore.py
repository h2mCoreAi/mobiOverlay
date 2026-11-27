"""Regression suite for minimize-to-taskbar recovery: the tray's Show, the
Stow/Deploy hotkey and tray Stow must all act on a minimized window instead
of changing a window the user can't see, and the content-hidden signal
(which pauses card refresh timers) must follow stow/minimize/restore.

Runs offscreen — no visible window, no input hooks.
Plain asserts, run directly:
    python tests/test_taskbar_restore.py
"""
import os
import sys
import tempfile
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from PySide6.QtWidgets import QApplication


def run() -> int:
    app = QApplication.instance() or QApplication(sys.argv)
    from host.config import Config
    import host.main_window as mw

    config = Config(Path(tempfile.mkdtemp()) / "config.json")
    win = mw.MainWindow(config)
    win._take_foreground_focus = lambda: None  # no real foreground juggling offscreen
    hidden_events = []
    win.content_hidden_changed.connect(hidden_events.append)
    win.show()
    app.processEvents()
    checks = 0

    win.showMinimized()
    app.processEvents()
    assert win.isMinimized(), "offscreen platform didn't minimize"
    assert hidden_events[-1] is True, "minimizing should report content hidden"
    checks += 1

    win._tray._on_show()
    app.processEvents()
    assert not win.isMinimized(), "tray Show left a minimized window minimized"
    assert hidden_events[-1] is False
    checks += 1

    win.showMinimized()
    app.processEvents()
    win.toggle_app_stow()
    app.processEvents()
    assert not win.isMinimized() and not win.is_app_stowed(), \
        "hotkey on a minimized window should show it, not stow it out of sight"
    checks += 1

    win.showMinimized()
    app.processEvents()
    win.stow_app()
    app.processEvents()
    assert win.is_app_stowed() and not win.isMinimized(), "tray Stow should show the pill, not a minimized one"
    assert hidden_events[-1] is True, "stowed should report content hidden"
    checks += 1

    win.showMinimized()
    app.processEvents()
    win.toggle_app_stow()
    app.processEvents()
    assert not win.is_app_stowed() and not win.isMinimized(), "hotkey on a minimized pill should deploy"
    assert hidden_events[-1] is False
    checks += 1

    # No duplicate signals for a state that didn't change.
    count = len(hidden_events)
    win._sync_content_hidden()
    assert len(hidden_events) == count
    checks += 1

    win._exiting = True
    win.close()
    print(f"{checks}/{checks} taskbar restore checks passed")
    return 0


if __name__ == "__main__":
    sys.exit(run())
