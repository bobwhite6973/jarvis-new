"""
Extension: pnl_report
Reads bot_status from SQLite and formats a daily P&L summary.
In production, hook this to your Render bot's /status endpoint.
"""

import os
import httpx
import sqlite3
import logging
from pathlib import Path
from datetime import datetime

log = logging.getLogger("jarvis.ext.pnl_report")
DB_PATH = Path("data/memory.db")

# Optional: your deployed Render arb bot status URL
ARB_BOT_URL = os.environ.get("ARB_BOT_STATUS_URL", "")


async def fetch_render_bot_status() -> dict | None:
    """Try to pull live status from your deployed Render arb bot."""
    if not ARB_BOT_URL:
        return None
    try:
        async with httpx.AsyncClient(timeout=8) as client:
            resp = await client.get(ARB_BOT_URL)
            resp.raise_for_status()
            return resp.json()
    except Exception as e:
        log.warning(f"Render bot status fetch failed: {e}")
        return None


async def get_pnl_report(_query: str = "") -> str:
    """
    Returns a formatted P&L summary for LLM consumption.
    Combines SQLite local data + live Render endpoint if available.
    """
    lines = [f"P&L Report — {datetime.utcnow().strftime('%Y-%m-%d %H:%M UTC')}\n"]

    # Pull from local DB
    with sqlite3.connect(DB_PATH) as conn:
        rows = conn.execute(
            "SELECT bot_name, status, last_pnl, updated_at FROM bot_status"
        ).fetchall()

    if rows:
        lines.append("Local bot registry:")
        total_pnl = 0.0
        for name, status, pnl, updated in rows:
            icon = "🟢" if status == "running" else "🔴"
            pnl_str = f"{pnl:+.6f} SOL" if pnl is not None else "N/A"
            if pnl:
                total_pnl += pnl
            lines.append(f"  {icon} {name}: {status} | PnL={pnl_str} | updated={updated}")
        lines.append(f"  Total tracked PnL: {total_pnl:+.6f} SOL")
    else:
        lines.append("No bots registered in local DB yet.")

    # Try live Render status
    live = await fetch_render_bot_status()
    if live:
        lines.append("\nLive Render bot status:")
        for k, v in live.items():
            lines.append(f"  {k}: {v}")
    else:
        lines.append("\nLive Render status: not configured or unreachable.")
        lines.append("Set ARB_BOT_STATUS_URL in .env to connect your Render bot.")

    return "\n".join(lines)


def register(brain):
    brain.register_extension("pnl_report", get_pnl_report)
