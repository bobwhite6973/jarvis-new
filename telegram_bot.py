async def cmd_browse(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    if not _check_auth(uid): return
    url = " ".join(ctx.args) if ctx.args else ""
    if not url:
        await update.message.reply_text("Usage: `/browse <url>`", parse_mode="Markdown")
        return
    await update.message.reply_text(f"🌐 Fetching: {url}...")
    result = _brain.run_tool("browse", url=url)
    if "error" in result:
        await update.message.reply_text(f"❌ {result['error']}")
        return
    summary = _brain.chat(uid, f"Summarize this webpage content concisely:\n\n{result['content']}")
    await _send_long(update, f"🌐 *{url}*\n\n{summary}")


async def cmd_github(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    if not _check_auth(uid): return
    args = ctx.args if ctx.args else []
    if not args:
        await update.message.reply_text(
            "Usage:\n"
            "`/github repos` — list your repos\n"
            "`/github files <repo>` — list files\n"
            "`/github read <repo> <path>` — read a file\n"
            "`/github commits <repo>` — recent commits\n"
            "`/github search <query>` — search your code",
            parse_mode="Markdown"
        )
        return

    cmd = args[0].lower()

    if cmd == "repos":
        result = _brain.run_tool("list_repos")
        if "error" in result:
            await update.message.reply_text(f"❌ {result['error']}")
            return
        lines = ["*📁 Your Repos*\n"]
        for r in result["repos"]:
            icon = "🔒" if r["private"] else "📂"
            desc = f" — {r['description']}" if r.get("description") else ""
            lines.append(f"{icon} *{r['name']}*{desc}")
        await _send_long(update, "\n".join(lines))

    elif cmd == "files" and len(args) >= 2:
        repo = args[1]
        path = args[2] if len(args) > 2 else ""
        result = _brain.run_tool("list_files", repo=repo, path=path)
        if "error" in result:
            await update.message.reply_text(f"❌ {result['error']}")
            return
        lines = [f"*📁 {repo}/{result['path']}*\n"]
        for f in result["items"]:
            icon = "📁" if f["type"] == "dir" else "📄"
            lines.append(f"{icon} {f['name']}")
        await _send_long(update, "\n".join(lines))

    elif cmd == "read" and len(args) >= 3:
        repo = args[1]
        path = args[2]
        result = _brain.run_tool("get_file", repo=repo, path=path)
        if "error" in result:
            await update.message.reply_text(f"❌ {result['error']}")
            return
        await _send_long(update, f"*📄 {repo}/{path}*\n\n```\n{result['content']}\n```")

    elif cmd == "commits" and len(args) >= 2:
        repo = args[1]
        result = _brain.run_tool("get_commits", repo=repo)
        if "error" in result:
            await update.message.reply_text(f"❌ {result['error']}")
            return
        lines = [f"*📝 Recent commits: {repo}*\n"]
        for c in result["commits"]:
            lines.append(f"`{c['sha']}` {c['message']} — _{c['author']}_")
        await _send_long(update, "\n".join(lines))

    elif cmd == "search" and len(args) >= 2:
        query = " ".join(args[1:])
        result = _brain.run_tool("search_code", query=query)
        if "error" in result:
            await update.message.reply_text(f"❌ {result['error']}")
            return
        lines = [f"*🔍 Code search: {query}*\n"]
        for r in result["results"]:
            lines.append(f"• *{r['repo']}* — `{r['path']}`")
        if not result["results"]:
            lines.append("No results found.")
        await _send_long(update, "\n".join(lines))

    else:
        await update.message.reply_text("❌ Unknown command. Try `/github` for usage.", parse_mode="Markdown")
