"""
Extension: memory_store
Persistent encrypted key-value storage for JARVIS.
Survives /clear commands. Use for preferences, settings, wallet addresses, etc.
Adds /remember and /recall Telegram commands.
"""

import os
import sqlite3
import logging
from pathlib import Path
from cryptography.fernet import Fernet

log = logging.getLogger("jarvis.ext.memory_store")

DB_PATH = Path("data/persistent.db")
KEY_FILE = Path("data/jarvis.key")


def _load_or_create_key() -> bytes:
    KEY_FILE.parent.mkdir(exist_ok=True)
    if KEY_FILE.exists():
        return KEY_FILE.read_bytes()
    key = Fernet.generate_key()
    KEY_FILE.write_bytes(key)
    return key


def _cipher():
    return Fernet(_load_or_create_key())


def _init_db():
    DB_PATH.parent.mkdir(exist_ok=True)
    with sqlite3.connect(DB_PATH) as conn:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS user_profile (
                user_id TEXT NOT NULL,
                key TEXT NOT NULL,
                value TEXT NOT NULL,
                protected INTEGER DEFAULT 0,
                PRIMARY KEY (user_id, key)
            )
        """)
        conn.commit()


def store(user_id: str, key: str, value: str, protected: bool = False) -> str:
    encrypted = _cipher().encrypt(value.encode()).decode()
    with sqlite3.connect(DB_PATH) as conn:
        conn.execute(
            "INSERT OR REPLACE INTO user_profile (user_id,key,value,protected) VALUES (?,?,?,?)",
            (user_id, key, encrypted, int(protected))
        )
        conn.commit()
    flag = "protected" if protected else "standard"
    return f"Stored '{key}' ({flag})"


def retrieve(user_id: str, key: str) -> str | None:
    with sqlite3.connect(DB_PATH) as conn:
        row = conn.execute(
            "SELECT value FROM user_profile WHERE user_id=? AND key=?",
            (user_id, key)
        ).fetchone()
    if row:
        return _cipher().decrypt(row[0].encode()).decode()
    return None


def list_keys(user_id: str) -> list[str]:
    with sqlite3.connect(DB_PATH) as conn:
        rows = conn.execute(
            "SELECT key, protected FROM user_profile WHERE user_id=?",
            (user_id,)
        ).fetchall()
    return [f"{r[0]} ({'protected' if r[1] else 'standard'})" for r in rows]


def soft_clear(user_id: str):
    with sqlite3.connect(DB_PATH) as conn:
        conn.execute(
            "DELETE FROM user_profile WHERE user_id=? AND protected=0",
            (user_id,)
        )
        conn.commit()


async def handle_remember(query: str) -> str:
    """
    Called by brain on 'remember' intent.
    Parses: remember [key] = [value]
    """
    try:
        parts = query.lower().replace("remember", "").strip()
        if "=" in parts:
            key, value = parts.split("=", 1)
            store("bob_white", key.strip(), value.strip())
            return f"Got it — stored '{key.strip()}'"
        return "Format: remember [key] = [value]\nExample: remember groq model = llama-3.3-70b"
    except Exception as e:
        return f"Error storing: {e}"


async def handle_recall(query: str) -> str:
    """
    Called by brain on 'recall' intent.
    Parses: recall [key]
    """
    try:
        key = query.lower().replace("recall", "").strip()
        if not key:
            keys = list_keys("bob_white")
            if not keys:
                return "Nothing stored yet."
            return "Stored keys:\n" + "\n".join(f"  {k}" for k in keys)
        value = retrieve("bob_white", key)
        if value:
            return f"{key}: {value}"
        return f"Nothing stored for '{key}'"
    except Exception as e:
        return f"Error retrieving: {e}"


def register(brain):
    _init_db()
    brain.register_extension("memory_store", handle_remember)
    brain.register_extension("memory_recall", handle_recall)
    log.info("memory_store extension loaded")
