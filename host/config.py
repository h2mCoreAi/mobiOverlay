"""Local JSON config: persists UI state, API settings, and per-module settings.

Schema documented in docs/ARCHITECTURE.md.
"""
import json
import logging
from pathlib import Path

from host.fileio import atomic_write_text, quarantine_corrupt
from host.paths import app_root

logger = logging.getLogger("mobioverlay.config")

CONFIG_PATH = app_root() / "config.json"

DEFAULT_CONFIG = {
    "ui": {
        "window_opacity": 0.92,
        "card_opacity": 0.94,
        "font_scale": 1.15,  # matches the new "Normal" tier — see theme.py
        "always_on_top": True,
        "window_geometry": {},
        "pre_stow_geometry": {},
        "pill_geometry": {},
        # When True, the minimized pill is click-through (WS_EX_TRANSPARENT)
        # — can't be dragged or clicked at all; redeploy via the Stow/Deploy
        # hotkey. Never applied while deployed, regardless of this value.
        "pill_click_through": False,
        "hotkey_combo": "",
        "hotkey_display": "",
        # Debug feature: shows a console window with log output. Only
        # actually changes anything for the packaged exe (mobioverlay.spec
        # builds console=False) or a source run with no console already
        # attached — see host/main.py's _maybe_allocate_console(). Applies
        # on next launch, same as font_scale.
        "show_console": False,
    },
    "api": {"uex_token": "", "uex_base_url": "https://api.uexcorp.uk/2.0/"},
    "cards": {},
    "modules": {},
    # Cross-module state, not namespaced to any one module — Phase 5 of the
    # location-service plan (docs/DECISIONS.md, 2026-09-04). Logistics Hub's
    # CURRENT LOCATION picker writes here; other modules read it only as an
    # initial default for their own system/terminal filters, never as a
    # forced override of a filter the user already set explicitly.
    "shared": {"current_location_name": "", "current_location": None},
}


def _deep_merge_defaults(data: dict, defaults: dict) -> dict:
    for key, value in defaults.items():
        if key not in data:
            data[key] = value
        elif isinstance(value, dict) and not isinstance(data[key], dict):
            # A hand-edited or damaged section (e.g. "ui": null) would
            # otherwise crash every data["ui"][...] lookup at startup.
            data[key] = value
        elif isinstance(value, dict):
            _deep_merge_defaults(data[key], value)
    return data


class Config:
    def __init__(self, path: Path = CONFIG_PATH):
        self.path = path
        self.data = self._load()

    def _load(self) -> dict:
        data = {}
        if self.path.exists():
            try:
                with open(self.path, "r", encoding="utf-8") as f:
                    data = json.load(f)
            except json.JSONDecodeError:
                quarantine_corrupt(self.path)
            except OSError:
                logger.warning("Could not read %s — using defaults", self.path, exc_info=True)
            if not isinstance(data, dict):
                quarantine_corrupt(self.path)
                data = {}
        return _deep_merge_defaults(data, json.loads(json.dumps(DEFAULT_CONFIG)))

    def save(self) -> None:
        # Never raises: save() is called from dozens of UI slots, and a
        # transient write failure (file locked by a sync client, disk full)
        # shouldn't break whatever the user just clicked.
        try:
            atomic_write_text(self.path, json.dumps(self.data, indent=2))
        except (OSError, TypeError, ValueError):
            logger.warning("Failed to save %s", self.path, exc_info=True)

    # -- module-namespaced settings --
    def module_settings(self, module_id: str) -> dict:
        return self.data["modules"].setdefault(module_id, {})

    def set_module_settings(self, module_id: str, settings: dict) -> None:
        self.data["modules"][module_id] = settings
        self.save()

    # -- shared cross-module current location (Phase 5) --
    def shared_location(self) -> dict | None:
        """The terminal dict last picked as CURRENT LOCATION by whichever
        module set it (today: Logistics Hub only), or None if nothing has
        been picked yet this install."""
        return self.data["shared"].get("current_location")

    def set_shared_location(self, terminal: dict | None, name: str) -> None:
        self.data["shared"]["current_location"] = terminal
        self.data["shared"]["current_location_name"] = name
        self.save()

    # -- card layout --
    def card_state(self, card_id: str) -> dict:
        return self.data["cards"].setdefault(
            card_id, {"x": 0, "y": 0, "collapsed": False, "visible": True}
        )

    def set_card_state(self, card_id: str, **kwargs) -> None:
        state = self.card_state(card_id)
        state.update(kwargs)
        self.save()
