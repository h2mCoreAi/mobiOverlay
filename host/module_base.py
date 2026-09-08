"""The module contract every modules/<name>/module.py entry point implements.

See docs/ARCHITECTURE.md for the full contract description. host/module_loader.py
validates module_id/display_name/create_card/refresh at load time and rejects
duplicate module_ids — a module that doesn't conform is skipped with a logged
error rather than corrupting shared state or crashing the app.
"""
from host.api_client import UexApiClient
from host.config import Config


class ModuleBase:
    module_id: str = ""
    display_name: str = ""

    def __init__(self, api_client: UexApiClient, config: Config):
        self.api = api_client
        self.config = config
        self.settings = config.module_settings(self.module_id)

    def create_card(self, parent):
        """Return a host.card.Card populated with this module's content."""
        raise NotImplementedError

    def refresh(self):
        """Fetch fresh data and update the card. Called on a timer and on
        manual refresh. Exceptions propagate to the host's error boundary,
        which puts the card into its error state rather than crashing."""
        raise NotImplementedError

    def shutdown(self):
        """Optional: release any process-wide resource a module opened for
        its own lifetime — a global keyboard hook, a background thread/timer
        outside Qt's normal widget-destruction path, an open device handle.
        Default no-op; most modules need nothing here (a card being torn
        down along with the rest of the Qt widget tree is enough on its
        own). The host calls this for every loaded module on app quit —
        including a Relaunch, which self-tests exactly this: relaunch()
        already had to explicitly unhook the host's own Stow/Deploy hotkey
        before spawning the new process (see docs/DECISIONS.md, 2026-09-04)
        because Windows only reclaims a WH_KEYBOARD_LL hook when the owning
        *process* actually dies, not when a Python object is merely
        destroyed — otherwise the old and new instance could briefly hold a
        live hook for the same combo at once. Any module doing the same
        thing (see modules/mobi_throttle) needs the identical cleanup, so
        it's a first-class hook here rather than a one-off fixed to the host
        window alone."""
        pass
