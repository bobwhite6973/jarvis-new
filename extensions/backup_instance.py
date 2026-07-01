"""
JARVIS Backup Instance Manager
Phase 1 - Step 7: Never Dies Protocol
Ensures JARVIS always has a fallback running instance.
"""

import os
import json
import hashlib
import requests
import datetime
from pathlib import Path

BACKUP_LOG = Path("extensions/backup_log.json")
RENDER_PRIMARY = os.getenv("RENDER_PRIMARY_URL", "https://jarvis-new.onrender.com")
RENDER_BACKUP = os.getenv("RENDER_BACKUP_URL", "")
HEALTH_ENDPOINT = "/health"


def _log(event: str, detail: str = ""):
    """Append event to backup log."""
    log = []
    if BACKUP_LOG.exists():
        try:
            log = json.loads(BACKUP_LOG.read_text())
        except Exception:
            log = []
    log.append({
        "timestamp": datetime.datetime.utcnow().isoformat(),
        "event": event,
        "detail": detail
    })
    # Keep last 100 entries
    log = log[-100:]
    BACKUP_LOG.write_text(json.dumps(log, indent=2))


def check_primary_health(timeout: int = 10) -> dict:
    """Ping the primary JARVIS instance and return status."""
    try:
        url = RENDER_PRIMARY.rstrip("/") + HEALTH_ENDPOINT
        resp = requests.get(url, timeout=timeout)
        alive = resp.status_code == 200
        _log("health_check", f"Primary {'UP' if alive else 'DOWN'} — {resp.status_code}")
        return {
            "status": "up" if alive else "down",
            "code": resp.status_code,
            "url": url,
            "checked_at": datetime.datetime.utcnow().isoformat()
        }
    except Exception as e:
        _log("health_check", f"Primary UNREACHABLE — {str(e)}")
        return {
            "status": "unreachable",
            "error": str(e),
            "url": RENDER_PRIMARY,
            "checked_at": datetime.datetime.utcnow().isoformat()
        }


def check_backup_health(timeout: int = 10) -> dict:
    """Ping the backup JARVIS instance."""
    if not RENDER_BACKUP:
        return {"status": "not_configured", "detail": "Set RENDER_BACKUP_URL env var"}
    try:
        url = RENDER_BACKUP.rstrip("/") + HEALTH_ENDPOINT
        resp = requests.get(url, timeout=timeout)
        alive = resp.status_code == 200
        _log("backup_health_check", f"Backup {'UP' if alive else 'DOWN'} — {resp.status_code}")
        return {
            "status": "up" if alive else "down",
            "code": resp.status_code,
            "url": url,
            "checked_at": datetime.datetime.utcnow().isoformat()
        }
    except Exception as e:
        _log("backup_health_check", f"Backup UNREACHABLE — {str(e)}")
        return {
            "status": "unreachable",
            "error": str(e),
            "url": RENDER_BACKUP,
            "checked_at": datetime.datetime.utcnow().isoformat()
        }


def failover_status() -> dict:
    """Check both instances and determine if failover is needed."""
    primary = check_primary_health()
    backup = check_backup_health()

    failover_needed = primary["status"] not in ("up",)

    if failover_needed:
        _log("FAILOVER_TRIGGERED", f"Primary down, backup status: {backup['status']}")

    return {
        "primary": primary,
        "backup": backup,
        "failover_needed": failover_needed,
        "recommendation": (
            "⚠️ PRIMARY DOWN — Route traffic to backup!" if failover_needed
            else "✅ Primary healthy — no action needed"
        )
    }


def instance_summary() -> str:
    """Human-readable summary of both instances."""
    status = failover_status()
    p = status["primary"]
    b = status["backup"]

    lines = [
        "🤖 JARVIS Instance Monitor",
        f"  Primary:  {p['status'].upper()} — {p.get('url', 'N/A')}",
        f"  Backup:   {b['status'].upper()} — {b.get('url', 'N/A')}",
        f"  Failover: {'⚠️ NEEDED' if status['failover_needed'] else '✅ NOT NEEDED'}",
        f"  Checked:  {datetime.datetime.utcnow().strftime('%Y-%m-%d %H:%M:%S')} UTC"
    ]
    return "\n".join(lines)


if __name__ == "__main__":
    print(instance_summary())
