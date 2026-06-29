import os, sys, asyncio, logging, importlib
from pathlib import Path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from dotenv import load_dotenv
from core.brain import Brain
from core.telegram_bot import TelegramBot

load_dotenv()
logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")
log = logging.getLogger("jarvis")

def load_extensions(brain):
    ext_dir = Path(__file__).parent / "extensions"
    loaded, failed = [], []
    for path in sorted(ext_dir.glob("*.py")):
        if path.name.startswith("_"):
            continue
        try:
            mod = importlib.import_module(f"extensions.{path.stem}")
            if hasattr(mod, "register"):
                mod.register(brain)
            loaded.append(path.stem)
        except Exception as e:
            log.error(f"Extension {path.stem} failed: {e}")
            failed.append(path.stem)
    return loaded, failed

async def main():
    log.info("JARVIS starting up...")
    brain = Brain()
    loaded, failed = load_extensions(brain)
    log.info(f"Ready. Extensions: {loaded}")
    if failed:
        log.warning(f"Failed: {failed}")
    bot = TelegramBot(brain)
    await bot.run()

if __name__ == "__main__":
    asyncio.run(main())
