"""
Telegram Bot - Mobile-first UI for JARVIS
Commands: /start /help /model /clear /status /pnl /arb /genbot
"""

import os
import logging
import asyncio
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    Application, CommandHandler, MessageHandler,
    CallbackQueryHandler, filters, ContextTypes
)
from core.brain import Brain, PROVIDERS

log = logging.getLogger("jarvis.telegram")


class TelegramBot:
    def __init__(self, brain: Brain):
        self.brain = brain
        self.token = os.environ["TELEGRAM_BOT_TOKEN"]
        raw = os.environ.get("ALLOWED_USER_IDS", "")
        self.allowed_ids = set(int(x.strip()) for x in raw.split(",") if x.strip())

    def _uid(self, update: Update) -> str:
        return str(update.effective_user.id)

    def _allowed(self, update: Update) -> bool:
        if not self.allowed_ids:
            return True
        return update.effective_user.id in self.allowed_ids

    async def _deny(self, update: Update):
        await update.message.reply_text("Unauthorized.")

    async def cmd_start(self, update: Update, ctx: ContextTypes.DEFAULT_TYPE):
        if not self._allowed(update):
            return await self._deny(update)
        name = update.effective_user.first_name
        available = self.brain.available_providers()
        provider = self.brain.get_user_provider(self._uid(update))
        await update.message.reply_text(
            f"JARVIS online, {name}.\n\nActive model: {PROVIDERS[provider]['label']}\nAvailable: {', '.join(available)}\n\nType anything to talk. Use /help for commands."
        )

    async def cmd_help(self, update: Update, ctx: ContextTypes.DEFAULT_TYPE):
        if not self._allowed(update):
            return await self._deny(update)
        await update.message.reply_text(
            "JARVIS Commands\n\n/model - switch LLM provider\n/clear - clear conversation history\n/status - all bot statuses\n/pnl - today P&L summary\n/arb - current Solana arb spreads\n/genbot - generate a trading bot from description"
        )

    async def cmd_model(self, update: Update, ctx: ContextTypes.DEFAULT_TYPE):
        if not self._allowed(update):
            return await self._deny(update)
        available = self.brain.available_providers()
        current = self.brain.get_user_provider(self._uid(update))
        buttons = []
        for p in available:
            label = PROVIDERS[p]["label"]
            tick = "OK " if p == current else ""
            buttons.append([InlineKeyboardButton(f"{tick}{label}", callback_data=f"model:{p}")])
        await update.message.reply_text("Choose your LLM provider:", reply_markup=InlineKeyboardMarkup(buttons))

    async def cb_model(self, update: Update, ctx: ContextTypes.DEFAULT_TYPE):
        query = update.callback_query
        await query.answer()
        provider = query.data.split(":")[1]
        uid = str(query.from_user.id)
        result = self.brain.set_user_provider(uid, provider)
        await query.edit_message_text(result)

    async def cmd_clear(self, update: Update, ctx: ContextTypes.DEFAULT_TYPE):
        if not self._allowed(update):
            return await self._deny(update)
        self.brain.clear_history(self._uid(update))
        await update.message.reply_text("Conversation history cleared.")

    async def cmd_status(self, update: Update, ctx: ContextTypes.DEFAULT_TYPE):
        if not self._allowed(update):
            return await self._deny(update)
        statuses = self.brain.get_all_bot_statuses()
        if not statuses:
            await update.message.reply_text("No bots registered yet.")
            return
        lines = ["Bot Status\n"]
        for b in statuses:
            icon = "ON" if b["status"] == "running" else "OFF"
            pnl = f"  PnL: {b['pnl']:+.4f} SOL" if b["pnl"] is not None else ""
            lines.append(f"{icon} {b['name']} - {b['status']}{pnl}")
        await update.message.reply_text("\n".join(lines))

    async def cmd_pnl(self, update: Update, ctx: ContextTypes.DEFAULT_TYPE):
        if not self._allowed(update):
            return await self._deny(update)
        msg = await update.message.reply_text("Fetching P&L...")
        response = await self.brain.think(self._uid(update), "show me today's PnL report")
        await msg.edit_text(response)

    async def cmd_arb(self, update: Update, ctx: ContextTypes.DEFAULT_TYPE):
        if not self._allowed(update):
            return await self._deny(update)
        msg = await update.message.reply_text("Scanning for arb spreads...")
        response = await self.brain.think(self._uid(update), "show current arbitrage spreads")
        await msg.edit_text(response)

    async def cmd_genbot(self, update: Update, ctx: ContextTypes.DEFAULT_TYPE):
        if not self._allowed(update):
            return await self._deny(update)
        args = " ".join(ctx.args) if ctx.args else ""
        if not args:
            await update.message.reply_text("Usage: /genbot description\nExample: /genbot Solana momentum bot using RSI on JUP/USDC")
            return
        msg = await update.message.reply_text("Scaffolding bot...")
        response = await self.brain.think(self._uid(update), f"generate bot: {args}")
        for chunk in self._split(response):
            await update.message.reply_text(chunk)
        await msg.delete()

    async def handle_message(self, update: Update, ctx: ContextTypes.DEFAULT_TYPE):
        if not self._allowed(update):
            return await self._deny(update)
        user_text = update.message.text.strip()
        await ctx.bot.send_chat_action(update.effective_chat.id, "typing")
        response = await self.brain.think(self._uid(update), user_text)
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
        app.add_handler(CallbackQueryHandler(self.cb_model, pattern="^model:"))
        app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, self.handle_message))
        log.info("Telegram bot polling...")
        async with app:
            await app.start()
            await app.updater.start_polling(drop_pending_updates=True)
            await asyncio.Event().wait()
