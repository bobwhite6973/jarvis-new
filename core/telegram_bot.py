"""
Telegram Bot - Mobile-first UI for JARVIS Mark 5
Compatible with Mark 5 Brain API (brain.chat, brain.set_provider, etc.)
"""

import os
import logging
import asyncio
from telegram import Update
from telegram import InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    Application, CommandHandler, MessageHandler,
    CallbackQueryHandler, filters, ContextTypes
)
from core.brain import Brain

log = logging.getLogger("jarvis.telegram")

PROVIDERS = {
    "claude": "Claude Sonnet 4.6",
    "groq":   "Groq LLaMA 3.3 70B",
    "openai": "GPT-4o",
}


async def start_telegram_bot(brain: Brain):
    """Entry point called from jarvis.py asyncio.gather()"""
    bot = TelegramBot(brain)
    await bot.run()


class TelegramBot:
    def __init__(self, brain: Brain):
        self.brain = brain
        self.token = os.environ["TELEGRAM_BOT_TOKEN"]
        raw = os.environ.get("ALLOWED_USER_IDS", "")
        self.allowed_ids = set(int(x.strip()) for x in raw.split(",") if x.strip())

    def _uid(self, update: Update) -> int:
        return update.effective_user.id

    def _allowed(self, update: Update) -> bool:
        if not self.allowed_ids:
            return True
        return update.effective_user.id in self.allowed_ids

    async def _deny(self, update: Update):
        await update.message.reply_text("Unauthorized.")

    def _chat(self, user_id: int, message: str, intent: str = "default") -> str:
        return self.brain.chat(user_id, message, intent)

    async def cmd_start(self, update: Update, ctx: ContextTypes.DEFAULT_TYPE):
        if not self._allowed(update):
            return await self._deny(update)
        name = update.effective_user.first_name
        uid = self._uid(update)
        provider = self.brain.user_provider.get(uid, "claude")
        label = PROVIDERS.get(provider, provider)
        await update.message.reply_text(
            f"JARVIS online, {name}.\n\nActive model: {label}\n\nType anything to talk. Use /help for commands."
        )

    async def cmd_help(self, update: Update, ctx: ContextTypes.DEFAULT_TYPE):
        if not self._allowed(update):
            return await self._deny(update)
        await update.message.reply_text(
            "JARVIS Commands\n\n"
            "/model - switch LLM provider\n"
            "/clear - clear conversation history\n"
            "/status - bot statuses\n"
            "/pnl - today P&L summary\n"
            "/arb - Solana arb spreads\n"
            "/genbot description - scaffold a trading bot\n"
            "/remember key = value - store permanently\n"
            "/recall key - retrieve stored value\n"
            "/approve - approve pending GitHub change\n"
            "/reject - reject pending GitHub change\n"
            "/diff - show pending GitHub change\n"
            "/rollback - revert last JARVIS commit\n"
            "/help - this menu"
        )

    async def cmd_model(self, update: Update, ctx: ContextTypes.DEFAULT_TYPE):
        if not self._allowed(update):
            return await self._deny(update)
        uid = self._uid(update)
        current = self.brain.user_provider.get(uid, "claude")
        buttons = []
        for p, label in PROVIDERS.items():
            tick = "OK " if p == current else ""
            buttons.append([InlineKeyboardButton(f"{tick}{label}", callback_data=f"model:{p}")])
        await update.message.reply_text("Choose your LLM provider:", reply_markup=InlineKeyboardMarkup(buttons))

    async def cb_model(self, update: Update, ctx: ContextTypes.DEFAULT_TYPE):
        query = update.callback_query
        await query.answer()
        provider = query.data.split(":")[1]
        uid = query.from_user.id
        try:
            self.brain.set_provider(uid, provider)
            label = PROVIDERS.get(provider, provider)
            await query.edit_message_text(f"Switched to {label}")
        except ValueError as e:
            await query.edit_message_text(str(e))

    async def cmd_clear(self, update: Update, ctx: ContextTypes.DEFAULT_TYPE):
        if not self._allowed(update):
            return await self._deny(update)
        self.brain.clear_history(self._uid(update))
        await update.message.reply_text("Conversation history cleared. Persistent memory kept.")

    async def cmd_status(self, update: Update, ctx: ContextTypes.DEFAULT_TYPE):
        if not self._allowed(update):
            return await self._deny(update)
        result = self.brain.run_tool("bot_control", query="show status")
        await update.message.reply_text(str(result) if result else "No bot status available.")

    async def cmd_pnl(self, update: Update, ctx: ContextTypes.DEFAULT_TYPE):
        if not self._allowed(update):
            return await self._deny(update)
        msg = await update.message.reply_text("Fetching P&L...")
        result = self.brain.run_tool("pnl_report")
        await msg.edit_text(str(result) if result else "No P&L data available.")

    async def cmd_arb(self, update: Update, ctx: ContextTypes.DEFAULT_TYPE):
        if not self._allowed(update):
            return await self._deny(update)
        msg = await update.message.reply_text("Scanning for arb spreads...")
        result = self.brain.run_tool("solana_market")
        if asyncio.iscoroutine(result):
            result = await result
        await msg.edit_text(str(result) if result else "No arb data available.")

    async def cmd_genbot(self, update: Update, ctx: ContextTypes.DEFAULT_TYPE):
        if not self._allowed(update):
            return await self._deny(update)
        args = " ".join(ctx.args) if ctx.args else ""
        if not args:
            await update.message.reply_text("Usage: /genbot description")
            return
        msg = await update.message.reply_text("Scaffolding bot...")
        response = self._chat(self._uid(update), f"generate bot: {args}", "genbot")
        for chunk in self._split(response):
            await update.message.reply_text(chunk)
        await msg.delete()

    async def cmd_remember(self, update: Update, ctx: ContextTypes.DEFAULT_TYPE):
        if not self._allowed(update):
            return await self._deny(update)
        args = " ".join(ctx.args) if ctx.args else ""
        if not args or "=" not in args:
            await update.message.reply_text("Usage: /remember key = value")
            return
        key, value = args.split("=", 1)
        result = self.brain.run_tool("remember",
            user_id=str(self._uid(update)),
            key=key.strip(),
            value=value.strip()
        )
        await update.message.reply_text(str(result) if result else f"Stored: {key.strip()}")

    async def cmd_recall(self, update: Update, ctx: ContextTypes.DEFAULT_TYPE):
        if not self._allowed(update):
            return await self._deny(update)
        args = " ".join(ctx.args) if ctx.args else ""
        result = self.brain.run_tool("recall",
            user_id=str(self._uid(update)),
            query=args.strip()
        )
        await update.message.reply_text(str(result) if result else "Nothing found.")

    async def cmd_approve(self, update: Update, ctx: ContextTypes.DEFAULT_TYPE):
        if not self._allowed(update):
            return await self._deny(update)
        if not hasattr(self.brain, "github_approve"):
            await update.message.reply_text("GitHub editor not loaded.")
            return
        msg = await update.message.reply_text("Pushing change...")
        result = self.brain.github_approve()
        await msg.edit_text(str(result))

    async def cmd_reject(self, update: Update, ctx: ContextTypes.DEFAULT_TYPE):
        if not self._allowed(update):
            return await self._deny(update)
        if not hasattr(self.brain, "github_reject"):
            await update.message.reply_text("GitHub editor not loaded.")
            return
        result = self.brain.github_reject()
        await update.message.reply_text(str(result))

    async def cmd_diff(self, update: Update, ctx: ContextTypes.DEFAULT_TYPE):
        if not self._allowed(update):
            return await self._deny(update)
        if not hasattr(self.brain, "github_diff"):
            await update.message.reply_text("GitHub editor not loaded.")
            return
        result = self.brain.github_diff()
        for chunk in self._split(str(result)):
            await update.message.reply_text(chunk)

    async def cmd_rollback(self, update: Update, ctx: ContextTypes.DEFAULT_TYPE):
        if not self._allowed(update):
            return await self._deny(update)
        if not hasattr(self.brain, "github_rollback"):
            await update.message.reply_text("GitHub editor not loaded.")
            return
        result = self.brain.github_rollback()
        await update.message.reply_text(str(result))

    async def handle_message(self, update: Update, ctx: ContextTypes.DEFAULT_TYPE):
        if not self._allowed(update):
            return await self._deny(update)
        user_text = update.message.text.strip()
        await ctx.bot.send_chat_action(update.effective_chat.id, "typing")
        response = self._chat(self._uid(update), user_text)
        for chunk in self._split(response):
            await update.message.reply_text(chunk)

    def _split(self, text: str, limit: int = 4000) -> list[str]:
        if len(text) <= limit:
            return [text]
        chunks = []
        while text:
            chunks.append(text[:limit])
            text = text[limit:]
        return chunks

    async def run(self):
        app = Application.builder().token(self.token).build()
        app.add_handler(CommandHandler("start", self.cmd_start))
        app.add_handler(CommandHandler("help", self.cmd_help))
        app.add_handler(CommandHandler("model", self.cmd_model))
        app.add_handler(CommandHandler("clear", self.cmd_clear))
        app.add_handler(CommandHandler("status", self.cmd_status))
        app.add_handler(CommandHandler("pnl", self.cmd_pnl))
        app.add_handler(CommandHandler("arb", self.cmd_arb))
        app.add_handler(CommandHandler("genbot", self.cmd_genbot))
        app.add_handler(CommandHandler("remember", self.cmd_remember))
        app.add_handler(CommandHandler("recall", self.cmd_recall))
        app.add_handler(CommandHandler("approve", self.cmd_approve))
        app.add_handler(CommandHandler("reject", self.cmd_reject))
        app.add_handler(CommandHandler("diff", self.cmd_diff))
        app.add_handler(CommandHandler("rollback", self.cmd_rollback))
        app.add_handler(CallbackQueryHandler(self.cb_model, pattern="^model:"))
        app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, self.handle_message))
        log.info("Telegram bot polling...")
        async with app:
            await app.bot.delete_webhook(drop_pending_updates=True)
            await app.start()
            await app.updater.start_polling(
                drop_pending_updates=True,
                allowed_updates=Update.ALL_TYPES,
            )
            await asyncio.Event().wait()
