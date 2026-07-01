"""
Extension: learning
JARVIS adaptive learning loop.

Tracks:
- Tool call outcomes (success/failure/timeout)
- User feedback (thumbs up/down)
- Patterns that work vs don't work
- Crypto/trading insights that proved correct

Uses Supabase (Postgres) if DATABASE_URL is set, falls back to SQLite.
Injects relevant lessons into brain system prompt at startup.
Gets smarter with every interaction.
"""

import json
import logging
from datetime import datetime, timezone

from extensions.db import get_conn, is_postgres, fetchall, fetchone

log = logging.getLogger("jarvis.learning")
MAX_LESSONS = 20


def _init_db():
    conn = get_conn()
    try:
        cur = conn.cursor()
        if is_postgres():
            cur.execute("""
                CREATE TABLE IF NOT EXISTS interactions (
                    id        SERIAL PRIMARY KEY,
                    timestamp TEXT NOT NULL,
                    category  TEXT NOT NULL,
                    action    TEXT NOT NULL,
                    outcome   TEXT NOT NULL,
                    score     REAL DEFAULT 0.0,
                    context   TEXT,
                    lesson    TEXT
                )
            """)
            cur.execute("""
                CREATE TABLE IF NOT EXISTS lessons (
                    id            SERIAL PRIMARY KEY,
                    timestamp     TEXT NOT NULL,
                    category      TEXT NOT NULL,
                    lesson        TEXT NOT NULL,
                    confidence    REAL DEFAULT 0.5,
                    times_applied INTEGER DEFAULT 0,
                    times_correct INTEGER DEFAULT 0
                )
            """)
            cur.execute("""
                CREATE TABLE IF NOT EXISTS feedback (
                    id        SERIAL PRIMARY KEY,
                    timestamp TEXT NOT NULL,
                    user_id   TEXT,
                    message   TEXT,
                    response  TEXT,
                    rating    INTEGER,
                    notes     TEXT
                )
            """)
        else:
            conn.executescript("""
                CREATE TABLE IF NOT EXISTS interactions (
                    id        INTEGER PRIMARY KEY AUTOINCREMENT,
                    timestamp TEXT NOT NULL,
                    category  TEXT NOT NULL,
                    action    TEXT NOT NULL,
                    outcome   TEXT NOT NULL,
                    score     REAL DEFAULT 0.0,
                    context   TEXT,
                    lesson    TEXT
                );
                CREATE TABLE IF NOT EXISTS lessons (
                    id            INTEGER PRIMARY KEY AUTOINCREMENT,
                    timestamp     TEXT NOT NULL,
                    category      TEXT NOT NULL,
                    lesson        TEXT NOT NULL,
                    confidence    REAL DEFAULT 0.5,
                    times_applied INTEGER DEFAULT 0,
                    times_correct INTEGER DEFAULT 0
                );
                CREATE TABLE IF NOT EXISTS feedback (
                    id        INTEGER PRIMARY KEY AUTOINCREMENT,
                    timestamp TEXT NOT NULL,
                    user_id   TEXT,
                    message   TEXT,
                    response  TEXT,
                    rating    INTEGER,
                    notes     TEXT
                );
            """)
        conn.commit()
        log.info("Learning DB initialized — backend: %s", "postgres" if is_postgres() else "sqlite")
    finally:
        conn.close()


def record_tool_call(tool_name: str, args: dict, result: dict, success: bool) -> str:
    """Record a tool call outcome."""
    outcome = "success" if success else "failure"
    error = result.get("error", "") if isinstance(result, dict) else ""
    lesson = None
    if not success and error:
        lesson = f"Tool '{tool_name}' failed with: {error[:100]}"

    conn = get_conn()
    try:
        cur = conn.cursor()
        now = datetime.now(timezone.utc).isoformat()
        if is_postgres():
            cur.execute("""
                INSERT INTO interactions (timestamp, category, action, outcome, score, context, lesson)
                VALUES (%s, %s, %s, %s, %s, %s, %s)
            """, (now, "tool_call", tool_name, outcome, 1.0 if success else 0.0,
                  json.dumps(args)[:500], lesson))
        else:
            cur.execute("""
                INSERT INTO interactions (timestamp, category, action, outcome, score, context, lesson)
                VALUES (?, ?, ?, ?, ?, ?, ?)
            """, (now, "tool_call", tool_name, outcome, 1.0 if success else 0.0,
                  json.dumps(args)[:500], lesson))
        conn.commit()
    except Exception as e:
        log.error("record_tool_call() failed: %s", e)
    finally:
        conn.close()

    return outcome


def store_lesson(category: str, lesson: str, confidence: float = 0.5) -> dict:
    """Manually store a lesson JARVIS should remember."""
    conn = get_conn()
    try:
        cur = conn.cursor()
        now = datetime.now(timezone.utc).isoformat()
        if is_postgres():
            cur.execute("""
                INSERT INTO lessons (timestamp, category, lesson, confidence)
                VALUES (%s, %s, %s, %s)
            """, (now, category, lesson, confidence))
        else:
            cur.execute("""
                INSERT INTO lessons (timestamp, category, lesson, confidence)
                VALUES (?, ?, ?, ?)
            """, (now, category, lesson, confidence))
        conn.commit()
        msg = f"✅ Lesson stored: [{category}] {lesson}"
        log.info(msg)
        return {"status": "ok", "message": msg}
    except Exception as e:
        log.error("store_lesson() failed: %s", e)
        return {"status": "error", "message": str(e)}
    finally:
        conn.close()


def get_lessons(limit: int = MAX_LESSONS) -> dict:
    """Return a summary of what JARVIS has learned."""
    conn = get_conn()
    try:
        cur = conn.cursor()
        if is_postgres():
            cur.execute(
                "SELECT id, category, lesson, confidence FROM lessons ORDER BY confidence DESC, timestamp DESC LIMIT %s",
                (limit,)
            )
        else:
            cur.execute(
                "SELECT id, category, lesson, confidence FROM lessons ORDER BY confidence DESC, timestamp DESC LIMIT ?",
                (limit,)
            )
        rows = cur.fetchall()
        lessons = [{"id": r[0], "category": r[1], "lesson": r[2], "confidence": r[3]} for r in rows]
        return {"status": "ok", "lessons": lessons, "count": len(lessons)}
    except Exception as e:
        log.error("get_lessons() failed: %s", e)
        return {"status": "error", "message": str(e)}
    finally:
        conn.close()


def delete_lesson(lesson_id: int) -> dict:
    """Delete a single lesson row by its id. Returns status + how many rows were removed."""
    conn = get_conn()
    try:
        cur = conn.cursor()
        if is_postgres():
            cur.execute("DELETE FROM lessons WHERE id = %s", (lesson_id,))
        else:
            cur.execute("DELETE FROM lessons WHERE id = ?", (lesson_id,))
        deleted = cur.rowcount
        conn.commit()
        if deleted > 0:
            msg = f"🗑️ Deleted lesson id={lesson_id}"
        else:
            msg = f"⚠️ No lesson found with id={lesson_id}"
        log.info(msg)
        return {"status": "ok", "deleted": deleted, "message": msg}
    except Exception as e:
        log.error("delete_lesson() failed: %s", e)
        return {"status": "error", "message": str(e)}
    finally:
        conn.close()


def record_feedback(user_id: str, message: str, response: str, rating: int, notes: str = None) -> dict:
    """Record user feedback on a response. rating: 1 = thumbs up, -1 = thumbs down, 0 = neutral"""
    conn = get_conn()
    try:
        cur = conn.cursor()
        now = datetime.now(timezone.utc).isoformat()
        if is_postgres():
            cur.execute("""
                INSERT INTO feedback (timestamp, user_id, message, response, rating, notes)
                VALUES (%s, %s, %s, %s, %s, %s)
            """, (now, user_id, message, response, rating, notes))
        else:
            cur.execute("""
                INSERT INTO feedback (timestamp, user_id, message, response, rating, notes)
                VALUES (?, ?, ?, ?, ?, ?)
            """, (now, user_id, message, response, rating, notes))
        conn.commit()
        emoji = "👍" if rating > 0 else "👎" if rating < 0 else "😐"
        msg = f"{emoji} Feedback recorded (rating={rating})"
        log.info(msg)
        return {"status": "ok", "message": msg}
    except Exception as e:
        log.error("record_feedback() failed: %s", e)
        return {"status": "error", "message": str(e)}
    finally:
        conn.close()


def learning_summary() -> dict:
    """Return a summary of what JARVIS has learned."""
    return get_lessons()


def register(brain) -> None:
    """Register learning tools with the brain."""
    brain.register_tool("store_lesson", store_lesson)
    brain.register_tool("get_lessons", get_lessons)
    brain.register_tool("delete_lesson", delete_lesson)
    brain.register_tool("record_feedback", record_feedback)
    brain.register_tool("learning_summary", learning_summary)
    log.info("learning tools registered: store_lesson, get_lessons, delete_lesson, record_feedback, learning_summary")
