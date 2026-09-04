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
