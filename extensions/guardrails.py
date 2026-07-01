"""
JARVIS Guardrail System
=======================
Auto-rollback, syntax checking, and safety gates before any self-edit is applied.
Phase 1 — Step 5
"""

import os
import ast
import shutil
import hashlib
import datetime
import traceback
from pathlib import Path

BACKUP_DIR = Path("extensions/.guardrail_backups")
LOG_FILE = Path("extensions/guardrail_log.txt")
MAX_BACKUPS = 20


# ─────────────────────────────────────────────
# 1. Logging
# ─────────────────────────────────────────────

def _log(message: str):
    timestamp = datetime.datetime.utcnow().strftime("%Y-%m-%d %Human:%M:%S UTC")
    entry = f"[{timestamp}] {message}\n"
    try:
        LOG_FILE.parent.mkdir(parents=True, exist_ok=True)
        with open(LOG_FILE, "a") as f:
            f.write(entry)
    except Exception:
        pass
    print(entry.strip())


# ─────────────────────────────────────────────
# 2. Syntax Check
# ─────────────────────────────────────────────

def syntax_check(code: str, filename: str = "<unknown>") -> dict:
    """
    Parse Python source for syntax errors before writing.
    Returns: {"ok": bool, "error": str or None}
    """
    try:
        ast.parse(code)
        _log(f"SYNTAX OK: {filename}")
        return {"ok": True, "error": None}
    except SyntaxError as e:
        msg = f"SyntaxError in {filename} at line {e.lineno}: {e.msg}"
        _log(f"SYNTAX FAIL: {msg}")
        return {"ok": False, "error": msg}


# ─────────────────────────────────────────────
# 3. Backup
# ─────────────────────────────────────────────

def backup_file(filepath: str) -> dict:
    """
    Create a timestamped backup of a file before editing.
    Returns: {"ok": bool, "backup_path": str or None, "error": str or None}
    """
    src = Path(filepath)
    if not src.exists():
        _log(f"BACKUP SKIP: {filepath} does not exist yet (new file)")
        return {"ok": True, "backup_path": None, "error": None}

    try:
        BACKUP_DIR.mkdir(parents=True, exist_ok=True)
        ts = datetime.datetime.utcnow().strftime("%Y%m%d_%H%M%S")
        backup_name = f"{src.stem}__{ts}{src.suffix}"
        backup_path = BACKUP_DIR / backup_name
        shutil.copy2(src, backup_path)
        _log(f"BACKUP OK: {filepath} → {backup_path}")
        _prune_backups()
        return {"ok": True, "backup_path": str(backup_path), "error": None}
    except Exception as e:
        msg = f"Backup failed for {filepath}: {e}"
        _log(f"BACKUP FAIL: {msg}")
        return {"ok": False, "backup_path": None, "error": msg}


def _prune_backups():
    """Keep only the last MAX_BACKUPS backups."""
    try:
        files = sorted(BACKUP_DIR.glob("*"), key=lambda f: f.stat().st_mtime)
        while len(files) > MAX_BACKUPS:
            files.pop(0).unlink()
    except Exception:
        pass


# ─────────────────────────────────────────────
# 4. Rollback
# ─────────────────────────────────────────────

def rollback_file(filepath: str) -> dict:
    """
    Restore the most recent backup of a file.
    Returns: {"ok": bool, "restored_from": str or None, "error": str or None}
    """
    src = Path(filepath)
    try:
        BACKUP_DIR.mkdir(parents=True, exist_ok=True)
        candidates = sorted(
            BACKUP_DIR.glob(f"{src.stem}__*{src.suffix}"),
            key=lambda f: f.stat().st_mtime,
            reverse=True
        )
        if not candidates:
            msg = f"No backup found for {filepath}"
            _log(f"ROLLBACK FAIL: {msg}")
            return {"ok": False, "restored_from": None, "error": msg}

        latest = candidates[0]
        shutil.copy2(latest, src)
        _log(f"ROLLBACK OK: {filepath} ← {latest}")
        return {"ok": True, "restored_from": str(latest), "error": None}
    except Exception as e:
        msg = f"Rollback failed for {filepath}: {traceback.format_exc()}"
        _log(f"ROLLBACK FAIL: {msg}")
        return {"ok": False, "restored_from": None, "error": msg}


# ─────────────────────────────────────────────
# 5. Safe Write Gate
# ─────────────────────────────────────────────

def safe_write(filepath: str, code: str) -> dict:
    """
    Full guardrail pipeline:
      1. Syntax check
      2. Backup existing file
      3. Write new file
      4. Auto-rollback if write fails

    Returns: {"ok": bool, "stage": str, "error": str or None}
    """
    # Stage 1: Syntax
    check = syntax_check(code, filepath)
    if not check["ok"]:
        return {"ok": False, "stage": "syntax_check", "error": check["error"]}

    # Stage 2: Backup
    bak = backup_file(filepath)
    if not bak["ok"]:
        return {"ok": False, "stage": "backup", "error": bak["error"]}

    # Stage 3: Write
    try:
        path = Path(filepath)
        path.parent.mkdir(parents=True, exist_ok=True)
        with open(path, "w") as f:
            f.write(code)
        _log(f"WRITE OK: {filepath}")
        return {"ok": True, "stage": "write", "error": None}
    except Exception as e:
        _log(f"WRITE FAIL: {filepath} — triggering rollback")
        rollback_file(filepath)
        return {"ok": False, "stage": "write", "error": str(e)}


# ─────────────────────────────────────────────
# 6. Checksum Verification
# ─────────────────────────────────────────────

def file_checksum(filepath: str) -> str:
    """Return SHA256 hash of a file for integrity checks."""
    try:
        with open(filepath, "rb") as f:
            return hashlib.sha256(f.read()).hexdigest()
    except Exception:
        return "ERROR"


# ─────────────────────────────────────────────
# 7. Status Report
# ─────────────────────────────────────────────

def guardrail_status() -> dict:
    """Return current guardrail system status."""
    backups = list(BACKUP_DIR.glob("*")) if BACKUP_DIR.exists() else []
    last_log_lines = []
    if LOG_FILE.exists():
        with open(LOG_FILE) as f:
            last_log_lines = f.readlines()[-10:]

    return {
        "backup_count": len(backups),
        "backup_dir": str(BACKUP_DIR),
        "log_file": str(LOG_FILE),
        "last_10_log_entries": [l.strip() for l in last_log_lines],
        "max_backups": MAX_BACKUPS,
        "status": "ACTIVE"
    }


# ─────────────────────────────────────────────
# Quick test
# ─────────────────────────────────────────────
if __name__ == "__main__":
    print("=== JARVIS Guardrail Self-Test ===")

    # Test syntax check (good code)
    result = syntax_check("x = 1 + 1", "test_good.py")
    print("Good code:", result)

    # Test syntax check (bad code)
    result = syntax_check("def broken(:\n    pass", "test_bad.py")
    print("Bad code:", result)

    # Status
    print("Status:", guardrail_status())
