def audit_repo(brain, repo: str, owner: str = DEFAULT_OWNER) -> dict:
    """Full repo audit — lists files, reads each, summarizes issues."""
    try:
        # Get file list
        files_result = list_files(repo=repo, owner=owner)
        if "error" in files_result:
            return {"error": files_result["error"]}

        items = files_result.get("items", [])
        code_files = [f for f in items if f["type"] == "file" and any(
            f["name"].endswith(ext) for ext in [".py", ".js", ".ts", ".json", ".yaml", ".yml", ".md", ".txt", ".env.example"]
        )]

        if not code_files:
            return {"error": "No code files found in root directory."}

        report = []
        for f in code_files[:15]:  # cap at 15 files
            file_result = get_file(repo=repo, path=f["path"], owner=owner)
            if "error" in file_result:
                report.append(f"❌ {f['name']}: could not read")
                continue
            content = file_result.get("content", "")
            summary = brain.chat(
                0,
                f"Audit this file from the '{repo}' repo. Be concise. Flag: bugs, security issues, missing error handling, hardcoded secrets, or improvements needed. File: {f['name']}\n\n{content[:2000]}"
            )
            report.append(f"📄 **{f['name']}**\n{summary}")

        return {"repo": repo, "files_audited": len(report), "report": report}

    except Exception as e:
        log.error(f"Audit failed: {e}")
        return {"error": str(e)}
