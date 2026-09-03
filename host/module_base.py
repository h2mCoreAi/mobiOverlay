"""The module contract every modules/<name>/module.py entry point implements.

See docs/ARCHITECTURE.md for the full contract description.
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
