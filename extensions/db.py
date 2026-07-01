"""
Shared database utility for JARVIS extensions.
Uses Postgres (via DATABASE_URL env var) as primary connection.
Falls back to SQLite only if DATABASE_URL is not set or connection fails
after retries.

Usage:
    from extensions.db import get_conn, DB_TYPE, is_postgres
"""

import os
import time
import logging
from pathlib import Path

log = logging.getLogger("jarvis.db")

# SQLite fallback path
SQLITE_PATH = Path(os.environ.get("SQLITE_PATH", "data/jarvis.db"))

# Number of connection attempts before giving up and using SQLite.
CONNECT_RETRIES = int(os.environ.get("DB_CONNECT_RETRIES", "3"))
RETRY_DELAY_SECONDS = float(os.environ.get("DB_RETRY_DELAY", "0.75"))

# Tracks the backend actually in use as of the most recent get_conn() call.
# NOTE: this reflects the *last* connection attempt, not a permanent choice.
DB_TYPE = "postgres" if os.environ.get("DATABASE_URL") else "sqlite"


def _database_url():
    """
    Always re-read the env var at call time rather than caching it once
    at import time. This does NOT fix the need for Render to restart the
    process when a new env var is added (env vars are injected at process
    start, full stop) — but it avoids a second, needless source of
    staleness if the env var is ever mutated programmatically or the
    module gets re-imported.
    """
    return os.environ.get("DATABASE_URL")


def get_conn():
    """
    Returns a database connection.
    - Postgres if DATABASE_URL env var is set and connection succeeds
      (retries a few times to survive transient network blips before
      giving up).
    - SQLite fallback if DATABASE_URL is missing or all retries fail.
      Falling back is now logged at CRITICAL level so it can't be missed
      in Render logs.
    """
    global DB_TYPE

    database_url = _database_url()

    if database_url:
        last_err = None
        try:
            import psycopg2
        except ImportError:
            log.critical("psycopg2 not installed — falling back to SQLite. Memory will NOT persist across redeploys.")
            DB_TYPE = "sqlite"
            return _sqlite_conn()

        for attempt in range(1, CONNECT_RETRIES + 1):
            try:
                conn = psycopg2.connect(database_url, sslmode="require", connect_timeout=5)
                DB_TYPE = "postgres"
                if attempt > 1:
                    log.warning("Postgres connection succeeded on retry attempt %d", attempt)
                else:
                    log.debug("Connected to Postgres")
                return conn
            except Exception as e:
                last_err = e
                log.error("Postgres connection attempt %d/%d failed: %s", attempt, CONNECT_RETRIES, e)
                if attempt < CONNECT_RETRIES:
                    time.sleep(RETRY_DELAY_SECONDS)

        log.critical(
            "Postgres connection FAILED after %d attempts (%s) — falling back to EPHEMERAL SQLite. "
            "Any data written now will be LOST on next redeploy.",
            CONNECT_RETRIES, last_err
        )
    else:
        log.critical(
            "DATABASE_URL is not set in this process's environment — falling back to EPHEMERAL SQLite. "
            "If you just added it in Render, the running process must be RESTARTED/REDEPLOYED to pick it up; "
            "adding an env var alone does not update a process already running."
        )

    DB_TYPE = "sqlite"
    return _sqlite_conn()


def _sqlite_conn():
    import sqlite3
    SQLITE_PATH.parent.mkdir(parents=True, exist_ok=True)
    return sqlite3.connect(SQLITE_PATH)


def is_postgres() -> bool:
    return DB_TYPE == "postgres"


def placeholder() -> str:
    """Returns the correct SQL placeholder for the active DB."""
    return "%s" if is_postgres() else "?"


def execute(conn, sql: str, params: tuple = ()):
    """
    Execute a SQL statement with correct placeholder style.
    Translates ? -> %s for Postgres automatically.
    """
    if is_postgres():
        sql = sql.replace("?", "%s")
    conn.cursor().execute(sql, params)


def executescript_compat(conn, sql: str):
    """
    Execute a multi-statement SQL script.
    Uses executescript for SQLite, executes statements individually for Postgres.
    """
    if is_postgres():
        cur = conn.cursor()
        for statement in sql.strip().split(";"):
            s = statement.strip()
            if s:
                cur.execute(s)
        conn.commit()
    else:
        conn.executescript(sql)


def fetchall(conn, sql: str, params: tuple = ()) -> list:
    """Execute a SELECT and return all rows."""
    if is_postgres():
        sql = sql.replace("?", "%s")
        cur = conn.cursor()
        cur.execute(sql, params)
        return cur.fetchall()
    else:
        return conn.execute(sql, params).fetchall()


def fetchone(conn, sql: str, params: tuple = ()):
    """Execute a SELECT and return one row."""
    if is_postgres():
        sql = sql.replace("?", "%s")
        cur = conn.cursor()
        cur.execute(sql, params)
        return cur.fetchone()
    else:
        return conn.execute(sql, params).fetchone()


log.info("JARVIS DB layer initialized — DATABASE_URL present at import: %s", bool(os.environ.get("DATABASE_URL")))
