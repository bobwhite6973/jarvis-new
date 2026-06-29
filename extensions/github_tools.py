"""
Extension: github_tools
Read GitHub repos, files, commits, and issues via GitHub API.
Set GITHUB_TOKEN in .env for private repo access.
"""
import os
import logging
import requests
import base64

log = logging.getLogger("jarvis.github")

GITHUB_TOKEN = os.getenv("GITHUB_TOKEN", "")
BASE_URL = "https://api.github.com"
DEFAULT_OWNER = os.getenv("GITHUB_USERNAME", "bobwhite6973")


def _headers():
    h = {"Accept": "application/vnd.github.v3+json"}
    if GITHUB_TOKEN:
        h["Authorization"] = f"token {GITHUB_TOKEN}"
    return h


def list_repos(owner: str = DEFAULT_OWNER) -> dict:
    """List all repos for a user."""
    try:
        resp = requests.get(
            f"{BASE_URL}/users/{owner}/repos?per_page=30&sort=updated",
            headers=_headers(), timeout=10
        )
        resp.raise_for_status()
        repos = [{"name": r["name"], "description": r.get("description",""), "updated": r["updated_at"], "private": r["private"]} for r in resp.json()]
        return {"repos": repos, "count": len(repos)}
    except Exception as e:
        return {"error": str(e)}


def get_file(repo: str, path: str, owner: str = DEFAULT_OWNER) -> dict:
    """Get contents of a file from a repo."""
    try:
        resp = requests.get(
            f"{BASE_URL}/repos/{owner}/{repo}/contents/{path}",
            headers=_headers(), timeout=10
        )
        resp.raise_for_status()
        data = resp.json()
        if data.get("encoding") == "base64":
            content = base64.b64decode(data["content"]).decode("utf-8", errors="replace")
        else:
            content = data.get("content", "")
        if len(content) > 4000:
            content = content[:4000] + "\n...[truncated]"
        return {"file": path, "repo": repo, "content": content}
    except Exception as e:
        return {"error": str(e)}


def list_files(repo: str, path: str = "", owner: str = DEFAULT_OWNER) -> dict:
    """List files in a repo directory."""
    try:
        url = f"{BASE_URL}/repos/{owner}/{repo}/contents/{path}"
        resp = requests.get(url, headers=_headers(), timeout=10)
        resp.raise_for_status()
        items = [{"name": f["name"], "type": f["type"], "path": f["path"]} for f in resp.json()]
        return {"path": path or "/", "repo": repo, "items": items}
    except Exception as e:
        return {"error": str(e)}


def get_commits(repo: str, owner: str = DEFAULT_OWNER, limit: int = 10) -> dict:
    """Get recent commits for a repo."""
    try:
        resp = requests.get(
            f"{BASE_URL}/repos/{owner}/{repo}/commits?per_page={limit}",
            headers=_headers(), timeout=10
        )
        resp.raise_for_status()
        commits = [{"sha": c["sha"][:7], "message": c["commit"]["message"].split("\n")[0], "author": c["commit"]["author"]["name"], "date": c["commit"]["author"]["date"]} for c in resp.json()]
        return {"repo": repo, "commits": commits}
    except Exception as e:
        return {"error": str(e)}


def get_issues(repo: str, owner: str = DEFAULT_OWNER) -> dict:
    """Get open issues for a repo."""
    try:
        resp = requests.get(
            f"{BASE_URL}/repos/{owner}/{repo}/issues?state=open&per_page=20",
            headers=_headers(), timeout=10
        )
        resp.raise_for_status()
        issues = [{"number": i["number"], "title": i["title"], "state": i["state"]} for i in resp.json()]
        return {"repo": repo, "issues": issues}
    except Exception as e:
        return {"error": str(e)}


def search_code(query: str, owner: str = DEFAULT_OWNER) -> dict:
    """Search code across your repos."""
    try:
        resp = requests.get(
            f"{BASE_URL}/search/code?q={query}+user:{owner}",
            headers=_headers(), timeout=10
        )
        resp.raise_for_status()
        items = [{"repo": i["repository"]["name"], "path": i["path"], "url": i["html_url"]} for i in resp.json().get("items", [])[:10]]
        return {"query": query, "results": items}
    except Exception as e:
        return {"error": str(e)}


def register(brain):
    brain.register_tool("list_repos", list_repos)
    brain.register_tool("get_file", get_file)
    brain.register_tool("list_files", list_files)
    brain.register_tool("get_commits", get_commits)
    brain.register_tool("get_issues", get_issues)
    brain.register_tool("search_code", search_code)
    log.info("github_tools extension registered")
