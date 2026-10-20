"""Core hands every module one shared Services object (L2).

No Qt window, no network:
    python tests/test_services.py
"""
import sys
import tempfile
from pathlib import Path
from unittest.mock import MagicMock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from host.config import Config
from host.module_base import ModuleBase
from host.price_cache import PriceCache
from host.services import Services


class _M(ModuleBase):
    module_id = "services_probe"


def _args():
    d = Path(tempfile.mkdtemp())
    return MagicMock(), Config(path=d / "config.json"), MagicMock(), d


def test_default_services_built_outside_the_loader() -> int:
    ModuleBase.install_services(None)
    api, config, locations, _ = _args()
    m = _M(api, config, locations)
    assert m.services.api is api and m.services.config is config and m.services.locations is locations
    assert isinstance(m.services.price_cache, PriceCache)
    return 2


def test_installed_services_shared_by_every_module() -> int:
    api, config, locations, d = _args()
    shared = Services(api, config, locations, PriceCache(d / "p.sqlite3"))
    ModuleBase.install_services(shared)
    try:
        a, b = _M(api, config, locations), _M(api, config, locations)
        assert a.services is shared and b.services is shared
        assert a.api is api, "the self.api shortcut must still work"
    finally:
        ModuleBase.install_services(None)
    return 3


def run() -> int:
    checks = 0
    for t in (test_default_services_built_outside_the_loader, test_installed_services_shared_by_every_module):
        checks += t()
        print(f"[PASS] {t.__name__}")
    print(f"\n{checks}/{checks} services checks passed")
    return checks


if __name__ == "__main__":
    run()
