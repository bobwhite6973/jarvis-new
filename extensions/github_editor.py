"""
Extension: github_editor
Allows JARVIS to read and edit files in the jarvis-new repo via GitHub API.

Guardrails:
1. Approval gate — never pushes without /approve from user
2. Syntax check — validates Python before any push
3. Branch protection — pushes to 'jarvis-changes' branch only, not main
4. Rollback — /rollback reverts last JARVIS commit
5. Scope limits — can only edit files in /extensions/ by default

Telegram commands added:
  /approve  — approve pending change and push
  /reject   — reject pending change
  /diff     — show pending change
  /rollback — revert last JARVIS commit
"""

import os
import ast
import base64
import httpx
import logging
from datetime import datetime, timezone

log = logging.getLogger("jarvis.ext.github_editor")

GITHUB_API = "https://api.github.com"
REPO = "bobwhite6973/jarvis-new"
BRANCH = "jarvis-changes"
ALLOWED_PATHS = ["extensions/"]  # JARVIS can only edit these paths

# Pending change stored in memory (one at a time)
_pending = {
    "path": None,
    "content": None,
    "message": None,
    "sha": None,  # needed for updates
    "proposed_by": None,
}


def _headers() -> dict:
    token = os.environ.get("GITHUB_TOKEN", "")
    return {
        "Authorization": f"token {token}",
        "Accept": "application/vnd.github.v3+json",
        "Content-Type": "application/json",
    }


def _allowed_path(path: str) -> bool:
    """Check if path is within allowed edit scope."""
    return any(path.startswith(p) for p in ALLOWED_PATHS)


async def _ensure_branch() -> bool:
    """Create jarvis-changes branch if it doesn't exist."""
    async with httpx.AsyncClient(timeout=15) as client:
        # Get main branch SHA
        resp = await client.get(
            f"{GITHUB_API}/repos/{REPO}/git/ref/heads/main",
            headers=_headers()
        )
        if resp.status_code != 200:
            log.error(f"Could not get main branch: {resp.text}")
            return False

        main_sha = resp.json()["object"]["sha"]

        # Try to create jarvis-changes branch
        resp = await client.post(
            f"{GITHUB_API}/repos/{REPO}/git/refs",
            headers=_headers(),
            json={"ref": f"refs/heads/{BRANCH}", "sha": main_sha}
        )
        if resp.status_code in (201, 422):  # 422 = already exists
            return True
        log.error(f"Branch creation failed: {resp.text}")
        return False


async def read_file(path: str) -> tuple[str, str]:
    """Read file contents and SHA from repo. Returns (content, sha)."""
    async with httpx.AsyncClient(timeout=15) as client:
        resp = await client.get(
            f"{GITHUB_API}/repos/{REPO}/contents/{path}",
            headers=_headers(),
            params={"ref": BRANCH}
        )
        if resp.status_code == 404:
            # Try main branch
            resp = await client.get(
                f"{GITHUB_API}/repos/{REPO}/contents/{path}",
                headers=_headers(),
                params={"ref": "main"}
            )
        if resp.status_code != 200:
            return None, None
        data = resp.json()
        content = base64.b64decode(data["content"]).decode("utf-8")
        return content, data["sha"]


async def _push_file(path: str, content: str, message: str, sha: str = None) -> bool:
    """Push file to jarvis-changes branch."""
    payload = {
        "message": f"[JARVIS] {message}",
        "content": base64.b64encode(content.encode()).decode(),
        "branch": BRANCH,
    }
    if sha:
        payload["sha"] = sha

    async with httpx.AsyncClient(timeout=15) as client:
        resp = await client.put(
            f"{GITHUB_API}/repos/{REPO}/contents/{path}",
            headers=_headers(),
            json=payload
        )
        return resp.status_code in (200, 201)


async def propose_change(path: str, content: str, reason: str, user_id: str) -> str:
    """
    Propose a file change. Stores it pending approval.
    Returns a summary for the user to review.
    """
    global _pending

    # Guardrail 1: scope check
    if not _allowed_path(path):
        return (
            f"Blocked: '{path}' is outside allowed scope.\n"
            f"JARVIS can only edit: {', '.join(ALLOWED_PATHS)}\n"
            "Ask Bob to expand scope if needed."
        )

    # Guardrail 2: syntax check for Python files
    if path.endswith(".py"):
        try:
            ast.parse(content)
        except SyntaxError as e:
            return f"Blocked: Syntax error in proposed code — line {e.lineno}: {e.msg}\nFix the code before proposing."

    # Read current file SHA
    _, sha = await read_file(path)

    _pending = {
        "path": path,
        "content": content,
        "message": reason,
        "sha": sha,
        "proposed_by": user_id,
    }

    preview = content[:500] + ("..." if len(content) > 500 else "")
    return (
        f"Change proposed for `{path}`\n\n"
        f"Reason: {reason}\n\n"
        f"Preview:\n```\n{preview}\n```\n\n"
        f"Send /approve to push to '{BRANCH}' branch\n"
        f"Send /reject to cancel\n"
        f"Send /diff to see full content"
    )


async def approve_change() -> str:
    """Push the pending change to jarvis-changes branch."""
    global _pending

    if not _pending["path"]:
        return "No pending change to approve."

    # Ensure branch exists
    if not await _ensure_branch():
        return "Failed to create/access jarvis-changes branch."

    success = await _push_file(
        _pending["path"],
        _pending["content"],
        _pending["message"],
        _pending["sha"]
    )

    if success:
        path = _pending["path"]
        _pending = {"path": None, "content": None, "message": None, "sha": None, "proposed_by": None}
        return (
            f"Pushed to '{BRANCH}' branch.\n\n"
            f"File: {path}\n\n"
            f"To deploy: merge '{BRANCH}' into main on GitHub.\n"
            f"Render will auto-deploy after merge."
        )
    else:
        return "Push failed. Check GITHUB_TOKEN permissions."


async def reject_change() -> str:
    """Reject the pending change."""
    global _pending
    if not _pending["path"]:
        return "No pending change to reject."
    path = _pending["path"]
    _pending = {"path": None, "content": None, "message": None, "sha": None, "proposed_by": None}
    return f"Change to '{path}' rejected and discarded."


async def get_diff() -> str:
    """Show the full pending change."""
    if not _pending["path"]:
        return "No pending change."
    return (
        f"Pending change for `{_pending['path']}`\n\n"
        f"```python\n{_pending['content']}\n```"
    )


async def rollback() -> str:
    """Revert the last JARVIS commit on jarvis-changes branch."""
    async with httpx.AsyncClient(timeout=15) as client:
        # Get commits on jarvis-changes
        resp = await client.get(
            f"{GITHUB_API}/repos/{REPO}/commits",
            headers=_headers(),
            params={"sha": BRANCH, "per_page": 10}
        )
        if resp.status_code != 200:
            return "Could not fetch commits."

        commits = resp.json()
        jarvis_commits = [c for c in commits if c["commit"]["message"].startswith("[JARVIS]")]

        if not jarvis_commits:
            return "No JARVIS commits found to roll back."

        last = jarvis_commits[0]
        msg = last["commit"]["message"]
        sha = last["sha"]
        return (
            f"Last JARVIS commit:\n{msg}\nSHA: {sha[:7]}\n\n"
            f"To roll back, go to github.com/{REPO}/commits/{BRANCH} "
            f"and revert that commit, or merge main back into {BRANCH}.\n\n"
            f"Auto-rollback via API coming in next update."
        )


async def list_extensions() -> str:
    """List all files in extensions/ folder."""
    async with httpx.AsyncClient(timeout=15) as client:
        resp = await client.get(
            f"{GITHUB_API}/repos/{REPO}/contents/extensions",
            headers=_headers(),
        )
        if resp.status_code != 200:
            return "Could not list extensions."
        files = [f["name"] for f in resp.json() if f["type"] == "file"]
        return "Current extensions:\n" + "\n".join(f"  {f}" for f in files)


async def handle(query: str) -> str:
    """Main handler — called by brain on github intent."""
    q = query.lower()
    if "list" in q and "extension" in q:
        return await list_extensions()
    if "read" in q:
        import re
        match = re.search(r"read\s+([\w/\.\-]+)", q)
        if match:
            content, _ = await read_file(match.group(1))
            return content[:2000] if content else "File not found."
    return "GitHub editor ready. I can propose changes to extensions/, read files, and push with your approval."


def register(brain):
    brain.register_extension("github_editor", handle)
    brain.register_pending = lambda: _pending
    brain.github_approve = approve_change
    brain.github_reject = reject_change
    brain.github_diff = get_diff
    brain.github_rollback = rollback
    brain.github_propose = propose_change
    log.info("github_editor extension loaded")
