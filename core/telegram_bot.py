async def cmd_code(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    if not _check_auth(uid): return
    desc = " ".join(ctx.args) if ctx.args else ""
    if not desc:
        await update.message.reply_text(
            "Usage: `/code <description>`\nExample: `/code async Python function to fetch Solana token price`",
            parse_mode="Markdown"
        )
        return
    await update.message.reply_text("💻 Generating code...")
    result = _brain.run_tool("generate_code", user_id=uid, description=desc)
    await _send_long(update, f"```\n{result}\n```")


async def cmd_review(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    if not _check_auth(uid): return
    code = " ".join(ctx.args) if ctx.args else ""
    if not code:
        await update.message.reply_text(
            "Paste your code after the command:\n`/review <code>`",
            parse_mode="Markdown"
        )
        return
    await update.message.reply_text("🔍 Reviewing code...")
    result = _brain.run_tool("review_code", user_id=uid, code=code)
    await _send_long(update, result)


async def cmd_fix(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    if not _check_auth(uid): return
    text = " ".join(ctx.args) if ctx.args else ""
    if not text or "---" not in text:
        await update.message.reply_text(
            "Usage: `/fix <code> --- <error>`\nSeparate code and error with `---`",
            parse_mode="Markdown"
        )
        return
    parts = text.split("---", 1)
    code, error = parts[0].strip(), parts[1].strip()
    await update.message.reply_text("🔧 Fixing code...")
    result = _brain.run_tool("fix_code", user_id=uid, code=code, error=error)
    await _send_long(update, f"```\n{result}\n```")


async def cmd_improve(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    if not _check_auth(uid): return
    text = " ".join(ctx.args) if ctx.args else ""
    if not text:
        await update.message.reply_text(
            "Usage: `/improve <code>` or `/improve <code> --- <goal>`",
            parse_mode="Markdown"
        )
        return
    if "---" in text:
        parts = text.split("---", 1)
        code, goal = parts[0].strip(), parts[1].strip()
    else:
        code, goal = text, ""
    await update.message.reply_text("⚡ Improving code...")
    result = _brain.run_tool("improve_code", user_id=uid, code=code, goal=goal)
    await _send_long(update, f"```\n{result}\n```")


async def cmd_explain(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    if not _check_auth(uid): return
    code = " ".join(ctx.args) if ctx.args else ""
    if not code:
        await update.message.reply_text(
            "Usage: `/explain <code>`",
            parse_mode="Markdown"
        )
        return
    await update.message.reply_text("📖 Explaining code...")
    result = _brain.run_tool("explain_code", user_id=uid, code=code)
    await _send_long(update, result)
