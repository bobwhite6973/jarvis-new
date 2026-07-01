"""
Shared database utility for JARVIS extensions.
Automatically uses Supabase (Postgres) if DATABASE_URL is set in env,
otherwise falls back to local SQLite for development.

Usage:
    from extensions.db import get_conn, DB_TYPE
"""

import os
import logging
from pathlib import Path

log = logging.getLogger("jarvis.db")

DATABASE_URL = os.environ.get("DATABASE_URL", "")
DB_TYPE = "postgres" if DATABASE_URL else "sqlite"

# SQLite fallback path
SQLITE_PATH = Path(os.environ.get("SQLITE_PATH", "data/jarvis.db"))


def get_conn():
    """
    Returns a database connection.
    - Postgres (Supabase) if DATABASE_URL is set
    - SQLite fallback otherwise
    """
    if DB_TYPE == "postgres":
        try:
            import psycopg2
            conn = psycopg2.connect(DATABASE_URL, sslmode="require")
            return conn
        except ImportError:
            log.error("psycopg2 not installed — falling back to SQLite")
        except Exception as e:
            log.error("Postgres connection failed: %s — falling back to SQLite", e)

    # SQLite fallback
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


log.info("JARVIS DB layer initialized — using %s", DB_TYPE.upper())
