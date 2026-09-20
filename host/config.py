"""Local JSON config: persists UI state, API settings, and per-module settings.

Schema documented in docs/ARCHITECTURE.md.
"""
import json
from pathlib import Path

from host.paths import app_root

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
        elif isinstance(value, dict) and isinstance(data[key], dict):
            _deep_merge_defaults(data[key], value)
    return data


class Config:
    def __init__(self, path: Path = CONFIG_PATH):
        self.path = path
        self.data = self._load()

    def _load(self) -> dict:
        if self.path.exists():
            try:
                with open(self.path, "r", encoding="utf-8") as f:
                    data = json.load(f)
            except (json.JSONDecodeError, OSError):
                data = {}
        else:
            data = {}
        return _deep_merge_defaults(data, json.loads(json.dumps(DEFAULT_CONFIG)))

    def save(self) -> None:
        with open(self.path, "w", encoding="utf-8") as f:
            json.dump(self.data, f, indent=2)

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
