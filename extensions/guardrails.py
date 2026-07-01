"""
JARVIS Guardrail System
Protects against bad code edits with syntax checks, backups, and auto-rollback.
"""

import ast
import os
import shutil
import hashlib
import datetime
import json

BACKUP_DIR = "/tmp/jarvis_backups"
LOG_FILE = "/tmp/jarvis_guardrail_log.json"

os.makedirs(BACKUP_DIR, exist_ok=True)


def syntax_check(code: str) -> dict:
    """Check Python code for syntax errors before writing."""
    try:
        ast.parse(code)
        return {"ok": True, "error": None}
    except SyntaxError as e:
        return {"ok": False, "error": str(e)}


def backup_file(filepath: str) -> dict:
    """Backup a file before editing it."""
    if not os.path.exists(filepath):
        return {"ok": False, "error": f"File not found: {filepath}"}

    timestamp = datetime.datetime.utcnow().strftime("%Y%m%d_%H%M%S")
    filename = os.path.basename(filepath)
    backup_path = os.path.join(BACKUP_DIR, f"{filename}.{timestamp}.bak")

    shutil.copy2(filepath, backup_path)
    _log_event("backup", filepath, backup_path)

    return {"ok": True, "backup_path": backup_path, "timestamp": timestamp}


def rollback_file(filepath: str) -> dict:
    """Restore the most recent backup of a file."""
    filename = os.path.basename(filepath)
    backups = sorted([
        f for f in os.listdir(BACKUP_DIR)
        if f.startswith(filename) and f.endswith(".bak")
    ], reverse=True)

    if not backups:
        return {"ok": False, "error": f"No backups found for {filename}"}

    latest_backup = os.path.join(BACKUP_DIR, backups[0])
    shutil.copy2(latest_backup, filepath)
    _log_event("rollback", filepath, latest_backup)

    return {"ok": True, "restored_from": latest_backup}


def safe_write(filepath: str, code: str) -> dict:
    """Full safe pipeline: syntax check → backup → write → rollback if fail."""
    # Step 1: Syntax check
    check = syntax_check(code)
    if not check["ok"]:
        return {"ok": False, "stage": "syntax_check", "error": check["error"]}

    # Step 2: Backup existing file
    if os.path.exists(filepath):
        backup = backup_file(filepath)
        if not backup["ok"]:
            return {"ok": False, "stage": "backup", "error": backup["error"]}
        backup_path = backup["backup_path"]
    else:
        backup_path = None

    # Step 3: Write new file
    try:
        with open(filepath, "w") as f:
            f.write(code)
        _log_event("write", filepath, "success")
        return {"ok": True, "written": filepath, "backup": backup_path}
    except Exception as e:
        # Step 4: Auto-rollback on failure
        if backup_path:
            rollback_file(filepath)
            return {"ok": False, "stage": "write", "error": str(e), "rolled_back": True}
        return {"ok": False, "stage": "write", "error": str(e), "rolled_back": False}


def file_checksum(filepath: str) -> dict:
    """Return SHA256 checksum of a file."""
    if not os.path.exists(filepath):
        return {"ok": False, "error": f"File not found: {filepath}"}

    sha256 = hashlib.sha256()
    with open(filepath, "rb") as f:
        for chunk in iter(lambda: f.read(4096), b""):
            sha256.update(chunk)

    return {"ok": True, "filepath": filepath, "sha256": sha256.hexdigest()}


def guardrail_status() -> dict:
    """Return current guardrail system status."""
    backups = os.listdir(BACKUP_DIR) if os.path.exists(BACKUP_DIR) else []
    logs = []
    if os.path.exists(LOG_FILE):
        with open(LOG_FILE, "r") as f:
            logs = json.load(f)

    return {
        "backup_count": len(backups),
        "backup_dir": BACKUP_DIR,
        "recent_logs": logs[-5:] if logs else [],
        "status": "active"
    }


def _log_event(event_type: str, filepath: str, detail: str):
    """Internal: log guardrail events."""
    logs = []
    if os.path.exists(LOG_FILE):
        with open(LOG_FILE, "r") as f:
            try:
                logs = json.load(f)
            except Exception:
                logs = []

    logs.append({
        "type": event_type,
        "file": filepath,
        "detail": detail,
        "timestamp": datetime.datetime.utcnow().isoformat()
    })

    with open(LOG_FILE, "w") as f:
        json.dump(logs[-100:], f, indent=2)


if __name__ == "__main__":
    print(json.dumps(guardrail_status(), indent=2))
