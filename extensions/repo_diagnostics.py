"""
Extension: repo_diagnostics

Gives Orion the ability to scan its own GitHub repo for problems without
needing a local dev environment. Runs on Render, where a real Python
interpreter is available (unlike Bob's Chromebook).

Two tools:
  1. scan_repo_safety  — pattern-based scan for known risky code shapes
     (unbounded while-loops, bare excepts, retry loops with no cap,
     possible hardcoded secrets).
  2. lint_repo          — pulls every .py file and checks it for syntax
     errors using Python's built-in `ast` module (no extra install needed).

Both tools fetch file contents directly from the GitHub REST API using the
same GITHUB_TOKEN already used by commit_file, so no new credentials are
required.

Outputs are intentionally capped/truncated — this tool is meant to be
called inside the Claude tool-loop, and a full raw dump of every match in
a large repo would burn a lot of tokens for no benefit.
"""

import os
import ast
import base64
import logging
import re

import requests

log = logging.getLogger("repo_diagnostics")

GITHUB_API = "https://api.github.com"
GITHUB_TOKEN = os.getenv("GITHUB_TOKEN", "")

MAX_FILES_SCANNED = 60          # don't blow the loop budget on huge repos
MAX_FINDINGS_RETURNED = 30      # cap total findings in the response
MAX_SNIPPET_CHARS = 160         # truncate long lines in findings


def _headers():
    return {
        "Authorization": f"token {GITHUB_TOKEN}",
        "Accept": "application/vnd.github+json",
    }


def _get_python_files(repo: str, branch: str = "main") -> list:
    """Return a list of .py file paths in the repo (recursive tree)."""
    url = f"{GITHUB_API}/repos/{repo}/git/trees/{branch}?recursive=1"
    resp = requests.get(url, headers=_headers(), timeout=20)
    resp.raise_for_status()
    tree = resp.json().get("tree", [])
    return [
        item["path"]
        for item in tree
        if item.get("type") == "blob" and item["path"].endswith(".py")
    ]


def _get_file_content(repo: str, path: str, branch: str = "main") -> str:
    """Fetch and decode a single file's contents from the repo."""
    url = f"{GITHUB_API}/repos/{repo}/contents/{path}?ref={branch}"
    resp = requests.get(url, headers=_headers(), timeout=20)
    resp.raise_for_status()
    data = resp.json()
    content_b64 = data.get("content", "")
    return base64.b64decode(content_b64).decode("utf-8", errors="replace")


# ── Safety pattern checks ──────────────────────────────────────────────

_UNBOUNDED_WHILE_RE = re.compile(r"^\s*while\s+True\s*:", re.MULTILINE)
_BARE_EXCEPT_RE = re.compile(r"^\s*except\s*:\s*$", re.MULTILINE)
_POSSIBLE_SECRET_RE = re.compile(
    r"(api[_-]?key|secret|token|password)\s*=\s*[\"'][A-Za-z0-9_\-]{12,}[\"']",
    re.IGNORECASE,
)


def _check_unbounded_loops(path: str, text: str) -> list:
    """
    Flag `while True:` blocks that don't appear to have an iteration
    counter or MAX_* cap anywhere nearby in the same file. This is the
    exact bug class that caused the commit_file retry-loop cost spike.
    """
    findings = []
    for m in _UNBOUNDED_WHILE_RE.finditer(text):
        line_no = text[: m.start()].count("\n") + 1
        # crude heuristic: check the next ~15 lines for a cap/counter
        lines = text.splitlines()
        window = "\n".join(lines[line_no - 1: line_no + 15])
        if not re.search(r"MAX_|max_iter|iteration\s*>|break", window, re.IGNORECASE):
            snippet = lines[line_no - 1].strip()[:MAX_SNIPPET_CHARS]
            findings.append({
                "file": path,
                "line": line_no,
                "issue": "Unbounded while-loop with no visible iteration cap or break",
                "snippet": snippet,
            })
    return findings


def _check_bare_except(path: str, text: str) -> list:
    findings = []
    for m in _BARE_EXCEPT_RE.finditer(text):
        line_no = text[: m.start()].count("\n") + 1
        findings.append({
            "file": path,
            "line": line_no,
            "issue": "Bare 'except:' — swallows all errors including KeyboardInterrupt/SystemExit",
        })
    return findings


def _check_possible_secrets(path: str, text: str) -> list:
    findings = []
    for m in _POSSIBLE_SECRET_RE.finditer(text):
        line_no = text[: m.start()].count("\n") + 1
        findings.append({
            "file": path,
            "line": line_no,
            "issue": "Possible hardcoded secret/API key/token in source",
        })
    return findings


def scan_repo_safety(repo: str, branch: str = "main") -> dict:
    """
    Scan a GitHub repo for risky code patterns: unbounded loops, bare
    excepts, and possible hardcoded secrets. repo format: 'owner/name'.
    """
    if not GITHUB_TOKEN:
        return {"error": "GITHUB_TOKEN not set in environment"}

    try:
        py_files = _get_python_files(repo, branch)
    except Exception as e:
        return {"error": f"Could not list repo files: {e}"}

    scanned = py_files[:MAX_FILES_SCANNED]
    all_findings = []

    for path in scanned:
        try:
            text = _get_file_content(repo, path, branch)
        except Exception as e:
            log.warning(f"Could not fetch {path}: {e}")
            continue

        all_findings.extend(_check_unbounded_loops(path, text))
        all_findings.extend(_check_bare_except(path, text))
        all_findings.extend(_check_possible_secrets(path, text))

        if len(all_findings) >= MAX_FINDINGS_RETURNED:
            break

    truncated = len(all_findings) > MAX_FINDINGS_RETURNED
    return {
        "repo": repo,
        "branch": branch,
        "files_scanned": len(scanned),
        "total_python_files": len(py_files),
        "findings_count": len(all_findings),
        "findings": all_findings[:MAX_FINDINGS_RETURNED],
        "truncated": truncated,
    }


# ── Lint / syntax check ────────────────────────────────────────────────

def lint_repo(repo: str, branch: str = "main") -> dict:
    """
    Check every .py file in a GitHub repo for syntax errors using Python's
    built-in ast module. repo format: 'owner/name'.
    """
    if not GITHUB_TOKEN:
        return {"error": "GITHUB_TOKEN not set in environment"}

    try:
        py_files = _get_python_files(repo, branch)
    except Exception as e:
        return {"error": f"Could not list repo files: {e}"}

    scanned = py_files[:MAX_FILES_SCANNED]
    errors = []

    for path in scanned:
        try:
            text = _get_file_content(repo, path, branch)
        except Exception as e:
            log.warning(f"Could not fetch {path}: {e}")
            continue

        try:
            ast.parse(text, filename=path)
        except SyntaxError as e:
            errors.append({
                "file": path,
                "line": e.lineno,
                "error": str(e.msg),
            })

        if len(errors) >= MAX_FINDINGS_RETURNED:
            break

    return {
        "repo": repo,
        "branch": branch,
        "files_checked": len(scanned),
        "total_python_files": len(py_files),
        "syntax_errors_found": len(errors),
        "errors": errors[:MAX_FINDINGS_RETURNED],
        "clean": len(errors) == 0,
    }


def register(brain):
    """Register this extension's tools with the Brain instance."""
    brain.register_extension("scan_repo_safety", scan_repo_safety)
    brain.register_extension("lint_repo", lint_repo)
    log.info("repo_diagnostics extension registered: scan_repo_safety, lint_repo")
