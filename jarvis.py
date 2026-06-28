import os, sys, asyncio, logging
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from dotenv import load_dotenv
from core.brain import Brain
from core.telegram_bot import TelegramBot
from extensions import load_all

load_dotenv()
logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")
log = logging.getLogger("jarvis")

async def main():
    log.info("JARVIS starting up...")
    brain = Brain()
    loaded, failed = load_all(brain)
    log.info(f"Ready. Extensions: {loaded}")
    if failed:
        log.warning(f"Some extensions failed: {failed}")
    bot = TelegramBot(brain)
    await bot.run()

if __name__ == "__main__":
    asyncio.run(main())
