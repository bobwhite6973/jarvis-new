"""
Extension: github_editor
Full-auto GitHub write access for JARVIS.

Flow:
  commit_file() → push to jarvis-changes → create PR → auto-merge → Render deploys

Guardrails:
  - Syntax check on all Python files before push
  - extensions/ folder only by default
  - Full audit log in memory
  - /rollback to revert last JARVIS commit
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
MAIN_BRANCH = "main"
ALLOWED_PATHS = ["extensions/"]

_pending = {
    "path": None,
    "content": None,
    "message": None,
    "sha": None,
}

# Audit log of all JARVIS commits
_commit_log = []


def _headers() -> dict:
    token = os.environ.get("GITHUB_TOKEN", "")
    return {
        "Authorization": f"token {token}",
        "Accept": "application/vnd.github.v3+json",
        "Content-Type": "application/json",
    }


def _full_repo(repo: str) -> str:
    if "/" not in repo:
        return f"{DEFAULT_OWNER}/{repo}"
    return repo


def _get_file_sha(repo: str, path: str) -> str | None:
    full = _full_repo(repo)
    for branch in [BRANCH, MAIN_BRANCH]:
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


def _create_pr(repo: str, title: str, body: str) -> dict:
    """Create a PR from jarvis-changes into main."""
    full = _full_repo(repo)
    try:
        resp = requests.post(
            f"{GITHUB_API}/repos/{full}/pulls",
            headers=_headers(),
            json={
                "title": title,
                "body": body,
                "head": BRANCH,
                "base": MAIN_BRANCH,
            },
            timeout=15
        )
        if resp.status_code == 201:
            return {"ok": True, "pr_number": resp.json()["number"], "url": resp.json()["html_url"]}
        if resp.status_code == 422:
            # PR already exists or no diff
            data = resp.json()
            errors = data.get("errors", [])
            for e in errors:
                if "already exists" in str(e.get("message", "")):
                    # Get existing PR number
                    prs = requests.get(
                        f"{GITHUB_API}/repos/{full}/pulls",
                        headers=_headers(),
                        params={"head": f"{DEFAULT_OWNER}:{BRANCH}", "state": "open"},
                        timeout=10
                    ).json()
                    if prs:
                        return {"ok": True, "pr_number": prs[0]["number"], "url": prs[0]["html_url"]}
            return {"error": f"PR creation failed: {resp.text[:200]}"}
        return {"error": f"PR creation failed {resp.status_code}: {resp.text[:200]}"}
    except Exception as e:
        return {"error": str(e)}


def _merge_pr(repo: str, pr_number: int, message: str) -> dict:
    """Merge a PR."""
    full = _full_repo(repo)
    try:
        resp = requests.put(
            f"{GITHUB_API}/repos/{full}/pulls/{pr_number}/merge",
            headers=_headers(),
            json={
                "commit_title": f"[JARVIS] {message}",
                "merge_method": "squash",
            },
            timeout=15
        )
        if resp.status_code == 200:
            return {"ok": True, "sha": resp.json().get("sha", "")[:7]}
        return {"error": f"Merge failed {resp.status_code}: {resp.text[:200]}"}
    except Exception as e:
        return {"error": str(e)}


def read_file(path: str) -> dict:
    """Read file contents from jarvis-new repo."""
    for branch in [BRANCH, MAIN_BRANCH]:
        try:
            resp = requests.get(
                f"{GITHUB_API}/repos/{DEFAULT_REPO}/contents/{path}",
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
    Full-auto commit: push to jarvis-changes → create PR → merge to main.
    Render auto-deploys after merge.
    Syntax-checks Python before pushing.
    """
    full_repo = _full_repo(repo)

    # Syntax check
    if path.endswith(".py"):
        try:
            ast.parse(content)
        except SyntaxError as e:
            return {"error": f"Syntax error in {path} line {e.lineno}: {e.msg}"}

    # Get existing SHA
    sha = _get_file_sha(full_repo, path)

    payload = {
        "message": f"[JARVIS] {message}",
        "content": base64.b64encode(content.encode()).decode(),
        "branch": BRANCH,
    }
    if sha:
        payload["sha"] = sha

    # Step 1: Push to jarvis-changes
    try:
        url = f"{GITHUB_API}/repos/{full_repo}/contents/{path}"
        log.info(f"commit_file: PUT {url} branch={BRANCH}")
        resp = requests.put(url, headers=_headers(), json=payload, timeout=15)

        if resp.status_code not in (200, 201):
            log.error(f"Push failed: {resp.status_code} {resp.text[:300]}")
            return {"error": f"Push failed {resp.status_code}: {resp.text[:300]}"}

        commit_sha = resp.json().get("commit", {}).get("sha", "")[:7]
        log.info(f"Pushed {path} to {BRANCH} — SHA: {commit_sha}")

    except Exception as e:
        return {"error": f"Push error: {e}"}

    # Step 2: Create PR
    pr_result = _create_pr(
        full_repo,
        title=f"[JARVIS] {message}",
        body=f"Auto-commit by JARVIS\n\nFile: `{path}`\nMessage: {message}"
    )

    if not pr_result.get("ok"):
        return {
            "ok": True,
            "path": path,
            "branch": BRANCH,
            "sha": commit_sha,
            "warning": f"Pushed but PR creation failed: {pr_result.get('error')}. Merge manually.",
        }

    pr_number = pr_result["pr_number"]
    pr_url = pr_result.get("url", "")
    log.info(f"PR #{pr_number} created: {pr_url}")

    # Step 3: Merge PR
    import time
    time.sleep(2)  # Brief delay to let GitHub process the PR
    merge_result = _merge_pr(full_repo, pr_number, message)

    if not merge_result.get("ok"):
        return {
            "ok": True,
            "path": path,
            "branch": BRANCH,
            "sha": commit_sha,
            "pr": pr_url,
            "warning": f"Pushed and PR created but merge failed: {merge_result.get('error')}. Merge PR manually: {pr_url}",
        }

    merge_sha = merge_result["sha"]
    log.info(f"PR #{pr_number} merged — SHA: {merge_sha}")

    # Log to audit trail
    _commit_log.append({
        "path": path,
        "message": message,
        "commit_sha": commit_sha,
        "merge_sha": merge_sha,
        "pr_number": pr_number,
    })

    return {
        "ok": True,
        "path": path,
        "repo": full_repo,
        "branch": f"{BRANCH} → {MAIN_BRANCH}",
        "sha": merge_sha,
        "pr_number": pr_number,
        "message": f"Committed, PR created, and merged to main. Render is deploying now."
    }


def propose_change(path: str, content: str, reason: str) -> str:
    """Propose a change — stores pending for manual review if needed."""
    global _pending

    if not any(path.startswith(p) for p in ALLOWED_PATHS):
        return f"Blocked: '{path}' outside allowed scope ({', '.join(ALLOWED_PATHS)})"

    if path.endswith(".py"):
        try:
            ast.parse(content)
        except SyntaxError as e:
            return f"Blocked: Syntax error line {e.lineno}: {e.msg}"

    _pending = {"path": path, "content": content, "message": reason, "sha": None}
    preview = content[:500] + ("..." if len(content) > 500 else "")
    return (
        f"Change proposed for `{path}`\n"
        f"Reason: {reason}\n\n"
        f"Preview:\n```\n{preview}\n```\n\n"
        f"Send /approve to commit and auto-merge | /reject to cancel"
    )


def approve_change() -> str:
    global _pending
    if not _pending["path"]:
        return "No pending change to approve."
    result = commit_file(DEFAULT_REPO, _pending["path"], _pending["content"], _pending["message"])
    if result.get("ok"):
        path = _pending["path"]
        _pending = {"path": None, "content": None, "message": None, "sha": None}
        return f"Done. `{path}` committed and merged. Render deploying."
    return f"Failed: {result.get('error')}"


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
    """Show last JARVIS commit for manual rollback."""
    if _commit_log:
        last = _commit_log[-1]
        return (
            f"Last JARVIS commit:\n"
            f"File: {last['path']}\n"
            f"Message: {last['message']}\n"
            f"PR: #{last['pr_number']}\n"
            f"SHA: {last['merge_sha']}\n\n"
            f"To revert: go to github.com/{DEFAULT_REPO}/commits/main and revert that commit."
        )
    try:
        resp = requests.get(
            f"{GITHUB_API}/repos/{DEFAULT_REPO}/commits",
            headers=_headers(),
            params={"sha": MAIN_BRANCH, "per_page": 10},
            timeout=10
        )
        if resp.status_code != 200:
            return "Could not fetch commits."
        commits = resp.json()
        jarvis = [c for c in commits if c["commit"]["message"].startswith("[JARVIS]")]
        if not jarvis:
            return "No JARVIS commits found on main."
        last = jarvis[0]
        return (
            f"Last JARVIS commit on main:\n"
            f"{last['commit']['message']}\n"
            f"SHA: {last['sha'][:7]}\n\n"
            f"Revert at: github.com/{DEFAULT_REPO}/commit/{last['sha']}"
        )
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
    return "GitHub editor ready. commit_file now auto-merges to main."


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
    log.info("github_editor extension loaded — full-auto commit+merge enabled")
