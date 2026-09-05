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
import time

from host.api_client import UexApiClient
from host.config import Config
from host.module_base import ModuleBase
from host.paths import app_root

logger = logging.getLogger("mobioverlay.module_loader")

MODULES_ROOT = app_root() / "modules"


def discover_modules(api_client: UexApiClient, config: Config, on_module_loading=None) -> list[ModuleBase]:
    """`on_module_loading`, if given, is called with each folder name right
    before that module's file is imported/executed — lets a caller (main.py's
    splash screen) show which module is loading, since a slow one (e.g.
    Logistics Hub's `import easyocr`) can otherwise look like a frozen app."""
    loaded: list[ModuleBase] = []
    seen_module_ids: dict[str, str] = {}  # module_id -> folder name that claimed it
    if not MODULES_ROOT.exists():
        return loaded

    for finder, name, is_pkg in pkgutil.iter_modules([str(MODULES_ROOT)]):
        if not is_pkg:
            continue
        entry_point = MODULES_ROOT / name / "module.py"
        if not entry_point.exists():
            continue
        if on_module_loading is not None:
            on_module_loading(name)
        try:
            # Temporary diagnostic timing (see the startup-delay investigation
            # in DECISIONS.md) — a module's own top-level imports (e.g.
            # Logistics Hub's `import easyocr`, which pulls in PyTorch) run
            # here, during exec_module, entirely separate from any API call
            # and before main.py's create_card()/refresh() watchdog exists.
            load_start = time.monotonic()
            module_class = _load_module_class(name, entry_point)
            load_elapsed = time.monotonic() - load_start
            logger.info("modules/%s: import + exec took %.2fs", name, load_elapsed)
            if module_class is None:
                logger.error("modules/%s/module.py has no MODULE_CLASS", name)
                continue
            instance = module_class(api_client, config)
            _validate_module_contract(name, instance)

            module_id = instance.module_id
            if module_id in seen_module_ids:
                logger.error(
                    "modules/%s declares module_id '%s', already claimed by "
                    "modules/%s — skipping (module_id must be unique)",
                    name, module_id, seen_module_ids[module_id],
                )
                continue
            seen_module_ids[module_id] = name

            loaded.append(instance)
        except Exception:
            logger.exception("Failed to load module '%s' — skipping", name)
    return loaded


def _validate_module_contract(name: str, instance: ModuleBase):
    """Fail loudly and early at load time rather than letting a malformed
    module surface a confusing error deep inside main.py/card_container.py
    later. Raises ValueError; the caller's broad except turns that into a
    logged skip, same as any other load failure."""
    if not isinstance(instance, ModuleBase):
        raise ValueError(f"modules/{name}'s MODULE_CLASS does not subclass ModuleBase")
    if not instance.module_id or not isinstance(instance.module_id, str):
        raise ValueError(f"modules/{name} has no non-empty string module_id")
    if not instance.display_name or not isinstance(instance.display_name, str):
        raise ValueError(f"modules/{name} has no non-empty string display_name")
    for method_name in ("create_card", "refresh"):
        if not callable(getattr(instance, method_name, None)):
            raise ValueError(f"modules/{name} does not implement {method_name}()")


def _load_module_class(name: str, entry_point):
    module_name = f"mobioverlay_module_{name}"
    spec = importlib.util.spec_from_file_location(module_name, entry_point)
    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module
    spec.loader.exec_module(module)
    return getattr(module, "MODULE_CLASS", None)
