"""Discovers and loads modules from modules/<name>/module.py.

Convention: each module.py defines MODULE_CLASS = <ModuleBase subclass>.
A module that fails to import or instantiate is skipped with a logged
error — it never takes the whole host down.

Modules are loaded by file path (importlib.util.spec_from_file_location),
not as a dotted "modules.<name>.module" package import. That matters once
this is packaged: modules/ is meant to stay an external, editable folder
next to the exe (see docs/ARCHITECTURE.md, "Packaging") rather than being
frozen inside it, so it won't be an importable package on sys.path the way
it is when running from source. File-path loading works identically either
way.
"""
import importlib.util
import logging
import pkgutil
import sys

from host.api_client import UexApiClient
from host.config import Config
from host.module_base import ModuleBase
from host.paths import app_root

logger = logging.getLogger("mobioverlay.module_loader")

MODULES_ROOT = app_root() / "modules"


def discover_modules(api_client: UexApiClient, config: Config) -> list[ModuleBase]:
    loaded: list[ModuleBase] = []
    if not MODULES_ROOT.exists():
        return loaded

    for finder, name, is_pkg in pkgutil.iter_modules([str(MODULES_ROOT)]):
        if not is_pkg:
            continue
        entry_point = MODULES_ROOT / name / "module.py"
        if not entry_point.exists():
            continue
        try:
            module_class = _load_module_class(name, entry_point)
            if module_class is None:
                logger.error("modules/%s/module.py has no MODULE_CLASS", name)
                continue
            instance = module_class(api_client, config)
            loaded.append(instance)
        except Exception:
            logger.exception("Failed to load module '%s' — skipping", name)
    return loaded


def _load_module_class(name: str, entry_point):
    module_name = f"mobioverlay_module_{name}"
    spec = importlib.util.spec_from_file_location(module_name, entry_point)
    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module
    spec.loader.exec_module(module)
    return getattr(module, "MODULE_CLASS", None)
