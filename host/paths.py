"""Resolves the app's root directory — the exe's own folder when packaged
(PyInstaller frozen build), or the project root when running from source.

Use this for anything that must live next to the app on disk rather than
bundled inside it: config.json (must persist across launches — a frozen
onefile build's temp extraction directory is wiped and recreated every
launch, so anything __file__-relative inside it never actually persists)
and modules/ (must stay externally editable/pluggable without a rebuild —
see docs/ARCHITECTURE.md, "Packaging" section, for why).

Bundled, non-pluggable assets (fonts) should keep using __file__-relative
paths as before — those are meant to travel inside the frozen build.
"""
import sys
from pathlib import Path


def app_root() -> Path:
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parent.parent
