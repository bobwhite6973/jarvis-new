"""
Extension: delete_file_tool
Adds a dedicated delete_file tool: push a delete commit to jarvis-changes,
open a PR, and auto-merge to main (mirrors commit_file's flow in github_editor.py).
"""
import os
import time
import logging
import requests

log = logging.getLogger("jarvis.ext.delete_file_tool")

GITHUB_API = "https://api.github.com"
DEFAULT_OWNER = "bobwhite6973"
DEFAULT_REPO = "bobwhite6973/jarvis-new"
BRANCH = "jarvis-changes"
MAIN_BRANCH = "main"
ALLOWED_PATHS = ["extensions/"]


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


def _get_file_sha(repo: str, path: str, branch: str):
    try:
        resp = requests.get(
            f"{GITHUB_API}/repos/{repo}/contents/{path}",
            headers=_headers(),
            params={"ref": branch},
            timeout=10,
        )
        if resp.status_code == 200:
            return resp.json().get("sha")
    except Exception as e:
        log.error(f"_get_file_sha error: {e}")
    return None


def _create_pr(repo: str, title: str, body: str) -> dict:
    try:
        resp = requests.post(
            f"{GITHUB_API}/repos/{repo}/pulls",
            headers=_headers(),
            json={"title": title, "body": body, "head": BRANCH, "base": MAIN_BRANCH},
            timeout=15,
        )
        if resp.status_code == 201:
            return {"ok": True, "pr_number": resp.json()["number"], "url": resp.json()["html_url"]}
        if resp.status_code == 422:
            prs = requests.get(
                f"{GITHUB_API}/repos/{repo}/pulls",
                headers=_headers(),
                params={"head": f"{DEFAULT_OWNER}:{BRANCH}", "state": "open"},
                timeout=10,
            ).json()
            if prs:
                return {"ok": True, "pr_number": prs[0]["number"], "url": prs[0]["html_url"]}
        return {"error": f"PR creation failed {resp.status_code}: {resp.text[:200]}"}
    except Exception as e:
        return {"error": str(e)}


def _merge_pr(repo: str, pr_number: int, message: str) -> dict:
    try:
        resp = requests.put(
            f"{GITHUB_API}/repos/{repo}/pulls/{pr_number}/merge",
            headers=_headers(),
            json={"commit_title": f"[JARVIS] {message}", "merge_method": "squash"},
            timeout=15,
        )
        if resp.status_code == 200:
            return {"ok": True, "sha": resp.json().get("sha", "")[:7]}
        return {"error": f"Merge failed {resp.status_code}: {resp.text[:200]}"}
    except Exception as e:
        return {"error": str(e)}


def delete_file(repo: str, path: str, message: str) -> dict:
    """
    Delete a file from the repo: removes on jarvis-changes branch,
    opens a PR into main, and auto-merges. Requires the file to exist
    on jarvis-changes or main (sha is looked up automatically).
    """
    full_repo = _full_repo(repo)

    if not any(path.startswith(p) for p in ALLOWED_PATHS):
        return {"error": f"Blocked: '{path}' outside allowed scope ({', '.join(ALLOWED_PATHS)})"}

    sha = _get_file_sha(full_repo, path, BRANCH) or _get_file_sha(full_repo, path, MAIN_BRANCH)
    if not sha:
        return {"error": f"File not found on {BRANCH} or {MAIN_BRANCH}: {path}"}

    try:
        resp = requests.delete(
            f"{GITHUB_API}/repos/{full_repo}/contents/{path}",
            headers=_headers(),
            json={"message": f"[JARVIS] {message}", "sha": sha, "branch": BRANCH},
            timeout=15,
        )
        if resp.status_code not in (200, 201):
            return {"error": f"Delete push failed {resp.status_code}: {resp.text[:300]}"}
        commit_sha = resp.json().get("commit", {}).get("sha", "")[:7]
    except Exception as e:
        return {"error": f"Delete push error: {e}"}

    pr_result = _create_pr(
        full_repo,
        title=f"[JARVIS] {message}",
        body=f"Auto-delete by JARVIS\n\nFile: `{path}`\nMessage: {message}",
    )
    if not pr_result.get("ok"):
        return {
            "ok": True,
            "path": path,
            "branch": BRANCH,
            "commit_sha": commit_sha,
            "warning": f"Deleted on branch but PR creation failed: {pr_result.get('error')}. Merge manually.",
        }

    pr_number = pr_result["pr_number"]
    pr_url = pr_result.get("url", "")
    time.sleep(2)
    merge_result = _merge_pr(full_repo, pr_number, message)

    if not merge_result.get("ok"):
        return {
            "ok": True,
            "path": path,
            "branch": BRANCH,
            "commit_sha": commit_sha,
            "pr": pr_url,
            "warning": f"Deleted and PR created but merge failed: {merge_result.get('error')}. Merge manually: {pr_url}",
        }

    return {
        "ok": True,
        "path": path,
        "repo": full_repo,
        "branch": f"{BRANCH} -> {MAIN_BRANCH}",
        "commit_sha": commit_sha,
        "merge_sha": merge_result["sha"],
        "pr_number": pr_number,
        "message": f"Deleted '{path}', PR created, and merged to main. Render is deploying now.",
    }


def register(brain):
    brain.register_tool("delete_file", delete_file)
    log.info("delete_file_tool extension loaded")
