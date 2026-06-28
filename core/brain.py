"""
Brain - Multi-LLM reasoning core with SQLite conversation memory
Providers: Groq (default), Claude (fallback), OpenAI (optional)
Switch per-user or per-query via /model command or intent routing.
"""

import os
import sqlite3
import httpx
import logging
from datetime import datetime
from pathlib import Path

log = logging.getLogger("jarvis.brain")

DB_PATH = Path("data/memory.db")
MAX_HISTORY = 20

# ── Provider configs ──────────────────────────────────────────────────────────
PROVIDERS = {
    "groq": {
        "url": "https://api.groq.com/openai/v1/chat/completions",
        "model": "llama-3.3-70b-versatile",
        "env_key": "GROQ_API_KEY",
        "label": "Groq LLaMA 3.3 70B",
    },
    "claude": {
        "url": "https://api.anthropic.com/v1/messages",
        "model": "claude-sonnet-4-6",
        "env_key": "ANTHROPIC_API_KEY",
        "label": "Claude Sonnet 4.6",
    },
    "openai": {
        "url": "https://api.openai.com/v1/chat/completions",
        "model": "gpt-4o-mini",
        "env_key": "OPENAI_API_KEY",
        "label": "GPT-4o Mini",
    },
}

# Groq handles everything by default
INTENT_PROVIDER_MAP = {
    "bot_generator":  "groq",
    "solana_market":  "groq",
    "pnl_report":     "groq",
    "bot_control":    "groq",
    "default":        "groq",
}

SYSTEM_PROMPT = """You are JARVIS, an advanced AI assistant built specifically for Bob — a crypto trader, bot developer, and full-stack builder working across Solana, Ethereum, and EVM chains.

Your personality: Direct, efficient, technically sharp. No fluff. You know Bob's stack: Python, Node.js, Solana/Jupiter, Raydium, Orca, Meteora, Render, Railway, Vercel, Telegram bots.

Core capabilities:
- Answer crypto/DeFi/trading questions with precision
- Help debug and write code (Python, JS, Solana programs)
- Analyze DEX market data and arbitrage opportunities
- Manage and command trading bots via extensions
- Scaffold new bot code and deployment configs
- Route signals and alerts intelligently

Format: Keep responses concise. Use code blocks for code. No unnecessary caveats."""


class Brain:
    def __init__(self):
        self._init_db()
        self.extensions = {}
        self._user_provider: dict[str, str] = {}
        log.info("Brain initialized — default provider: Groq")

    def _init_db(self):
        DB_PATH.parent.mkdir(exist_ok=True)
        with sqlite3.connect(DB_PATH) as conn:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS conversations (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    user_id TEXT NOT NULL,
                    role TEXT NOT NULL,
                    content TEXT NOT NULL,
                    provider TEXT,
                    timestamp TEXT NOT NULL
                )
            """)
            conn.execute("""
                CREATE TABLE IF NOT EXISTS bot_status (
                    bot_name TEXT PRIMARY KEY,
                    status TEXT,
                    last_pnl REAL,
                    updated_at TEXT
                )
            """)
            conn.execute("""
                CREATE TABLE IF NOT EXISTS user_prefs (
                    user_id TEXT PRIMARY KEY,
                    preferred_provider TEXT DEFAULT 'groq'
                )
            """)
            conn.commit()

    def get_history(self, user_id: str) -> list:
        with sqlite3.connect(DB_PATH) as conn:
            rows = conn.execute(
                "SELECT role, content FROM conversations WHERE user_id=? ORDER BY id DESC LIMIT ?",
                (user_id, MAX_HISTORY)
            ).fetchall()
        return [{"role": r, "content": c} for r, c in reversed(rows)]

    def save_message(self, user_id: str, role: str, content: str, provider: str = None):
        with sqlite3.connect(DB_PATH) as conn:
            conn.execute(
                "INSERT INTO conversations (user_id,role,content,provider,timestamp) VALUES(?,?,?,?,?)",
                (user_id, role, content, provider, datetime.utcnow().isoformat())
            )
            conn.commit()

    def clear_history(self, user_id: str):
        with sqlite3.connect(DB_PATH) as conn:
            conn.execute("DELETE FROM conversations WHERE user_id=?", (user_id,))
            conn.commit()

    def set_user_provider(self, user_id: str, provider: str) -> str:
        if provider not in PROVIDERS:
            return f"❌ Unknown provider. Choose: {', '.join(PROVIDERS.keys())}"
        self._user_provider[user_id] = provider
        with sqlite3.connect(DB_PATH) as conn:
            conn.execute(
                "INSERT OR REPLACE INTO user_prefs(user_id,preferred_provider) VALUES(?,?)",
                (user_id, provider)
            )
            conn.commit()
        label = PROVIDERS[provider]["label"]
        return f"✅ Switched to **{label}**"

    def get_user_provider(self, user_id: str) -> str:
        if user_id in self._user_provider:
            return self._user_provider[user_id]
        with sqlite3.connect(DB_PATH) as conn:
            row = conn.execute(
                "SELECT preferred_provider FROM user_prefs WHERE user_id=?", (user_id,)
            ).fetchone()
        provider = row[0] if row else "groq"
        self._user_provider[user_id] = provider
        return provider

    def available_providers(self) -> list[str]:
        return [
            name for name, cfg in PROVIDERS.items()
            if os.environ.get(cfg["env_key"])
        ]

    def register_extension(self, name: str, handler):
        self.extensions[name] = handler
        log.info(f"Extension registered: {name}")

    def _detect_intent(self, query: str) -> str | None:
        q = query.lower()
        if any(k in q for k in ["spread", "arb", "arbitrage", "price diff"]):
            return "solana_market"
        if any(k in q for k in ["pnl", "profit", "loss", "today's", "performance"]):
            return "pnl_report"
        if any(k in q for k in ["pause bot", "stop bot", "start bot", "resume bot"]):
            return "bot_control"
        if any(k in q for k in ["generate bot", "scaffold", "create bot", "build bot"]):
            return "bot_generator"
        return None

    async def think(self, user_id: str, query: str) -> str:
        intent = self._detect_intent(query)
        enriched_query = query
        save_as = query

        if intent and intent in self.extensions:
            try:
                ext_result = await self.extensions[intent](query)
                enriched_query = f"[Tool result: {intent}]\n{ext_result}\n\nUser asked: {query}"
            except Exception as e:
                log.error(f"Extension {intent} failed: {e}")
                intent = None

        user_pref = self.get_user_provider(user_id)
        provider_order = [user_pref, "groq", "claude", "openai"]

        available = self.available_providers()
        ordered = [p for p in dict.fromkeys(provider_order) if p in available]
        if not ordered:
            return "❌ No LLM API keys configured. Set GROQ_API_KEY at minimum."

        last_error = ""
        for provider in ordered:
            try:
                answer = await self._call_provider(provider, user_id, enriched_query)
                self.save_message(user_id, "user", save_as, provider)
                self.save_message(user_id, "assistant", answer, provider)
                if len(ordered) > 1 and provider != ordered[0]:
                    answer = f"_(via {PROVIDERS[provider]['label']} fallback)_\n\n{answer}"
                return answer
            except Exception as e:
                last_error = str(e)
                log.warning(f"Provider {provider} failed: {e} — trying next")
                continue

        return f"❌ All providers failed. Last error: {last_error}"

    async def _call_provider(self, provider: str, user_id: str, query: str) -> str:
        cfg = PROVIDERS[provider]
        api_key = os.environ.get(cfg["env_key"])
        if not api_key:
            raise ValueError(f"No API key for {provider}")
        history = self.get_history(user_id)
        if provider == "claude":
            return await self._call_claude(api_key, cfg, history, query)
        else:
            return await self._call_openai_compat(api_key, cfg, history, query)

    async def _call_claude(self, api_key: str, cfg: dict, history: list, query: str) -> str:
        messages = history + [{"role": "user", "content": query}]
        async with httpx.AsyncClient(timeout=30) as client:
            resp = await client.post(
                cfg["url"],
                headers={
                    "x-api-key": api_key,
                    "anthropic-version": "2023-06-01",
                    "content-type": "application/json",
                },
                json={
                    "model": cfg["model"],
                    "max_tokens": 1024,
                    "system": SYSTEM_PROMPT,
                    "messages": messages,
                }
            )
            resp.raise_for_status()
            return resp.json()["content"][0]["text"]

    async def _call_openai_compat(self, api_key: str, cfg: dict, history: list, query: str) -> str:
        messages = [{"role": "system", "content": SYSTEM_PROMPT}]
        messages += history
        messages.append({"role": "user", "content": query})
        async with httpx.AsyncClient(timeout=30) as client:
            resp = await client.post(
                cfg["url"],
                headers={
                    "Authorization": f"Bearer {api_key}",
                    "content-type": "application/json",
                },
                json={
                    "model": cfg["model"],
                    "max_tokens": 1024,
                    "messages": messages,
                }
            )
            resp.raise_for_status()
            return resp.json()["choices"][0]["message"]["content"]

    def update_bot_status(self, bot_name: str, status: str, pnl: float = None):
        with sqlite3.connect(DB_PATH) as conn:
            conn.execute(
                "INSERT OR REPLACE INTO bot_status(bot_name,status,last_pnl,updated_at) VALUES(?,?,?,?)",
                (bot_name, status, pnl, datetime.utcnow().isoformat())
            )
            conn.commit()

    def get_all_bot_statuses(self) -> list:
        with sqlite3.connect(DB_PATH) as conn:
            rows = conn.execute(
                "SELECT bot_name, status, last_pnl, updated_at FROM bot_status"
            ).fetchall()
        return [{"name": r[0], "status": r[1], "pnl": r[2], "updated": r[3]} for r in rows]
