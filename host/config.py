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
        "hotkey_combo": "",
        "hotkey_display": "",
    },
    "api": {"uex_token": "", "uex_base_url": "https://api.uexcorp.uk/2.0/"},
    "cards": {},
    "modules": {},
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

    # -- card layout --
    def card_state(self, card_id: str) -> dict:
        return self.data["cards"].setdefault(
            card_id, {"x": 0, "y": 0, "collapsed": False, "visible": True}
        )

    def set_card_state(self, card_id: str, **kwargs) -> None:
        state = self.card_state(card_id)
        state.update(kwargs)
        self.save()
