"""
Shared database utility for JARVIS extensions.
Uses Postgres (via DATABASE_URL env var) as primary connection.
Falls back to SQLite only if DATABASE_URL is not set or connection fails
after retries.
Falls back to SQLite only if DATABASE_URL is not set or connection fails.

Usage:
    from extensions.db import get_conn, DB_TYPE
"""

import os
import time
import logging
from pathlib import Path

log = logging.getLogger("jarvis.db")

# No hardcoded credentials — must be provided via environment variable.
DATABASE_URL = os.environ.get("DATABASE_URL")


DB_TYPE = "postgres" if DATABASE_URL else "sqlite"


def get_conn():
    """
    Returns a database connection.
    - Postgres if DATABASE_URL env var is set and connection succeeds
    - SQLite fallback if DATABASE_URL is missing or connection fails
    """
    global DB_TYPE

    if DATABASE_URL:
        try:
            import psycopg2
            conn = psycopg2.connect(DATABASE_URL, sslmode="require")
            DB_TYPE = "postgres"
            log.debug("Connected to Postgres")
            return conn
        except ImportError:
            log.error("psycopg2 not installed — falling back to SQLite")
        except Exception as e:
            log.error("Postgres connection failed: %s — falling back to SQLite", e)
    else:
        log.warning("DATABASE_URL not set — falling back to SQLite")

    # SQLite fallback
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
