"""
JARVIS Mark 5 — Bob White Edition
Entry point. Loads extensions, starts brain, starts Telegram bot.
"""

import os
import sys
import logging
import importlib
from pathlib import Path
from dotenv import load_dotenv

load_dotenv()

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s"
)
log = logging.getLogger("JARVIS")


def load_extensions(brain):
    """Auto-load every .py file in /extensions that has a register(brain) function."""
    ext_dir = Path(__file__).parent / "extensions"
    loaded = []
    for f in sorted(ext_dir.glob("*.py")):
        if f.name.startswith("_"):
            continue
        mod_name = f"extensions.{f.stem}"
        try:
            mod = importlib.import_module(mod_name)
            if hasattr(mod, "register"):
                mod.register(brain)
                loaded.append(f.stem)
                log.info(f"Extension loaded: {f.stem}")
        except Exception as e:
            log.warning(f"Extension {f.stem} failed to load: {e}")
    return loaded


def main():
    log.info("JARVIS Mark 5 starting...")

    from core.brain import Brain
    brain = Brain()

    extensions = load_extensions(brain)
    log.info(f"Loaded {len(extensions)} extensions: {extensions}")

    from core.telegram_bot import start_telegram_bot
    start_telegram_bot(brain)


if __name__ == "__main__":
    main()
