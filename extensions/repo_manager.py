"""
Extension: repo_manager
Gives JARVIS full lifecycle control over GitHub repos:
create, delete, configure settings, branch protection,
collaborators, topics, and webhooks.

Uses the same GITHUB_TOKEN as github_editor/github_tools.
NOTE: repo deletion requires the token to have the
'delete_repo' scope (classic PAT) or 'Administration: write'
(fine-grained PAT). If that scope is missing, delete_repo()
will return a clear 403 error instead of failing silently.
"""

import os
import logging
import requests

log = logging.getLogger("jarvis.ext.repo_manager")

GITHUB_API = "https://api.github.com"
DEFAULT_OWNER = os.getenv("GITHUB_USERNAME", "bobwhite6973")


def _headers():
    token = os.environ.get("GITHUB_TOKEN", "")
    return {
        "Authorization": f"token {token}",
        "Accept": "application/vnd.github.v3+json",
        "Content-Type": "application/json",
    }


def _full_repo(repo: str, owner: str = DEFAULT_OWNER) -> str:
    return repo if "/" in repo else f"{owner}/{repo}"


def create_repo(name: str, description: str = "", private: bool = True,
                 org: str = None, auto_init: bool = True) -> dict:
    """Create a brand new repo for the authenticated user, or inside an org."""
    payload = {
        "name": name,
        "description": description,
        "private": private,
        "auto_init": auto_init,
    }
    url = f"{GITHUB_API}/orgs/{org}/repos" if org else f"{GITHUB_API}/user/repos"
    try:
        resp = requests.post(url, headers=_headers(), json=payload, timeout=15)
        if resp.status_code == 201:
            data = resp.json()
            return {"ok": True, "full_name": data["full_name"], "html_url": data["html_url"]}
        return {"error": f"Create failed {resp.status_code}: {resp.text[:300]}"}
    except Exception as e:
        return {"error": str(e)}


def delete_repo(repo: str, owner: str = DEFAULT_OWNER) -> dict:
    """Permanently delete a repo. Requires 'delete_repo' scope on the token."""
    full = _full_repo(repo, owner)
    try:
        resp = requests.delete(f"{GITHUB_API}/repos/{full}", headers=_headers(), timeout=15)
        if resp.status_code == 204:
            return {"ok": True, "deleted": full}
        if resp.status_code == 403:
            return {"error": "Token lacks 'delete_repo' scope. Add it in GitHub PAT settings."}
        return {"error": f"Delete failed {resp.status_code}: {resp.text[:300]}"}
    except Exception as e:
        return {"error": str(e)}


def update_repo(repo: str, owner: str = DEFAULT_OWNER, **fields) -> dict:
    """Update settings: description, private, has_issues, default_branch, etc."""
    full = _full_repo(repo, owner)
    try:
        resp = requests.patch(f"{GITHUB_API}/repos/{full}", headers=_headers(), json=fields, timeout=15)
        if resp.status_code == 200:
            return {"ok": True, "updated": list(fields.keys())}
        return {"error": f"Update failed {resp.status_code}: {resp.text[:300]}"}
    except Exception as e:
        return {"error": str(e)}


def set_topics(repo: str, topics: list, owner: str = DEFAULT_OWNER) -> dict:
    full = _full_repo(repo, owner)
    try:
        resp = requests.put(
            f"{GITHUB_API}/repos/{full}/topics",
            headers=_headers(), json={"names": topics}, timeout=15
        )
        if resp.status_code == 200:
            return {"ok": True, "topics": resp.json().get("names", [])}
        return {"error": f"Set topics failed {resp.status_code}: {resp.text[:300]}"}
    except Exception as e:
        return {"error": str(e)}


def set_branch_protection(repo: str, branch: str = "main", owner: str = DEFAULT_OWNER,
                           required_reviews: int = 0) -> dict:
    full = _full_repo(repo, owner)
    payload = {
        "required_status_checks": None,
        "enforce_admins": False,
        "required_pull_request_reviews": (
            {"required_approving_review_count": required_reviews} if required_reviews else None
        ),
        "restrictions": None,
    }
    try:
        resp = requests.put(
            f"{GITHUB_API}/repos/{full}/branches/{branch}/protection",
            headers=_headers(), json=payload, timeout=15
        )
        if resp.status_code == 200:
            return {"ok": True, "branch": branch, "protected": True}
        return {"error": f"Protection failed {resp.status_code}: {resp.text[:300]}"}
    except Exception as e:
        return {"error": str(e)}


def add_collaborator(repo: str, username: str, permission: str = "push",
                      owner: str = DEFAULT_OWNER) -> dict:
    full = _full_repo(repo, owner)
    try:
        resp = requests.put(
            f"{GITHUB_API}/repos/{full}/collaborators/{username}",
            headers=_headers(), json={"permission": permission}, timeout=15
        )
        if resp.status_code in (201, 204):
            return {"ok": True, "added": username, "permission": permission}
        return {"error": f"Add collaborator failed {resp.status_code}: {resp.text[:300]}"}
    except Exception as e:
        return {"error": str(e)}


def create_webhook(repo: str, url: str, events: list = None,
                    owner: str = DEFAULT_OWNER) -> dict:
    full = _full_repo(repo, owner)
    payload = {
        "name": "web",
        "active": True,
        "events": events or ["push"],
        "config": {"url": url, "content_type": "json"},
    }
    try:
        resp = requests.post(f"{GITHUB_API}/repos/{full}/hooks", headers=_headers(), json=payload, timeout=15)
        if resp.status_code == 201:
            return {"ok": True, "webhook_id": resp.json().get("id"), "url": url}
        return {"error": f"Webhook failed {resp.status_code}: {resp.text[:300]}"}
    except Exception as e:
        return {"error": str(e)}


def get_repo_settings(repo: str, owner: str = DEFAULT_OWNER) -> dict:
    full = _full_repo(repo, owner)
    try:
        resp = requests.get(f"{GITHUB_API}/repos/{full}", headers=_headers(), timeout=15)
        if resp.status_code == 200:
            d = resp.json()
            return {
                "full_name": d["full_name"],
                "private": d["private"],
                "default_branch": d["default_branch"],
                "description": d.get("description"),
                "topics": d.get("topics", []),
                "html_url": d["html_url"],
            }
        return {"error": f"Fetch failed {resp.status_code}: {resp.text[:300]}"}
    except Exception as e:
        return {"error": str(e)}


def register(brain):
    brain.register_tool("create_repo", create_repo)
    brain.register_tool("delete_repo", delete_repo)
    brain.register_tool("update_repo", update_repo)
    brain.register_tool("set_topics", set_topics)
    brain.register_tool("set_branch_protection", set_branch_protection)
    brain.register_tool("add_collaborator", add_collaborator)
    brain.register_tool("create_webhook", create_webhook)
    brain.register_tool("get_repo_settings", get_repo_settings)
    log.info("repo_manager extension registered — full repo lifecycle control enabled")
