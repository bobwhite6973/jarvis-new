"""
JARVIS Mark 5 — Bob White Edition
Entry point. Loads extensions, starts brain, starts Telegram bot + web dashboard.
"""
import os
import sys
import logging
import importlib
import asyncio
from pathlib import Path
from dotenv import load_dotenv
load_dotenv()

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s"
)
log = logging.getLogger("JARVIS")


def load_extensions(brain):
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


async def main():
    log.info("JARVIS Mark 5 starting...")

    from core.brain import Brain
    brain = Brain()

    extensions = load_extensions(brain)
    log.info(f"Loaded {len(extensions)} extensions: {extensions}")

    # Wire brain into API
    from core.api import app, set_brain
    set_brain(brain)

    # Start FastAPI
    import uvicorn
    port = int(os.getenv("PORT", 8000))
    config = uvicorn.Config(app, host="0.0.0.0", port=port, log_level="warning")
    server = uvicorn.Server(config)

    # Start Telegram bot
    from core.telegram_bot import start_telegram_bot

    log.info(f"Dashboard running on port {port}")

    await asyncio.gather(
        server.serve(),
        start_telegram_bot(brain),
    )


if __name__ == "__main__":
    asyncio.run(main())
