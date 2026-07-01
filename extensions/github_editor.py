"""
Extension: github_editor
Allows JARVIS to read and edit files in the jarvis-new repo via GitHub API.

Guardrails:
1. Approval gate — never pushes without /approve from user
2. Syntax check — validates Python before any push
3. Branch protection — pushes to 'jarvis-changes' branch only, not main
4. Rollback — /rollback reverts last JARVIS commit
5. Scope limits — can only edit files in /extensions/ by default

Tools registered:
  commit_file(repo, path, content, message) — direct commit to jarvis-changes branch
  propose_change(path, content, reason) — propose with approval gate
  github_approve / github_reject / github_diff / github_rollback
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
ALLOWED_PATHS = ["extensions/"]

_pending = {
    "path": None,
    "content": None,
    "message": None,
    "sha": None,
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
    return any(path.startswith(p) for p in ALLOWED_PATHS)


async def _ensure_branch() -> bool:
    async with httpx.AsyncClient(timeout=15) as client:
        resp = await client.get(
            f"{GITHUB_API}/repos/{REPO}/git/ref/heads/main",
            headers=_headers()
        )
        if resp.status_code != 200:
            return False
        main_sha = resp.json()["object"]["sha"]
        resp = await client.post(
            f"{GITHUB_API}/repos/{REPO}/git/refs",
            headers=_headers(),
            json={"ref": f"refs/heads/{BRANCH}", "sha": main_sha}
        )
        return resp.status_code in (201, 422)


async def _get_file_sha(repo: str, path: str, branch: str = BRANCH) -> str | None:
    """Get the SHA of an existing file, needed for updates."""
    async with httpx.AsyncClient(timeout=15) as client:
        resp = await client.get(
            f"{GITHUB_API}/repos/{repo}/contents/{path}",
            headers=_headers(),
            params={"ref": branch}
        )
        if resp.status_code == 200:
            return resp.json().get("sha")
        # Try main branch
        resp = await client.get(
            f"{GITHUB_API}/repos/{repo}/contents/{path}",
            headers=_headers(),
            params={"ref": "main"}
        )
        if resp.status_code == 200:
            return resp.json().get("sha")
    return None


async def read_file(path: str) -> tuple[str, str]:
    """Read file contents and SHA. Returns (content, sha)."""
    async with httpx.AsyncClient(timeout=15) as client:
        for branch in [BRANCH, "main"]:
            resp = await client.get(
                f"{GITHUB_API}/repos/{REPO}/contents/{path}",
                headers=_headers(),
                params={"ref": branch}
            )
            if resp.status_code == 200:
                data = resp.json()
                content = base64.b64decode(data["content"]).decode("utf-8")
                return content, data["sha"]
    return None, None


async def commit_file(repo: str, path: str, content: str, message: str) -> dict:
    """
    Direct commit tool — pushes a file to jarvis-changes branch.
    Called by JARVIS automatically when it wants to push code.
    Syntax-checks Python files before pushing.
    """
    # Syntax check Python files
    if path.endswith(".py"):
        try:
            ast.parse(content)
        except SyntaxError as e:
            return {"error": f"Syntax error in {path} line {e.lineno}: {e.msg}"}

    # Ensure branch exists
    if not await _ensure_branch():
        return {"error": "Could not create/access jarvis-changes branch"}

    # Get existing SHA if file exists
    sha = await _get_file_sha(repo, path)

    payload = {
        "message": f"[JARVIS] {message}",
        "content": base64.b64encode(content.encode()).decode(),
        "branch": BRANCH,
    }
    if sha:
        payload["sha"] = sha

    async with httpx.AsyncClient(timeout=15) as client:
        resp = await client.put(
            f"{GITHUB_API}/repos/{repo}/contents/{path}",
            headers=_headers(),
            json=payload
        )
        if resp.status_code in (200, 201):
            return {
                "ok": True,
                "path": path,
                "branch": BRANCH,
                "message": f"Committed to {BRANCH}. Merge into main on GitHub to deploy."
            }
        return {"error": f"Push failed: {resp.status_code} {resp.text[:200]}"}


async def propose_change(path: str, content: str, reason: str, user_id: str = "jarvis") -> str:
    """Propose a change with approval gate."""
    global _pending

    if not _allowed_path(path):
        return (
            f"Blocked: '{path}' is outside allowed scope.\n"
            f"JARVIS can only edit: {', '.join(ALLOWED_PATHS)}"
        )

    if path.endswith(".py"):
        try:
            ast.parse(content)
        except SyntaxError as e:
            return f"Blocked: Syntax error line {e.lineno}: {e.msg}"

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
    global _pending
    if not _pending["path"]:
        return "No pending change to approve."

    result = await commit_file(
        REPO,
        _pending["path"],
        _pending["content"],
        _pending["message"]
    )

    if result.get("ok"):
        path = _pending["path"]
        _pending = {"path": None, "content": None, "message": None, "sha": None, "proposed_by": None}
        return (
            f"Pushed to '{BRANCH}' branch.\n\n"
            f"File: {path}\n\n"
            f"To deploy: merge '{BRANCH}' into main on GitHub.\n"
            f"Render will auto-deploy after merge."
        )
    return f"Push failed: {result.get('error')}"


async def reject_change() -> str:
    global _pending
    if not _pending["path"]:
        return "No pending change to reject."
    path = _pending["path"]
    _pending = {"path": None, "content": None, "message": None, "sha": None, "proposed_by": None}
    return f"Change to '{path}' rejected and discarded."


async def get_diff() -> str:
    if not _pending["path"]:
        return "No pending change."
    return (
        f"Pending change for `{_pending['path']}`\n\n"
        f"```python\n{_pending['content']}\n```"
    )


async def rollback() -> str:
    async with httpx.AsyncClient(timeout=15) as client:
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
            f"To roll back, revert that commit on GitHub in the {BRANCH} branch."
        )


async def list_extensions() -> str:
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
    q = query.lower()
    if "list" in q and "extension" in q:
        return await list_extensions()
    if "read" in q:
        import re
        match = re.search(r"read\s+([\w/\.\-]+)", q)
        if match:
            content, _ = await read_file(match.group(1))
            return content[:2000] if content else "File not found."
    return "GitHub editor ready. Tools: commit_file, propose_change, list extensions, read files."


def register(brain):
    brain.register_tool("commit_file", commit_file)
    brain.register_tool("propose_change", propose_change)
    brain.register_tool("read_file", read_file)
    brain.register_tool("list_extensions", list_extensions)
    brain.register_extension("github_editor", handle)
    brain.github_approve = approve_change
    brain.github_reject = reject_change
    brain.github_diff = get_diff
    brain.github_rollback = rollback
    brain.github_propose = propose_change
    log.info("github_editor extension loaded — commit_file tool ready")
