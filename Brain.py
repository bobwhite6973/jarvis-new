"""
Brain - Multi-LLM reasoning core with SQLite conversation memory
Providers: Groq (default), Claude (fallback), OpenAI (optional)
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

INTENT_PROVIDER_MAP = {
    "bot_generator":  "groq",
    "solana_market":  "groq",
    "pnl_report":     "groq",
    "bot_control":    "groq",
    "default":        "groq",
}

SYSTEM_PROMPT = """You are JARVIS, an advanced AI assistant built specifically for Bob — a crypto trader, bot developer, and full-stack builder working across Sol
