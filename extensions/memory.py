"""
Extension: memory
Unified persistent memory for JARVIS using SQLite.
Single source of truth — replaces memory_store.py conflict.
Stores facts, preferences, notes, and important content across restarts.
Always confirms saves out loud.
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
                bot_name   TEXT PRIMARY KEY,
                status     TEXT,
                last_pnl   TEXT,
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
    log.info("Memory DB initialized at %s", DB_PATH.resolve())


def remember(user_id: int, key: str, value: str, category: str = "general") -> dict:
    """Save a key/value to persistent memory. Always confirms."""
    try:
        _init_db()
        with sqlite3.connect(DB_PATH) as conn:
            # Use INSERT OR REPLACE so duplicate keys update instead of stacking
            conn.execute(
                """INSERT INTO memories(user_id, category, key, value, created_at)
                   VALUES(?,?,?,?,?)
                   ON CONFLICT DO NOTHING""",
                (user_id, category, key, value, datetime.utcnow().isoformat())
            )
            # Also do an update in case it already existed
            conn.execute(
                """UPDATE memories SET value=?, category=?, created_at=?
                   WHERE user_id=? AND key=?""",
                (value, category, datetime.utcnow().isoformat(), user_id, key)
            )
            conn.commit()
        confirmation = f"✅ Saved to memory: [{category}] {key} = {value}"
        log.info(confirmation)
        return {"status": "ok", "message": confirmation}
    except Exception as e:
        log.error("remember() failed: %s", e)
        return {"error": str(e)}


def recall(user_id: int, query: str = "") -> dict:
    """Retrieve memories. Returns everything or filters by query."""
    try:
        _init_db()
        with sqlite3.connect(DB_PATH) as conn:
            if query:
                rows = conn.execute(
                    "SELECT key, value, category, created_at FROM memories "
                    "WHERE user_id=? AND (key LIKE ? OR value LIKE ? OR category LIKE ?) "
                    "ORDER BY created_at DESC LIMIT 50",
                    (user_id, f"%{query}%", f"%{query}%", f"%{query}%")
                ).fetchall()
            else:
                rows = conn.execute(
                    "SELECT key, value, category, created_at FROM memories "
                    "WHERE user_id=? ORDER BY created_at DESC LIMIT 50",
                    (user_id,)
                ).fetchall()
        memories = [{"key": r[0], "value": r[1], "category": r[2], "when": r[3]} for r in rows]
        if not memories:
            return {"memories": [], "message": "No memories found."}
        return {"memories": memories, "count": len(memories)}
    except Exception as e:
        log.error("recall() failed: %s", e)
        return {"error": str(e)}


def forget(user_id: int, key: str) -> dict:
    """Delete a memory by key."""
    try:
        _init_db()
        with sqlite3.connect(DB_PATH) as conn:
            conn.execute(
                "DELETE FROM memories WHERE user_id=? AND key LIKE ?",
                (user_id, f"%{key}%")
            )
            conn.commit()
        return {"status": "ok", "message": f"🗑️ Forgot: {key}"}
    except Exception as e:
        log.error("forget() failed: %s", e)
        return {"error": str(e)}


def get_context(user_id: int) -> str:
    """Returns a formatted memory context string for injection into prompts."""
    result = recall(user_id)
    memories = result.get("memories", [])
    if not memories:
        return ""
    lines = ["Bob's memory context:"]
    for m in memories[:20]:
        lines.append(f"  [{m['category']}] {m['key']}: {m['value']}")
    return "\n".join(lines)


def register(brain):
    _init_db()
    brain.register_tool("remember", remember)
    brain.register_tool("recall", recall)
    brain.register_tool("forget", forget)
    brain.register_tool("get_memory_context", get_context)
    log.info("✅ Unified memory extension registered — DB: %s", DB_PATH.resolve())
