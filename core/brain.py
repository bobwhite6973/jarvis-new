"""
JARVIS Brain — Multi-provider LLM router.

Default: Claude (claude-sonnet-4-6)
Fast data queries: Groq (llama-3.3-70b-versatile)
Optional third: OpenAI (gpt-4o)

Override with /model in Telegram.
Fallback chain: if provider 1 fails, tries 2, then 3.
"""

import os
import json
import logging
import anthropic
import requests
from openai import OpenAI

log = logging.getLogger("brain")

PROVIDERS = ["claude", "groq", "openai"]

# Intent → preferred provider mapping
INTENT_PROVIDER = {
    "arb":      "groq",    # fast, low-latency data
    "pnl":      "groq",
    "status":   "groq",
    "genbot":   "claude",  # code quality
    "default":  "claude",
}

GROQ_MODELS = {
    "fast": "llama-3.1-8b-instant",
    "smart": "llama-3.3-70b-versatile",
}


class Brain:
    def __init__(self):
        self.anthropic = anthropic.Anthropic(api_key=os.getenv("ANTHROPIC_API_KEY"))
        self.groq_key  = os.getenv("GROQ_API_KEY")
        self.openai    = OpenAI(api_key=os.getenv("OPENAI_API_KEY")) if os.getenv("OPENAI_API_KEY") else None

        # active provider per user (telegram user_id -> provider name)
        self.user_provider: dict[int, str] = {}

        # extensions register tools here
        self.tools: dict[str, callable] = {}

        # conversation history per user
        self.history: dict[int, list] = {}

        self.system_prompt = (
            "You are JARVIS, Bob White's AI assistant. "
            "You help with crypto trading, bot management, Solana DeFi analysis, "
            "and general tasks. Be concise and direct. "
            "When you have tool results in context, summarize them clearly."
        )

    # ── Extension API ──────────────────────────────────────────────────────────

    def register_tool(self, name: str, fn: callable):
        self.tools[name] = fn
        log.info(f"Tool registered: {name}")
        
        def register_extension(self, name: str, fn: callable):
    """Alias for register_tool — used by extensions that call register_extension."""
    self.register_tool(name, fn)

    def run_tool(self, name: str, **kwargs):
        if name not in self.tools:
            return {"error": f"Unknown tool: {name}"}
        try:
            return self.tools[name](**kwargs)
        except Exception as e:
            log.error(f"Tool {name} error: {e}")
            return {"error": str(e)}

    # ── Provider selection ─────────────────────────────────────────────────────

    def resolve_provider(self, user_id: int, intent: str = "default") -> str:
        if user_id in self.user_provider:
            return self.user_provider[user_id]
        return INTENT_PROVIDER.get(intent, "claude")

    def set_provider(self, user_id: int, provider: str):
        if provider not in PROVIDERS:
            raise ValueError(f"Unknown provider: {provider}")
        self.user_provider[user_id] = provider

    # ── Chat ───────────────────────────────────────────────────────────────────

    def chat(self, user_id: int, message: str, intent: str = "default") -> str:
        provider = self.resolve_provider(user_id, intent)
        history  = self.history.setdefault(user_id, [])
        history.append({"role": "user", "content": message})

        # Try preferred provider, then fallback chain
        order = [provider] + [p for p in PROVIDERS if p != provider]
        for p in order:
            try:
                reply = self._call(p, history)
                history.append({"role": "assistant", "content": reply})
                if len(history) > 40:  # keep last 20 turns
                    self.history[user_id] = history[-40:]
                return reply
            except Exception as e:
                log.warning(f"Provider {p} failed: {e}")

        return "⚠️ All providers failed. Check API keys."

    def _call(self, provider: str, history: list) -> str:
        if provider == "claude":
            return self._call_claude(history)
        elif provider == "groq":
            return self._call_groq(history)
        elif provider == "openai":
            return self._call_openai(history)
        raise ValueError(f"Unknown provider: {provider}")

    def _call_claude(self, history: list) -> str:
        resp = self.anthropic.messages.create(
            model="claude-sonnet-4-6",
            max_tokens=2048,
            system=self.system_prompt,
            messages=history,
        )
        return resp.content[0].text

    def _call_groq(self, history: list) -> str:
        if not self.groq_key:
            raise RuntimeError("GROQ_API_KEY not set")
        resp = requests.post(
            "https://api.groq.com/openai/v1/chat/completions",
            headers={"Authorization": f"Bearer {self.groq_key}"},
            json={
                "model": GROQ_MODELS["smart"],
                "messages": [{"role": "system", "content": self.system_prompt}] + history,
                "max_tokens": 2048,
            },
            timeout=30,
        )
        resp.raise_for_status()
        return resp.json()["choices"][0]["message"]["content"]

    def _call_openai(self, history: list) -> str:
        if not self.openai:
            raise RuntimeError("OPENAI_API_KEY not set")
        resp = self.openai.chat.completions.create(
            model="gpt-4o",
            messages=[{"role": "system", "content": self.system_prompt}] + history,
            max_tokens=2048,
        )
        return resp.choices[0].message.content

    def clear_history(self, user_id: int):
        self.history.pop(user_id, None)
