"""Regression suite for the click-through pill's hover-to-unlock: clicks
pass through until the cursor rests on the pill, it relocks on leave, and
the poll only runs while stowed with click-through ON.

Runs offscreen with a fake cursor — no visible window, no input hooks.
Plain asserts, run directly:
    python tests/test_pill_hover_unlock.py
"""
import os
import sys
import tempfile
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from PySide6.QtCore import QPoint, Qt
from PySide6.QtWidgets import QApplication


def run() -> int:
    app = QApplication.instance() or QApplication(sys.argv)
    from host.config import Config
    import host.main_window as mw

    cursor = {"pos": QPoint(-5000, -5000)}
    mw.QCursor = type("FakeCursor", (), {"pos": staticmethod(lambda: cursor["pos"])})

    config = Config(Path(tempfile.mkdtemp()) / "config.json")
    config.data["ui"]["pill_click_through"] = True
    win = mw.MainWindow(config)
    win.show()
    checks = 0

    win.stow_app()
    assert win._pill_hover_timer.isActive(), "poll should run while stowed with click-through ON"
    assert win.testAttribute(Qt.WA_TransparentForMouseEvents)
    checks += 1

    cursor["pos"] = win.frameGeometry().center()
    win._poll_pill_hover()
    assert not win._pill_unlocked, "unlocked on first contact — a quick pass would catch clicks"
    checks += 1

    win._pill_hover_since -= mw.PILL_HOVER_UNLOCK_MS / 1000 + 0.01
    win._poll_pill_hover()
    assert win._pill_unlocked and not win.testAttribute(Qt.WA_TransparentForMouseEvents), "didn't unlock after resting"
    unlocked_img = win.grab().toImage()
    edge = unlocked_img.pixelColor(unlocked_img.width() // 2, 1)
    assert edge.blue() > 150, f"no visible unlocked highlight on the pill edge: {edge.name()}"
    checks += 1

    cursor["pos"] = QPoint(-5000, -5000)
    win._poll_pill_hover()
    assert not win._pill_unlocked and win.testAttribute(Qt.WA_TransparentForMouseEvents), "didn't relock on leave"
    checks += 1

    win.set_pill_click_through(False)
    assert not win._pill_hover_timer.isActive(), "poll should stop when click-through is turned OFF"
    win.set_pill_click_through(True)
    assert win._pill_hover_timer.isActive()
    checks += 1

    win.deploy_app()
    assert not win._pill_hover_timer.isActive() and not win._pill_unlocked
    assert not win.testAttribute(Qt.WA_TransparentForMouseEvents), "deployed window left click-through"
    checks += 1

    win._pill_click_through = False
    win.stow_app()
    assert not win._pill_hover_timer.isActive(), "poll must not run with click-through OFF"
    checks += 1

    win._exiting = True  # don't quit a shared QApplication
    win.close()
    print(f"{checks}/{checks} pill hover-unlock checks passed")
    return checks


if __name__ == "__main__":
    run()
