"""The shared services Core hands to every module, in one object.

Adding a new shared service means adding a field here and building it in
host/main.py — no module's `__init__` changes. Modules reach it as
`self.services` (see host/module_base.py); `self.api`, `self.config` and
`self.locations` remain as shortcuts to the first three.
"""
from dataclasses import dataclass

from host.api_client import UexApiClient
from host.config import Config
from host.locations import LocationService
from host.price_cache import PriceCache


@dataclass
class Services:
    api: UexApiClient
    config: Config
    locations: LocationService
    price_cache: PriceCache
