"""
Brain - Multi-LLM reasoning core with SQLite conversation memory
Providers: Claude (default), Groq (fast/fallback), OpenAI (optional)
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
    "claude": {
        "url": "https://api.anthropic.com/v1/messages",
        "model": "claude-sonnet-4-6",
        "env_key": "ANTHROPIC_API_KEY",
        "label": "Claude Sonnet 4.6",
    },
    "groq": {
        "url": "https://api.groq.com/openai/v1/chat/completions",
        "model": "llama-3.3-70b-versatile",
        "env_key": "GROQ_API_KEY",
        "label": "Groq LLaMA 3.3 70B",
    },
    "openai": {
        "url": "https://api.openai.com/v1/chat/completions",
        "model": "gpt-4o-mini",
        "env_key": "OPENAI_API_KEY",
