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
            import sqlite3
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
        sql = """
            INSERT INTO interactions (timestamp, category, action, outcome, score, context, lesson)
            VALUES (?, ?, ?, ?, ?, ?, ?)
        """
        params = (
            datetime.now(timezone.utc).isoformat(),
            "tool_call",
            tool_name,
            outcome,
            1.0 if success else -0.5,
            json.dumps({"args": str(args)[:200], "error": error[:200]}),
            lesson
        )
        if is_postgres():
            sql = sql.replace("?", "%s")
        cur.execute(sql, params)
        conn.commit()
    finally:
        conn.close()

    if not success and lesson:
        _maybe_store_lesson("tool_reliability", lesson, confidence=0.6)

    return outcome


def record_feedback(user_id: str, message: str, response: str, rating: int, notes: str = "") -> str:
    """
    Record user feedback on a response.
    rating: 1 = thumbs up, -1 = thumbs down, 0 = neutral
    """
    conn = get_conn()
    try:
        cur = conn.cursor()
        sql = """
            INSERT INTO feedback (timestamp, user_id, message, response, rating, notes)
            VALUES (?, ?, ?, ?, ?, ?)
        """
        params = (
            datetime.now(timezone.utc).isoformat(),
            str(user_id),
            message[:500],
            response[:500],
            rating,
            notes[:200]
        )
        if is_postgres():
            sql = sql.replace("?", "%s")
        cur.execute(sql, params)
        conn.commit()
    finally:
        conn.close()

    if rating > 0:
        _maybe_store_lesson("response_quality",
            f"This type of response worked well: {message[:100]}", confidence=0.7)
    elif rating < 0:
        _maybe_store_lesson("response_quality",
            f"This type of response was unhelpful: {message[:100]}", confidence=0.7)

    return "Feedback recorded. JARVIS will learn from this."


def record_trade_outcome(token: str, action: str, entry_price: float,
                          exit_price: float = None, pnl: float = None) -> str:
    """Record a trading decision outcome."""
    score = 0.0
    outcome = "open"
    lesson = None

    if exit_price and entry_price:
        pnl = pnl or (exit_price - entry_price)
        score = pnl / entry_price
        outcome = "win" if pnl > 0 else "loss"
        if outcome == "win":
            lesson = f"Buying {token} at ${entry_price:.4f} and selling at ${exit_price:.4f} was profitable"
        else:
            lesson = f"Buying {token} at ${entry_price:.4f} and selling at ${exit_price:.4f} was a loss"

    conn = get_conn()
    try:
        cur = conn.cursor()
        sql = """
            INSERT INTO interactions (timestamp, category, action, outcome, score, context, lesson)
            VALUES (?, ?, ?, ?, ?, ?, ?)
        """
        params = (
            datetime.now(timezone.utc).isoformat(),
            "trade",
            f"{action} {token}",
            outcome,
            score,
            json.dumps({"token": token, "entry": entry_price, "exit": exit_price, "pnl": pnl}),
            lesson
        )
        if is_postgres():
            sql = sql.replace("?", "%s")
        cur.execute(sql, params)
        conn.commit()
    finally:
        conn.close()

    if lesson:
        _maybe_store_lesson("trading", lesson, confidence=0.8)

    return f"Trade outcome recorded: {outcome} | score: {score:.4f}"


def store_lesson(category: str, lesson: str, confidence: float = 0.7) -> str:
    """Manually store a lesson JARVIS should remember."""
    _maybe_store_lesson(category, lesson, confidence, force=True)
    return f"Lesson stored: {lesson[:100]}"


def _maybe_store_lesson(category: str, lesson: str, confidence: float, force: bool = False):
    """Store a lesson if it's new or reinforces an existing one."""
    if not lesson:
        return

    conn = get_conn()
    try:
        cur = conn.cursor()

        # Check for existing similar lesson
        if is_postgres():
            existing = fetchone(conn,
                "SELECT id, confidence, times_applied FROM lessons "
                "WHERE category = %s AND lesson ILIKE %s",
                (category, f"%{lesson[:50]}%")
            )
        else:
            existing = fetchone(conn,
                "SELECT id, confidence, times_applied FROM lessons "
                "WHERE category = ? AND lesson LIKE ?",
                (category, f"%{lesson[:50]}%")
            )

        if existing:
            if is_postgres():
                cur.execute("""
                    UPDATE lessons SET confidence = LEAST(1.0, confidence + 0.1),
                    times_applied = times_applied + 1
                    WHERE id = %s
                """, (existing[0],))
            else:
                cur.execute("""
                    UPDATE lessons SET confidence = MIN(1.0, confidence + 0.1),
                    times_applied = times_applied + 1
                    WHERE id = ?
                """, (existing[0],))
        elif force or confidence >= 0.6:
            sql = """
                INSERT INTO lessons (timestamp, category, lesson, confidence)
                VALUES (?, ?, ?, ?)
            """
            if is_postgres():
                sql = sql.replace("?", "%s")
            cur.execute(sql, (datetime.now(timezone.utc).isoformat(), category, lesson, confidence))

        conn.commit()
    finally:
        conn.close()


def get_lessons(category: str = None, limit: int = MAX_LESSONS) -> list:
    """Get top lessons by confidence for injection into system prompt."""
    conn = get_conn()
    try:
        if category:
            rows = fetchall(conn,
                "SELECT lesson, confidence FROM lessons "
                "WHERE category = ? ORDER BY confidence DESC, times_applied DESC LIMIT ?",
                (category, limit)
            )
        else:
            rows = fetchall(conn,
                "SELECT lesson, confidence FROM lessons "
                "ORDER BY confidence DESC, times_applied DESC LIMIT ?",
                (limit,)
            )
    finally:
        conn.close()

    return [row[0] for row in rows]


def get_learning_summary() -> str:
    """Return a summary of what JARVIS has learned."""
    conn = get_conn()
    try:
        total_interactions = fetchone(conn, "SELECT COUNT(*) FROM interactions")[0]
        total_lessons = fetchone(conn, "SELECT COUNT(*) FROM lessons")[0]
        total_feedback = fetchone(conn, "SELECT COUNT(*) FROM feedback")[0]
        positive = fetchone(conn, "SELECT COUNT(*) FROM feedback WHERE rating > 0")[0]
        negative = fetchone(conn, "SELECT COUNT(*) FROM feedback WHERE rating < 0")[0]

        top_lessons = fetchall(conn,
            "SELECT category, lesson, confidence FROM lessons "
            "ORDER BY confidence DESC LIMIT 5", ()
        )
        tool_stats = fetchall(conn,
            "SELECT action, COUNT(*) as calls, "
            "SUM(CASE WHEN outcome='success' THEN 1 ELSE 0 END) as successes "
            "FROM interactions WHERE category='tool_call' "
            "GROUP BY action ORDER BY calls DESC LIMIT 5", ()
        )
    finally:
        conn.close()

    lines = [
        "**JARVIS Learning Summary**\n",
        f"Total interactions tracked: {total_interactions}",
        f"Lessons learned: {total_lessons}",
        f"User feedback: {total_feedback} total ({positive} 👍 / {negative} 👎)\n",
    ]

    if top_lessons:
        lines.append("**Top Lessons:**")
        for cat, lesson, conf in top_lessons:
            lines.append(f"  [{cat}] {lesson[:80]} (confidence: {conf:.0%})")

    if tool_stats:
        lines.append("\n**Tool Reliability:**")
        for tool, calls, successes in tool_stats:
            rate = (successes or 0) / calls * 100 if calls > 0 else 0
            lines.append(f"  {tool}: {calls} calls, {rate:.0f}% success")

    return "\n".join(lines)


def build_lesson_prompt() -> str:
    """Build a lessons block to inject into brain system prompt."""
    lessons = get_lessons(limit=10)
    if not lessons:
        return ""
    lines = ["\n\nLESSONS LEARNED (from past experience):"]
    for lesson in lessons:
        lines.append(f"- {lesson}")
    return "\n".join(lines)


def thumbs_up(user_id: str = "1", message: str = "", response: str = "") -> str:
    """User gave thumbs up — positive feedback."""
    return record_feedback(user_id, message, response, rating=1)


def thumbs_down(user_id: str = "1", message: str = "", response: str = "", notes: str = "") -> str:
    """User gave thumbs down — negative feedback."""
    return record_feedback(user_id, message, response, rating=-1, notes=notes)


def register(brain):
    _init_db()

    brain.register_tool("record_feedback", record_feedback)
    brain.register_tool("record_tool_call", record_tool_call)
    brain.register_tool("record_trade", record_trade_outcome)
    brain.register_tool("store_lesson", store_lesson)
    brain.register_tool("get_lessons", lambda: get_lessons())
    brain.register_tool("learning_summary", get_learning_summary)
    brain.register_tool("thumbs_up", thumbs_up)
    brain.register_tool("thumbs_down", thumbs_down)

    lesson_prompt = build_lesson_prompt()
    if lesson_prompt:
        brain.system_prompt += lesson_prompt
        log.info("Injected %d lessons into system prompt", len(get_lessons()))

    brain._get_lessons = get_lessons
    log.info("✅ Learning extension loaded — backend: %s", "postgres" if is_postgres() else "sqlite")
