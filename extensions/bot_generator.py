"""
Extension: bot_generator
Uses Claude to scaffold complete, deployable trading bot code.
Always routes to Claude regardless of user's active provider setting.
"""

import os
import httpx
import logging

log = logging.getLogger("jarvis.ext.bot_generator")

CLAUDE_API_URL = "https://api.anthropic.com/v1/messages"
CLAUDE_MODEL = "claude-sonnet-4-6"

BOT_SCAFFOLD_PROMPT = """You are a senior crypto trading bot engineer.
Generate complete, production-ready Python bot code based on the description.
Always include:
1. Full working code in a single file (or clearly labeled multiple files)
2. requirements.txt entries needed
3. .env variables required (listed as comments, no real values)
4. Render/Railway deployment notes as comments at the top
5. Error handling, logging, and a clean main() async entry point

Stack preferences: Python, httpx or aiohttp for async HTTP, python-dotenv for config.
For Solana: use Jupiter API v6 for swaps, solders or solana-py for signing.
For Telegram control: python-telegram-bot v20+.
Keep code clean, commented, and immediately deployable."""


async def generate_bot(query: str) -> str:
    """
    Generates bot scaffold. Always uses Claude for code quality.
    Returns the raw code/description — Brain will forward to user as-is.
    """
    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        return "ERROR: ANTHROPIC_API_KEY not set — bot generator requires Claude."

    description = query.replace("generate bot:", "").replace("create bot:", "").strip()
    prompt = f"Generate a complete trading bot based on this description:\n\n{description}"

    try:
        async with httpx.AsyncClient(timeout=60) as client:
            resp = await client.post(
                CLAUDE_API_URL,
                headers={
                    "x-api-key": api_key,
                    "anthropic-version": "2023-06-01",
                    "content-type": "application/json",
                },
                json={
                    "model": CLAUDE_MODEL,
                    "max_tokens": 4096,
                    "system": BOT_SCAFFOLD_PROMPT,
                    "messages": [{"role": "user", "content": prompt}],
                }
            )
            resp.raise_for_status()
            code = resp.json()["content"][0]["text"]
            return f"[bot_generator output — {len(code)} chars]\n\n{code}"
    except Exception as e:
        log.error(f"Bot generation failed: {e}")
        return f"ERROR: Bot generation failed — {e}"


def register(brain):
    brain.register_extension("bot_generator", generate_bot)
