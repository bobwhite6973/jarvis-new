"""
JARVIS Backup Instance Manager
Phase 1 - Never Dies Protocol
Monitors primary instance, flags failover if down.
"""

import requests
import json
import os
from datetime import datetime

PRIMARY_URL = os.getenv("PRIMARY_JARVIS_URL", "https://jarvis-new.onrender.com")
BACKUP_URL = os.getenv("BACKUP_JARVIS_URL", "")
LOG_FILE = "backup_log.json"
HEALTH_ENDPOINT = "/health"
TIMEOUT = 10


def _log(entry: dict):
    """Append a log entry to backup_log.json"""
    logs = []
    if os.path.exists(LOG_FILE):
        try:
            with open(LOG_FILE, "r") as f:
                logs = json.load(f)
        except Exception:
            logs = []
    logs.append(entry)
    # Keep last 200 entries
    logs = logs[-200:]
    with open(LOG_FILE, "w") as f:
        json.dump(logs, f, indent=2)


def check_primary_health() -> dict:
    """Ping primary JARVIS instance. Returns status dict."""
    timestamp = datetime.utcnow().isoformat()
    try:
        resp = requests.get(PRIMARY_URL + HEALTH_ENDPOINT, timeout=TIMEOUT)
        status = "UP" if resp.status_code == 200 else "DEGRADED"
        result = {
            "timestamp": timestamp,
            "instance": "primary",
            "url": PRIMARY_URL,
            "status": status,
            "http_code": resp.status_code
        }
    except requests.exceptions.ConnectionError:
        result = {
            "timestamp": timestamp,
            "instance": "primary",
            "url": PRIMARY_URL,
            "status": "DOWN",
            "http_code": None
        }
    except requests.exceptions.Timeout:
        result = {
            "timestamp": timestamp,
            "instance": "primary",
            "url": PRIMARY_URL,
            "status": "UNREACHABLE",
            "http_code": None
        }
    except Exception as e:
        result = {
            "timestamp": timestamp,
            "instance": "primary",
            "url": PRIMARY_URL,
            "status": "ERROR",
            "error": str(e)
        }
    _log(result)
    return result


def check_backup_health() -> dict:
    """Ping backup JARVIS instance. Returns status dict."""
    timestamp = datetime.utcnow().isoformat()
    if not BACKUP_URL:
        return {
            "timestamp": timestamp,
            "instance": "backup",
            "status": "NOT_CONFIGURED",
            "url": None
        }
    try:
        resp = requests.get(BACKUP_URL + HEALTH_ENDPOINT, timeout=TIMEOUT)
        status = "UP" if resp.status_code == 200 else "DEGRADED"
        result = {
            "timestamp": timestamp,
            "instance": "backup",
            "url": BACKUP_URL,
            "status": status,
            "http_code": resp.status_code
        }
    except requests.exceptions.ConnectionError:
        result = {
            "timestamp": timestamp,
            "instance": "backup",
            "url": BACKUP_URL,
            "status": "DOWN",
            "http_code": None
        }
    except Exception as e:
        result = {
            "timestamp": timestamp,
            "instance": "backup",
            "url": BACKUP_URL,
            "status": "ERROR",
            "error": str(e)
        }
    _log(result)
    return result


def failover_status() -> dict:
    """Check both instances and determine if failover is needed."""
    primary = check_primary_health()
    backup = check_backup_health()
    failover_needed = primary["status"] not in ("UP",)
    return {
        "timestamp": datetime.utcnow().isoformat(),
        "primary": primary,
        "backup": backup,
        "failover_needed": failover_needed,
        "recommendation": (
            "✅ All systems nominal — no action needed."
            if not failover_needed
            else "🚨 Primary is DOWN — switch to backup instance immediately!"
            if backup["status"] == "UP"
            else "⚠️ Primary is DOWN and backup is not available — manual intervention required!"
        )
    }


def instance_summary() -> str:
    """Human-readable status report for both instances."""
    status = failover_status()
    p = status["primary"]
    b = status["backup"]
    lines = [
        "🤖 JARVIS Instance Status",
        f"  Primary  → {p['status']} ({p.get('url', 'N/A')})",
        f"  Backup   → {b['status']} ({b.get('url', 'N/A')})",
        f"  Failover Needed: {'YES 🚨' if status['failover_needed'] else 'NO ✅'}",
        f"  {status['recommendation']}"
    ]
    return "\n".join(lines)


if __name__ == "__main__":
    print(instance_summary())
