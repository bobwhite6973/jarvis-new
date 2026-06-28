"""
Extension loader — imports and registers all extensions with Brain at startup.
To add a new extension: drop a .py file in /extensions/ with a register(brain) function.
"""

import importlib
import logging
from pathlib import Path

log = logging.getLogger("jarvis.extensions")


def load_all(brain):
    """Auto-discover and register all extensions in the extensions/ directory."""
    ext_dir = Path(__file__).parent
    loaded = []
    failed = []

    for path in sorted(ext_dir.glob("*.py")):
        if path.name.startswith("_"):
            continue
        module_name = f"extensions.{path.stem}"
        try:
            mod = importlib.import_module(module_name)
            if hasattr(mod, "register"):
                mod.register(brain)
                loaded.append(path.stem)
            else:
                log.warning(f"Extension {path.stem} has no register() function — skipped")
        except Exception as e:
            log.error(f"Failed to load extension {path.stem}: {e}")
            failed.append(path.stem)

    log.info(f"Extensions loaded: {loaded}")
    if failed:
        log.warning(f"Extensions failed: {failed}")
    return loaded, failed
