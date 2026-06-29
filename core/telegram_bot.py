"""
JARVIS Telegram Bot
Commands:
  /arb       — Solana cross-DEX spread scan
  /pnl       — Today's P&L report
  /status    — Bot status
  /genbot    — Generate a new trading bot
  /model     — Switch LLM provider
  /voice     — Toggle voice replies on/off
  /search    — Web search
  /remember  — Save a fact to memory
  /recall    — Recall memories
  /code      — Generate code
  /review    — Review code
  /fix       — Fix broken code
  /improve   — Improve code
  /explain   — Explain code
  /sol       — Live SOL price
  /clear     — Clear conversation history
  Free text  — Chat with JARVIS
  Voice msg  — JARVIS transcribes + responds
"""

import os
import io
import logging
import asyncio
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    Application, CommandHandler, MessageHandler,
    CallbackQueryHandler, ContextTypes, filters
)

log = logging.getLogger("telegram_bot")

ALLOWED_USERS = set(
    int(x) for x in os.getenv("TELEGRAM_ALLOWED_USERS", "").split(",") if x.strip()
)

_brain = None
_voice_users: set = set()


def _check_auth(user_id: int) -> bool:
    if not ALLOWED_USERS:
        return True
    return user_id in ALLOWED_USERS


async def _send_long(update: Update, text: str):
    if len(text) <= 4096:
        await update.message.reply_text(text, parse_mode="Markdown")
        return
    chunks = [text[i:i+4096] for i in range(0, len(text), 4096)]
    for chunk in chunks:
        await update.message.reply_text(chunk, parse_mode="Markdown")


# ── Command handlers ───────────────────────────────────────────────────────────

async def cmd_start(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    if not _check_auth(uid):
        await update.message.reply_text("🚫 Unauthorized.")
        return
    await update.message.reply_text(
        "⚙️ *JARVIS Mark 5 online.*\n\n"
        "/arb — Solana spread scan\n"
        "/pnl — P&L report\n"
        "/status — Bot status\n"
        "/genbot — Generate a trading bot\n"
        "/model — Switch AI provider\n"
        "/voice — Toggle voice replies\n"
        "/search — Web search\n"
        "/remember — Save a fact\n"
        "/recall — Recall memories\n"
        "/code — Generate code\n"
        "/review — Review code\n"
        "/fix — Fix broken code\n"
        "/improve — Improve code\n"
        "/explain — Explain code\n"
        "/sol — Live SOL price\n"
        "/clear — Clear chat history\n\n"
        "Send a voice message and I'll transcribe + respond.\n"
        "Use /voice to also get audio replies.",
        parse_mode="Markdown"
    )


async def cmd_arb(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    if not _check_auth(uid): return
    await update.message.reply_text("🔍 Scanning DEX spreads...")
    result = _brain.run_tool("solana_market")
    text = _format_arb(result)
    await _send_long(update, text)


async def cmd_pnl(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    if not _check_auth(uid): return
    await update.message.reply_text("📊 Fetching P&L...")
    result = _brain.run_tool("pnl_report")
    text = _format_pnl(result)
    await _send_long(update, text)


async def cmd_status(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    if not _check_auth(uid): return
    result = _brain.run_tool("bot_status")
    text = _format_status(result)
    await _send_long(update, text)


async def cmd_genbot(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    if not _check_auth(uid): return
    desc = " ".join(ctx.args) if ctx.args else ""
    if not desc:
        await update.message.reply_text(
            "Usage: `/genbot <description>`\nExample: `/genbot SOL/USDC arb bot using Raydium and Orca`",
            parse_mode="Markdown"
        )
        return
    await update.message.reply_text("🤖 Generating bot... (may take up to 60s)")
    result = _brain.run_tool("bot_generator", description=desc)
    if "error" in result:
        await update.message.reply_text(f"❌ {result['error']}")
        return
    code = result.get("code", "")
    await _send_long(update, f"```python\n{code}\n```")


async def cmd_model(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    if not _check_auth(uid): return
    keyboard = [
        [
            InlineKeyboardButton("🧠 Claude (default)", callback_data="model:claude"),
            InlineKeyboardButton("⚡ Groq (fast)", callback_data="model:groq"),
        ],
        [InlineKeyboardButton("🔮 OpenAI GPT-4o", callback_data="model:openai")],
    ]
    await update.message.reply_text(
        "Choose AI provider:",
        reply_markup=InlineKeyboardMarkup(keyboard)
    )


async def cb_model(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    uid = query.from_user.id
    if not _check_auth(uid): return
    provider = query.data.split(":")[1]
    try:
        _brain.set_provider(uid, provider)
        await query.edit_message_text(f"✅ Provider set to *{provider}*", parse_mode="Markdown")
    except ValueError as e:
        await query.edit_message_text(f"❌ {e}")


async def cmd_clear(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    if not _check_auth(uid): return
    _brain.clear_history(uid)
    await update.message.reply_text("🗑️ Conversation history cleared.")


async def cmd_voice(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    if not _check_auth(uid): return
    if uid in _voice_users:
        _voice_users.discard(uid)
        await update.message.reply_text("🔇 Voice replies *off*.", parse_mode="Markdown")
    else:
        _voice_users.add(uid)
        await update.message.reply_text("🔊 Voice replies *on*.", parse_mode="Markdown")


async def cmd_search(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    if not _check_auth(uid): return
    query = " ".join(ctx.args) if ctx.args else ""
    if not query:
        await update.message.reply_text("Usage: `/search <query>`", parse_mode="Markdown")
        return
    await update.message.reply_text(f"🔍 Searching: _{query}_...", parse_mode="Markdown")
    result = _brain.run_tool("web_search", query=query)
    if "error" in result:
        await update.message.reply_text(f"❌ {result['error']}")
        return
    lines = [f"*🔍 Results for:* `{query}`\n"]
    for r in result.get("results", []):
        snippet = r['snippet'][:120]
        lines.append(f"• [{r['title']}]({r['url']})\n  _{snippet}_")
    if not result.get("results"):
        lines.append("No results found.")
    await _send_long(update, "\n\n".join(lines))


async def cmd_remember(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    if not _check_auth(uid): return
    text = " ".join(ctx.args) if ctx.args else ""
    if not text or "=" not in text:
        await update.message.reply_text(
            "Usage: `/remember key=value`\nExample: `/remember preferred_dex=Raydium`",
            parse_mode="Markdown"
        )
        return
    key, value = text.split("=", 1)
    result = _brain.run_tool("remember", user_id=uid, key=key.strip(), value=value.strip())
    await update.message.reply_text(f"✅ {result.get('message', 'Saved.')}")


async def cmd_recall(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    if not _check_auth(uid): return
    query = " ".join(ctx.args) if ctx.args else ""
    result = _brain.run_tool("recall", user_id=uid, query=query)
    if "error" in result:
        await update.message.reply_text(f"❌ {result['error']}")
        return
    memories = result.get("memories", [])
    if not memories:
        await update.message.reply_text("No memories found.")
        return
    lines = ["*🧠 JARVIS Memory*\n"]
    for m in memories:
        lines.append(f"• *{m['key']}*: {m['value']}")
    await _send_long(update, "\n".join(lines))


async def cmd_code(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    if not _check_auth(uid): return
    desc = " ".join(ctx.args) if ctx.args else ""
    if not desc:
        await update.message.reply_text(
            "Usage: `/code <description>`\nExample: `/code async Python function to fetch SOL price`",
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
            "Usage: `/review <code>`",
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
            "Usage: `/fix <code> --- <error>`",
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


async def cmd_sol(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    if not _check_auth(uid): return
    await update.message.reply_text("◎ Fetching SOL price...")
    result = _brain.run_tool("sol_price")
    if "error" in result:
        await update.message.reply_text(f"❌ {result['error']}")
        return
    await update.message.reply_text(
        f"◎ *SOL Price*: `${result['price']:,.2f}`",
        parse_mode="Markdown"
    )


# ── Message handlers ───────────────────────────────────────────────────────────

async def _reply_with_voice(update: Update, ctx, text: str, uid: int):
    await _send_long(update, text)
    if uid in _voice_users:
        try:
            await ctx.bot.send_chat_action(update.effective_chat.id, "record_voice")
            audio = _brain.run_tool("speak", text=text)
            if isinstance(audio, bytes) and len(audio) > 0:
                buf = io.BytesIO(audio)
                buf.name = "jarvis.ogg"
                buf.seek(0)
                await ctx.bot.send_voice(
                    chat_id=update.effective_chat.id,
                    voice=buf,
                )
        except Exception as e:
            log.warning(f"TTS failed: {e}")


async def handle_voice(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    if not _check_auth(uid):
        await update.message.reply_text("🚫 Unauthorized.")
        return

    await ctx.bot.send_chat_action(update.effective_chat.id, "typing")

    try:
        voice_file = await update.message.voice.get_file()
        audio_bytes = bytes(await voice_file.download_as_bytearray())
    except Exception as e:
        await update.message.reply_text(f"❌ Could not download voice message: {e}")
        return

    try:
        transcript = _brain.run_tool("transcribe", audio_bytes=audio_bytes)
        if isinstance(transcript, dict) and "error" in transcript:
            await update.message.reply_text(f"❌ Transcription failed: {transcript['error']}")
            return
        if not isinstance(transcript, str) or not transcript.strip():
            await update.message.reply_text("❌ Could not transcribe audio — try again.")
            return
    except Exception as e:
        await update.message.reply_text(f"❌ Transcription error: {e}")
        return

    await update.message.reply_text(f"🎙️ _{transcript}_", parse_mode="Markdown")

    lower = transcript.lower()
    if any(w in lower for w in ["spread", "arb", "arbitrage", "raydium", "orca"]):
        intent = "arb"
    elif any(w in lower for w in ["pnl", "profit", "loss", "trade"]):
        intent = "pnl"
    elif any(w in lower for w in ["generate", "build", "create", "make", "write"]) and "bot" in lower:
        intent = "genbot"
    else:
        intent = "default"

    mem_context = _brain.run_tool("get_memory_context", user_id=uid)
    if mem_context and isinstance(mem_context, str):
        transcript = f"{mem_context}\n\nUser message: {transcript}"

    reply = _brain.chat(uid, transcript, intent=intent)
    await _reply_with_voice(update, ctx, reply, uid)


async def handle_message(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    if not _check_auth(uid):
        await update.message.reply_text("🚫 Unauthorized.")
        return

    text = update.message.text or ""
    await ctx.bot.send_chat_action(update.effective_chat.id, "typing")
    lower = text.lower()

    if lower.startswith("search:") or lower.startswith("search "):
        query = text.split(" ", 1)[1] if " " in text else text[7:]
        result = _brain.run_tool("web_search", query=query)
        reply = _brain.chat(
            uid,
            f"Web search results for '{query}': {result}\n\nSummarize these results clearly.",
            intent="default"
        )
        await _reply_with_voice(update, ctx, reply, uid)
        return

    if any(w in lower for w in ["spread", "arb", "arbitrage", "raydium", "orca"]):
        intent = "arb"
    elif any(w in lower for w in ["pnl", "profit", "loss", "trade"]):
        intent = "pnl"
    elif any(w in lower for w in ["generate", "build", "create", "make", "write"]) and "bot" in lower:
        intent = "genbot"
    else:
        intent = "default"

    mem_context = _brain.run_tool("get_memory_context", user_id=uid)
    if mem_context and isinstance(mem_context, str):
        text = f"{mem_context}\n\nUser message: {text}"

    reply = _brain.chat(uid, text, intent=intent)
    await _reply_with_voice(update, ctx, reply, uid)


# ── Formatters ─────────────────────────────────────────────────────────────────

def _format_arb(result: dict) -> str:
    if "error" in result:
        return f"❌ {result['error']}"
    lines = ["*📈 Solana DEX Spreads*\n"]
    opps = result.get("opportunities", [])
    if not opps:
        return "No executable spreads found right now."
    for o in opps[:10]:
        flag = "✅" if o.get("executable") else "⚠️"
        lines.append(
            f"{flag} *{o['token']}* | {o['buy_dex']} → {o['sell_dex']}\n"
            f"   Gross: {o.get('gross_spread_pct', 0):.2f}% | Net: {o.get('net_spread_pct', 0):.2f}% | Est: ${o.get('est_profit_usd', 0):.4f}"
        )
    return "\n".join(lines)


def _format_pnl(result: dict) -> str:
    if "error" in result:
        return f"❌ {result['error']}"
    return (
        f"*📊 P&L Report*\n\n"
        f"Today: `{result.get('today_pnl', 'N/A')}`\n"
        f"7d:    `{result.get('week_pnl', 'N/A')}`\n"
        f"Trades: `{result.get('trade_count', 'N/A')}`\n"
        f"Win rate: `{result.get('win_rate', 'N/A')}`"
    )


def _format_status(result: dict) -> str:
    if "error" in result:
        return f"❌ {result['error']}"
    bots = result.get("bots", [])
    if not bots:
        return "No bots registered."
    lines = ["*⚙️ Bot Status*\n"]
    for b in bots:
        icon = "🟢" if b.get("status") == "running" else "🔴"
        lines.append(f"{icon} *{b['name']}* — {b.get('status', 'unknown')}")
    return "\n".join(lines)


# ── Start ──────────────────────────────────────────────────────────────────────

async def start_telegram_bot(brain):
    global _brain
    _brain = brain

    token = os.getenv("TELEGRAM_BOT_TOKEN")
    if not token:
        raise RuntimeError("TELEGRAM_BOT_TOKEN not set in .env")

    app = Application.builder().token(token).build()

    app.add_handler(CommandHandler("start",    cmd_start))
    app.add_handler(CommandHandler("arb",      cmd_arb))
    app.add_handler(CommandHandler("pnl",      cmd_pnl))
    app.add_handler(CommandHandler("status",   cmd_status))
    app.add_handler(CommandHandler("genbot",   cmd_genbot))
    app.add_handler(CommandHandler("model",    cmd_model))
    app.add_handler(CommandHandler("voice",    cmd_voice))
    app.add_handler(CommandHandler("search",   cmd_search))
    app.add_handler(CommandHandler("remember", cmd_remember))
    app.add_handler(CommandHandler("recall",   cmd_recall))
    app.add_handler(CommandHandler("code",     cmd_code))
    app.add_handler(CommandHandler("review",   cmd_review))
    app.add_handler(CommandHandler("fix",      cmd_fix))
    app.add_handler(CommandHandler("improve",  cmd_improve))
    app.add_handler(CommandHandler("explain",  cmd_explain))
    app.add_handler(CommandHandler("sol",      cmd_sol))
    app.add_handler(CommandHandler("clear",    cmd_clear))
    app.add_handler(CallbackQueryHandler(cb_model, pattern="^model:"))
    app.add_handler(MessageHandler(filters.VOICE, handle_voice))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))

    log.info("Telegram bot running...")

    async with app:
        await app.start()
        await app.updater.start_polling(allowed_updates=Update.ALL_TYPES)
        await asyncio.Event().wait()
        await app.updater.stop()
        await app.stop()
