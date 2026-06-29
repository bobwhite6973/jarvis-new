"""
Extension: memory
Persistent memory for JARVIS using SQLite.
Stores facts, preferences, and notes across restarts.
"""
import sqlite3
import logging
from pathlib import Path
from datetime import datetime

log = logging.getLogger("jarvis.memory")

DB_PATH = Path("data/memory.db")


def _init_db():
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(DB_PATH) as conn:
        conn.executescript("""
            CREATE TABLE IF NOT EXISTS bot_status (
                bot_name  TEXT PRIMARY KEY,
                status    TEXT,
                last_pnl  TEXT,
                updated_at TEXT
            );
            CREATE TABLE IF NOT EXISTS memories (
                id         INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id    INTEGER,
                category   TEXT DEFAULT 'general',
                key        TEXT,
                value      TEXT,
                created_at TEXT
            );
            CREATE TABLE IF NOT EXISTS notes (
                id         INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id    INTEGER,
                note       TEXT,
                created_at TEXT
            );
        """)
        conn.commit()
    log.info("Memory DB initialized")


def remember(user_id: int, key: str, value: str, category: str = "general") -> dict:
    try:
        with sqlite3.connect(DB_PATH) as conn:
            conn.execute(
                "INSERT INTO memories(user_id, category, key, value, created_at) VALUES(?,?,?,?,?)",
                (user_id, category, key, value, datetime.utcnow().isoformat())
            )
            conn.commit()
        return {"status": "ok", "message": f"Remembered: {key} = {value}"}
    except Exception as e:
        return {"error": str(e)}


def recall(user_id: int, query: str = "") -> dict:
    try:
        with sqlite3.connect(DB_PATH) as conn:
            if query:
                rows = conn.execute(
                    "SELECT key, value, category, created_at FROM memories "
                    "WHERE user_id=? AND (key LIKE ? OR value LIKE ?) "
                    "ORDER BY created_at DESC LIMIT 20",
                    (user_id, f"%{query}%", f"%{query}%")
                ).fetchall()
            else:
                rows = conn.execute(
                    "SELECT key, value, category, created_at FROM memories "
                    "WHERE user_id=? ORDER BY created_at DESC LIMIT 20",
                    (user_id,)
                ).fetchall()
        return {"memories": [{"key": r[0], "value": r[1], "category": r[2], "when": r[3]} for r in rows]}
    except Exception as e:
        return {"error": str(e)}


def forget(user_id: int, key: str) -> dict:
    try:
        with sqlite3.connect(DB_PATH) as conn:
            conn.execute(
                "DELETE FROM memories WHERE user_id=? AND key LIKE ?",
                (user_id, f"%{key}%")
            )
            conn.commit()
        return {"status": "ok", "message": f"Forgot: {key}"}
    except Exception as e:
        return {"error": str(e)}


def get_context(user_id: int) -> str:
    """Return recent memories as a string to inject into system prompt."""
    result = recall(user_id)
    memories = result.get("memories", [])
    if not memories:
        return ""
    lines = ["User memory context:"]
    for m in memories[:10]:
        lines.append(f"- {m['key']}: {m['value']}")
    return "\n".join(lines)


def register(brain):
    _init_db()
    brain.register_tool("remember", remember)
    brain.register_tool("recall", recall)
    brain.register_tool("forget", forget)
    brain.register_tool("get_memory_context", get_context)
    log.info("memory extension registered")
