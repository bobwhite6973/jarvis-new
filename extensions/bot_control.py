"""
Extension: bot_control
Sends control commands to deployed bots via HTTP webhooks.
Configure each bot's control URL in .env as BOT_CTRL_<NAME>=https://...
"""

import os
import re
import httpx
import sqlite3
import logging
from pathlib import Path
from datetime import datetime

log = logging.getLogger("jarvis.ext.bot_control")
DB_PATH = Path("data/memory.db")


def _parse_command(query: str) -> tuple[str, str]:
    """Extract action and bot name from natural language."""
    q = query.lower()
    action = "unknown"
    for word in ["pause", "stop", "start", "resume", "restart"]:
        if word in q:
            action = word
            break
    match = re.search(r"bot\s+(\w[\w\-]*)", q)
    bot_name = match.group(1) if match else "arb"
    return action, bot_name


async def control_bot(query: str) -> str:
    """Route a control command to the right bot endpoint."""
    action, bot_name = _parse_command(query)
    env_key = f"BOT_CTRL_{bot_name.upper()}"
    ctrl_url = os.environ.get(env_key, "")

    result_lines = [f"Bot control: {action} → {bot_name}"]

    if ctrl_url:
        try:
            async with httpx.AsyncClient(timeout=10) as client:
                resp = await client.post(ctrl_url, json={"action": action})
                resp.raise_for_status()
                result_lines.append(f"✅ HTTP {resp.status_code}: {resp.text[:200]}")
        except Exception as e:
            result_lines.append(f"❌ Webhook failed: {e}")
    else:
        result_lines.append(
            f"No control URL set for '{bot_name}'. "
            f"Set {env_key} in .env to wire up live control."
        )
        result_lines.append("Updating local status registry only.")

    # Update local DB regardless
    new_status = "paused" if action in ("pause", "stop") else "running"
    with sqlite3.connect(DB_PATH) as conn:
        conn.execute(
            "INSERT OR REPLACE INTO bot_status(bot_name,status,last_pnl,updated_at) VALUES(?,?,?,?)",
            (bot_name, new_status, None, datetime.utcnow().isoformat())
        )
        conn.commit()
    result_lines.append(f"Local registry updated: {bot_name} → {new_status}")

    return "\n".join(result_lines)


def register(brain):
    brain.register_extension("bot_control", control_bot)
