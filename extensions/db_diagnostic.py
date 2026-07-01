"""
Extension: db_diagnostic
Read-only diagnostic tool to confirm which database backend JARVIS is
actually running on (Postgres vs ephemeral SQLite fallback), and report
basic table health. Does NOT modify any data.
"""

import logging
from datetime import datetime, timezone

from extensions.db import get_conn, DB_TYPE, is_postgres, fetchall, fetchone, DATABASE_URL

log = logging.getLogger("jarvis.ext.db_diagnostic")


def diagnose_db(_query: str = "") -> str:
    """
    Returns a plain-text diagnostic report:
    - Which DB backend is active (postgres/sqlite)
    - Whether DATABASE_URL env var is set (not its value)
    - Whether a live connection succeeds
    - Row counts for key tables (read-only SELECT COUNT(*))
    """
    lines = [f"DB Diagnostic — {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')}\n"]

    lines.append(f"DATABASE_URL set: {'yes' if DATABASE_URL else 'no'}")
    lines.append(f"Configured DB_TYPE (module import time): {DB_TYPE.upper()}")

    try:
        conn = get_conn()
        active_type = "postgres" if is_postgres() else "sqlite"
        lines.append(f"Live connection succeeded — active backend: {active_type.upper()}")

        tables = ["memories", "notes", "bot_status", "lessons", "interactions", "feedback"]
        lines.append("\nTable row counts (read-only):")
        for t in tables:
            try:
                row = fetchone(conn, f"SELECT COUNT(*) FROM {t}")
                count = row[0] if row else "n/a"
                lines.append(f"  {t}: {count}")
            except Exception as e:
                lines.append(f"  {t}: not found / error ({e})")

        try:
            conn.close()
        except Exception:
            pass

    except Exception as e:
        lines.append(f"Live connection FAILED: {e}")
        lines.append("This means JARVIS is likely degraded to ephemeral storage or has no DB access.")

    lines.append(
        "\nNote: if active backend is SQLITE, all memory/lessons data is "
        "ephemeral and will be lost on the next Render redeploy."
    )

    return "\n".join(lines)


def register(brain):
    brain.register_extension("db_diagnostic", diagnose_db)
    log.info("db_diagnostic extension registered")
