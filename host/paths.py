"""Resolves the app's root directory and modules path.

- `app_root()` — the exe's own folder when packaged (PyInstaller frozen
  build), or the project root when running from source. Use this for
  anything that must **persist** next to the app on disk: config.json,
  notes data, cache files, etc. A frozen onefile build's temp extraction
  directory (`sys._MEIPASS`) is wiped and recreated every launch, so
  anything written there never actually persists.

- `modules_root()` — where to discover module folders at runtime. When
  frozen, modules are bundled *inside* the exe and extracted to
  `sys._MEIPASS/modules`. When running from source, it's just the
  `modules/` folder next to the project root.

Bundled, non-pluggable assets (fonts) should keep using __file__-relative
paths as before — those are meant to travel inside the frozen build.
"""
import os
import sys
from pathlib import Path


def app_root() -> Path:
    """Persistent storage root: exe folder when frozen, project root from source."""
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parent.parent


def modules_root() -> Path:
    """Where module folders live at runtime. Bundled inside exe when frozen,
    external `modules/` folder when running from source."""
    if getattr(sys, "frozen", False):
        return Path(sys._MEIPASS) / "modules"
    return Path(__file__).resolve().parent.parent / "modules"


def relaunch_command() -> list[str]:
    """Command to start a fresh instance of this app — the same exe when
    packaged, or the same interpreter + entry script when running from
    source. Used by Settings > Relaunch."""
    if getattr(sys, "frozen", False):
        return [sys.executable]
    return [sys.executable, str(Path(__file__).resolve().parent / "main.py")]


def relaunch_env() -> dict[str, str]:
    """Environment for the relaunched process. A onefile build that spawns
    itself passes on PyInstaller's bootloader variables, so the new process
    reuses this instance's sys._MEIPASS extraction folder — which this
    instance's bootloader deletes as it exits. The new copy then finds no
    modules (they live under _MEIPASS) and the cleanup fails with "Failed to
    remove temporary directory". PYINSTALLER_RESET_ENVIRONMENT (PyInstaller
    6.9+) makes the bootloader start fresh with its own extraction folder."""
    env = os.environ.copy()
    if getattr(sys, "frozen", False):
        env["PYINSTALLER_RESET_ENVIRONMENT"] = "1"
    return env
