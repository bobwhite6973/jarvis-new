"""
Extension: github_editor
Allows JARVIS to read and edit files in the jarvis-new repo via GitHub API.

Guardrails:
1. Syntax check — validates Python before any push
2. Branch protection — pushes to 'jarvis-changes' branch only
3. Approval gate — /approve /reject /diff /rollback commands
4. Scope limits — extensions/ folder only by default

Tools registered:
  commit_file(repo, path, content, message) — pushes to jarvis-changes
  propose_change(path, content, reason) — propose with approval gate
  read_file(path) — read file from repo
  list_extensions() — list extensions folder
"""

import os
import ast
import base64
import logging
import requests

log = logging.getLogger("jarvis.ext.github_editor")

GITHUB_API = "https://api.github.com"
DEFAULT_OWNER = "bobwhite6973"
DEFAULT_REPO = "bobwhite6973/jarvis-new"
BRANCH = "jarvis-changes"
ALLOWED_PATHS = ["extensions/"]

_pending = {
    "path": None,
    "content": None,
    "message": None,
    "sha": None,
}


def _headers() -> dict:
    token = os.environ.get("GITHUB_TOKEN", "")
    return {
        "Authorization": f"token {token}",
        "Accept": "application/vnd.github.v3+json",
        "Content-Type": "application/json",
    }


def _full_repo(repo: str) -> str:
    """Ensure repo has owner prefix."""
    if "/" not in repo:
        return f"{DEFAULT_OWNER}/{repo}"
    return repo


def _get_file_sha(repo: str, path: str) -> str | None:
    """Get SHA of existing file for updates."""
    full = _full_repo(repo)
    for branch in [BRANCH, "main"]:
        try:
            resp = requests.get(
                f"{GITHUB_API}/repos/{full}/contents/{path}",
                headers=_headers(),
                params={"ref": branch},
                timeout=10
            )
            if resp.status_code == 200:
                return resp.json().get("sha")
        except Exception:
            pass
    return None


def read_file(path: str) -> dict:
    """Read file contents from jarvis-new repo."""
    full = DEFAULT_REPO
    for branch in [BRANCH, "main"]:
        try:
            resp = requests.get(
                f"{GITHUB_API}/repos/{full}/contents/{path}",
                headers=_headers(),
                params={"ref": branch},
                timeout=10
            )
            if resp.status_code == 200:
                data = resp.json()
                content = base64.b64decode(data["content"]).decode("utf-8")
                return {"content": content, "sha": data["sha"], "branch": branch}
        except Exception as e:
            log.error(f"read_file error: {e}")
    return {"error": f"File not found: {path}"}


def commit_file(repo: str, path: str, content: str, message: str) -> dict:
    """
    Push a file to jarvis-changes branch.
    Syntax-checks Python files before pushing.
    repo can be short name (jarvis-new) or full (bobwhite6973/jarvis-new).
    """
    full_repo = _full_repo(repo)

    # Syntax check Python files
    if path.endswith(".py"):
        try:
            ast.parse(content)
        except SyntaxError as e:
            return {"error": f"Syntax error in {path} line {e.lineno}: {e.msg}"}

    # Get existing SHA if file exists (needed for updates)
    sha = _get_file_sha(full_repo, path)

    payload = {
        "message": f"[JARVIS] {message}",
        "content": base64.b64encode(content.encode()).decode(),
        "branch": BRANCH,
    }
    if sha:
        payload["sha"] = sha

    try:
        url = f"{GITHUB_API}/repos/{full_repo}/contents/{path}"
        log.info(f"commit_file: PUT {url} branch={BRANCH}")
        resp = requests.put(
            url,
            headers=_headers(),
            json=payload,
            timeout=15
        )
        if resp.status_code in (200, 201):
            commit_sha = resp.json().get("commit", {}).get("sha", "")[:7]
            return {
                "ok": True,
                "path": path,
                "repo": full_repo,
                "branch": BRANCH,
                "sha": commit_sha,
                "message": f"Committed to '{BRANCH}' branch. Merge into main on GitHub to deploy."
            }
        log.error(f"commit_file failed: {resp.status_code} {resp.text[:300]}")
        return {"error": f"Push failed {resp.status_code}: {resp.text[:300]}"}
    except Exception as e:
        return {"error": str(e)}


def propose_change(path: str, content: str, reason: str) -> str:
    """Propose a change with approval gate."""
    global _pending

    if not any(path.startswith(p) for p in ALLOWED_PATHS):
        return f"Blocked: '{path}' is outside allowed scope ({', '.join(ALLOWED_PATHS)})"

    if path.endswith(".py"):
        try:
            ast.parse(content)
        except SyntaxError as e:
            return f"Blocked: Syntax error line {e.lineno}: {e.msg}"

    sha_result = read_file(path)
    sha = sha_result.get("sha")

    _pending = {"path": path, "content": content, "message": reason, "sha": sha}

    preview = content[:500] + ("..." if len(content) > 500 else "")
    return (
        f"Change proposed for `{path}`\n"
        f"Reason: {reason}\n\n"
        f"Preview:\n```\n{preview}\n```\n\n"
        f"Send /approve to push | /reject to cancel | /diff to see full content"
    )


def approve_change() -> str:
    global _pending
    if not _pending["path"]:
        return "No pending change to approve."
    result = commit_file(DEFAULT_REPO, _pending["path"], _pending["content"], _pending["message"])
    if result.get("ok"):
        path = _pending["path"]
        _pending = {"path": None, "content": None, "message": None, "sha": None}
        return f"Pushed `{path}` to '{BRANCH}'. Merge into main on GitHub to deploy."
    return f"Push failed: {result.get('error')}"


def reject_change() -> str:
    global _pending
    if not _pending["path"]:
        return "No pending change."
    path = _pending["path"]
    _pending = {"path": None, "content": None, "message": None, "sha": None}
    return f"Change to '{path}' rejected."


def get_diff() -> str:
    if not _pending["path"]:
        return "No pending change."
    return f"Pending: `{_pending['path']}`\n\n```python\n{_pending['content']}\n```"


def rollback() -> str:
    try:
        resp = requests.get(
            f"{GITHUB_API}/repos/{DEFAULT_REPO}/commits",
            headers=_headers(),
            params={"sha": BRANCH, "per_page": 10},
            timeout=10
        )
        if resp.status_code != 200:
            return "Could not fetch commits."
        commits = resp.json()
        jarvis_commits = [c for c in commits if c["commit"]["message"].startswith("[JARVIS]")]
        if not jarvis_commits:
            return "No JARVIS commits found."
        last = jarvis_commits[0]
        return f"Last JARVIS commit: {last['commit']['message']}\nSHA: {last['sha'][:7]}\n\nRevert it on GitHub in the {BRANCH} branch."
    except Exception as e:
        return f"Rollback check failed: {e}"


def list_extensions() -> dict:
    try:
        resp = requests.get(
            f"{GITHUB_API}/repos/{DEFAULT_REPO}/contents/extensions",
            headers=_headers(),
            timeout=10
        )
        if resp.status_code != 200:
            return {"error": "Could not list extensions"}
        files = [f["name"] for f in resp.json() if f["type"] == "file"]
        return {"extensions": files, "count": len(files)}
    except Exception as e:
        return {"error": str(e)}


def handle(query: str) -> str:
    q = query.lower()
    if "list" in q and "extension" in q:
        result = list_extensions()
        if "error" in result:
            return f"Error: {result['error']}"
        return "Extensions:\n" + "\n".join(f"  {f}" for f in result["extensions"])
    if "read" in q:
        import re
        match = re.search(r"read\s+([\w/\.\-]+)", q)
        if match:
            result = read_file(match.group(1))
            return result.get("content", result.get("error", "Not found"))[:2000]
    return "GitHub editor ready. Tools: commit_file, propose_change, read_file, list_extensions."


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
    log.info("github_editor extension loaded — commit_file ready (sync)")
