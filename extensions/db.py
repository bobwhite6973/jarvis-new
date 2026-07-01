"""
Shared database utility for JARVIS extensions.
Uses Postgres (via DATABASE_URL env var) as primary connection.
Falls back to SQLite only if DATABASE_URL is not set or connection fails
after retries.
"""

import os
import time
import logging
from pathlib import Path

log = logging.getLogger("jarvis.db")

SQLITE_PATH = Path(os.environ.get("SQLITE_PATH", "data/jarvis.db"))
CONNECT_RETRIES = int(os.environ.get("DB_CONNECT_RETRIES", "3"))
RETRY_DELAY_SECONDS = float(os.environ.get("DB_RETRY_DELAY", "0.75"))

DB_TYPE = "postgres" if os.environ.get("DATABASE_URL") else "sqlite"


def _database_url():
    # Read live from env every call - never cache at import time.
    return os.environ.get("DATABASE_URL")


def get_conn():
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
                return conn
            except Exception as e:
                last_err = e
                log.error("Postgres connection attempt %d/%d failed: %s", attempt, CONNECT_RETRIES, e)
                if attempt < CONNECT_RETRIES:
                    time.sleep(RETRY_DELAY_SECONDS)

        log.critical(
            "Postgres connection FAILED after %d attempts (%s) — falling back to EPHEMERAL SQLite.",
            CONNECT_RETRIES, last_err
        )
    else:
        log.critical(
            "DATABASE_URL is not set in this process's environment — falling back to EPHEMERAL SQLite. "
            "If you just added it in Render, the running process must be RESTARTED/REDEPLOYED to pick it up."
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
    return "%s" if is_postgres() else "?"


def execute(conn, sql: str, params: tuple = ()):
    if is_postgres():
        sql = sql.replace("?", "%s")
    conn.cursor().execute(sql, params)


def executescript_compat(conn, sql: str):
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
    if is_postgres():
        sql = sql.replace("?", "%s")
        cur = conn.cursor()
        cur.execute(sql, params)
        return cur.fetchall()
    else:
        return conn.execute(sql, params).fetchall()


def fetchone(conn, sql: str, params: tuple = ()):
    if is_postgres():
        sql = sql.replace("?", "%s")
        cur = conn.cursor()
        cur.execute(sql, params)
        return cur.fetchone()
    else:
        return conn.execute(sql, params).fetchone()


log.info("JARVIS DB layer initialized — DATABASE_URL present at import: %s", bool(os.environ.get("DATABASE_URL")))
