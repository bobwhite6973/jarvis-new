"""
Extension: memory
Unified persistent memory for JARVIS.
Uses Supabase (Postgres) if DATABASE_URL is set, falls back to SQLite.
Single source of truth — stores facts, preferences, notes across restarts.
Always confirms saves out loud.
"""
import logging
from datetime import datetime

from extensions.db import get_conn, is_postgres, fetchall, fetchone

log = logging.getLogger("jarvis.memory")


def _init_db():
    conn = get_conn()
    try:
        cur = conn.cursor()

        if is_postgres():
            cur.execute("""
                CREATE TABLE IF NOT EXISTS bot_status (
                    bot_name   TEXT PRIMARY KEY,
                    status     TEXT,
                    last_pnl   TEXT,
                    updated_at TEXT
                )
            """)
            cur.execute("""
                CREATE TABLE IF NOT EXISTS memories (
                    id         SERIAL PRIMARY KEY,
                    user_id    INTEGER,
                    category   TEXT DEFAULT 'general',
                    key        TEXT,
                    value      TEXT,
                    created_at TEXT,
                    UNIQUE(user_id, key)
                )
            """)
            cur.execute("""
                CREATE TABLE IF NOT EXISTS notes (
                    id         SERIAL PRIMARY KEY,
                    user_id    INTEGER,
                    note       TEXT,
                    created_at TEXT
                )
            """)
        else:
            cur.executescript("""
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
        log.info("Memory DB initialized — backend: %s", "postgres" if is_postgres() else "sqlite")
    finally:
        conn.close()


def remember(user_id: int, key: str, value: str, category: str = "general") -> dict:
    """Save a key/value to persistent memory. Always confirms."""
    try:
        conn = get_conn()
        try:
            cur = conn.cursor()
            now = datetime.utcnow().isoformat()

            if is_postgres():
                cur.execute("""
                    INSERT INTO memories (user_id, category, key, value, created_at)
                    VALUES (%s, %s, %s, %s, %s)
                    ON CONFLICT (user_id, key) DO UPDATE
                    SET value = EXCLUDED.value,
                        category = EXCLUDED.category,
                        created_at = EXCLUDED.created_at
                """, (user_id, category, key, value, now))
            else:
                cur.execute(
                    "INSERT INTO memories(user_id, category, key, value, created_at) VALUES(?,?,?,?,?) "
                    "ON CONFLICT DO NOTHING",
                    (user_id, category, key, value, now)
                )
                cur.execute(
                    "UPDATE memories SET value=?, category=?, created_at=? WHERE user_id=? AND key=?",
                    (value, category, now, user_id, key)
                )

            conn.commit()
        finally:
            conn.close()

        msg = f"✅ Saved to memory: [{category}] {key} = {value}"
        log.info(msg)
        return {"status": "ok", "message": msg}
    except Exception as e:
        log.error("remember() failed: %s", e)
        return {"status": "error", "message": str(e)}


def recall(user_id: int, query: str = None) -> dict:
    """Retrieve memories. Returns everything or filters by query."""
    try:
        conn = get_conn()
        try:
            if query:
                q = f"%{query}%"
                if is_postgres():
                    rows = fetchall(conn,
                        "SELECT key, value, category, created_at FROM memories "
                        "WHERE user_id=%s AND (key ILIKE %s OR value ILIKE %s OR category ILIKE %s) "
                        "ORDER BY created_at DESC LIMIT 50",
                        (user_id, q, q, q)
                    )
                else:
                    rows = fetchall(conn,
                        "SELECT key, value, category, created_at FROM memories "
                        "WHERE user_id=? AND (key LIKE ? OR value LIKE ? OR category LIKE ?) "
                        "ORDER BY created_at DESC LIMIT 50",
                        (user_id, q, q, q)
                    )
            else:
                rows = fetchall(conn,
                    "SELECT key, value, category, created_at FROM memories "
                    "WHERE user_id=? ORDER BY created_at DESC LIMIT 50",
                    (user_id,)
                )
        finally:
            conn.close()

        memories = [{"key": r[0], "value": r[1], "category": r[2], "when": r[3]} for r in rows]
        if not memories:
            return {"memories": [], "message": "No memories found."}
        return {"memories": memories, "count": len(memories)}
    except Exception as e:
        log.error("recall() failed: %s", e)
        return {"status": "error", "message": str(e)}


def forget(user_id: int, key: str) -> dict:
    """Delete a memory by key."""
    try:
        conn = get_conn()
        try:
            cur = conn.cursor()
            if is_postgres():
                cur.execute(
                    "DELETE FROM memories WHERE user_id=%s AND key ILIKE %s",
                    (user_id, f"%{key}%")
                )
            else:
                cur.execute(
                    "DELETE FROM memories WHERE user_id=? AND key LIKE ?",
                    (user_id, f"%{key}%")
                )
            conn.commit()
        finally:
            conn.close()

        return {"status": "ok", "message": f"🗑️ Forgot: {key}"}
    except Exception as e:
        log.error("forget() failed: %s", e)
        return {"error": str(e)}

        msg = f"🗑️ Forgot: {key}"
        log.info(msg)
        return {"status": "ok", "message": msg}

    except Exception as e:
        log.error("forget() failed: %s", e)
        return {"status": "error", "message": str(e)}


def register(brain):
    """Register memory tools with the brain."""
    _init_db()
    brain.register_tool("remember", remember)
    brain.register_tool("recall", recall)
    brain.register_tool("forget", forget)
    brain.register_tool("get_memory_context", get_context)
    log.info("✅ Memory extension registered — backend: %s", "postgres" if is_postgres() else "sqlite")
