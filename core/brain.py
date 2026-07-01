"""
JARVIS Brain — Multi-provider LLM router with native tool use + Auto-Learning.

Default: Groq (llama-3.1-8b-instant) — free, fast, high rate limits
Fallback: Claude (claude-sonnet-4-6) — if credits available
Optional: OpenAI (gpt-4o)

NEW: Auto-recall relevant memories before each response
     Auto-store interactions after each response
"""

import os
import json
import logging
import inspect
import anthropic
import requests
from openai import OpenAI
from datetime import datetime, timezone

log = logging.getLogger("brain")

PROVIDERS = ["groq", "claude", "openai"]

INTENT_PROVIDER = {
    "arb":     "groq",
    "pnl":     "groq",
    "status":  "groq",
    "genbot":  "claude",
    "default": "claude",
}

GROQ_MODELS = {
    "fast":  "llama-3.1-8b-instant",
    "smart": "llama-3.3-70b-versatile",
}

SYSTEM_PROMPT = (
    "You are JARVIS, Bob White's personal AI assistant and autonomous agent. "
    "You help with crypto trading, bot management, Solana DeFi analysis, "
    "coding, GitHub repo management, and general tasks. "
    "Be concise and direct. When you use tools, summarize the results clearly.\n\n"
    "GITHUB RULES:\n"
    "1. commit_file pushes to jarvis-changes, creates a PR, and auto-merges to main.\n"
    "2. Only commit files to extensions/ folder unless Bob says otherwise.\n"
    "3. When asked to write and commit code: write the code yourself, then call commit_file.\n"
    "4. Do NOT call generate_code — write the code directly.\n"
    "5. NEVER fabricate tool responses. Report actual results.\n"
    "6. You CAN call multiple different tools in one response."
)

EXCLUDE_FROM_CLAUDE_TOOLS = {
    "generate_code", "review_code", "fix_code", "improve_code", "explain_code",
    "browser_run", "audit_repo", "get_memory_context", "memory_store",
    "memory_recall", "record_tool_call",
}


def build_claude_tools(tools: dict) -> list:
    claude_tools = []
    for name, fn in tools.items():
        if name in EXCLUDE_FROM_CLAUDE_TOOLS:
            continue
        try:
            sig = inspect.signature(fn)
            properties = {}
            required = []
            for param_name, param in sig.parameters.items():
                if param_name in ("self", "brain"):
                    continue
                prop = {"type": "string", "description": f"{param_name} parameter"}
                if param.annotation != inspect.Parameter.empty:
                    ann = param.annotation
                    if ann == int:
                        prop["type"] = "integer"
                    elif ann == float:
                        prop["type"] = "number"
                    elif ann == bool:
                        prop["type"] = "boolean"
                properties[param_name] = prop
                if param.default == inspect.Parameter.empty:
                    required.append(param_name)
            claude_tools.append({
                "name": name,
                "description": (fn.__doc__ or f"Tool: {name}").strip()[:200],
                "input_schema": {
                    "type": "object",
                    "properties": properties,
                    "required": required,
                }
            })
        except Exception as e:
            log.warning(f"Could not build tool schema for {name}: {e}")
    return claude_tools


class Brain:
    def __init__(self):
        self.anthropic_client = anthropic.Anthropic(api_key=os.getenv("ANTHROPIC_API_KEY", ""))
        self.groq_key = os.getenv("GROQ_API_KEY")
        self.openai = OpenAI(api_key=os.getenv("OPENAI_API_KEY")) if os.getenv("OPENAI_API_KEY") else None

        self.user_provider: dict[int, str] = {}
        self.tools: dict[str, callable] = {}
        self.history: dict[int, list] = {}
        self.system_prompt = SYSTEM_PROMPT

        # ── Initialize persistent storage on startup ──
        try:
            from extensions import memory, learning
            memory._init_db()
            learning._init_db()
            log.info("Memory & Learning DBs initialized on startup.")
        except Exception as e:
            log.warning(f"DB init skipped: {e}")

    def register_tool(self, name: str, fn: callable):
        self.tools[name] = fn
        log.info(f"Tool registered: {name}")

    def register_extension(self, name: str, fn: callable):
        self.register_tool(name, fn)

    def run_tool(self, name: str, **kwargs):
        if name not in self.tools:
            return {"error": f"Unknown tool: {name}"}
        try:
            result = self.tools[name](**kwargs)
            return result
        except Exception as e:
            log.error(f"Tool {name} raised: {e}")
            return {"error": str(e)}

    def _auto_recall_context(self, user_id: int, message: str) -> str:
        """
        Auto-recall relevant memories & lessons before processing.
        Returns augmented context string to inject into system prompt.
        """
        context_parts = []
        
        try:
            from extensions import memory, learning
            
            # 1. Recall user memories (keywords from message)
            keywords = message.lower().split()[:5]  # first 5 words
            mem_results = memory.recall(user_id=user_id, query=" ".join(keywords))
            if mem_results.get("memories"):
                context_parts.append("📝 RELEVANT MEMORIES:")
                for m in mem_results["memories"][:3]:  # top 3
                    context_parts.append(f"  • [{m.get('category', 'general')}] {m.get('key')}: {m.get('value')}")
            
            # 2. Get recent lessons learned
            lesson_results = learning.get_lessons(limit=5)
            if lesson_results.get("lessons"):
                context_parts.append("\n🧠 RECENT LESSONS:")
                for les in lesson_results["lessons"]:
                    context_parts.append(f"  • [{les.get('category')}] {les.get('lesson')} (confidence: {les.get('confidence', 0):.2f})")
        
        except Exception as e:
            log.warning(f"Auto-recall failed: {e}")
        
        return "\n".join(context_parts) if context_parts else ""

    def _auto_store_interaction(self, user_id: int, message: str, response: str, tools_used: list):
        """
        Auto-store interaction to learning DB after response.
        """
        try:
            from extensions import learning
            
            # Categorize interaction
            category = "general"
            if any(word in message.lower() for word in ["bot", "trade", "pnl", "sol", "arb"]):
                category = "crypto"
            elif any(word in message.lower() for word in ["code", "commit", "github", "repo"]):
                category = "coding"
            elif any(word in message.lower() for word in ["remember", "recall", "memory"]):
                category = "memory"
            
            # Record interaction
            action = f"user_query: {message[:50]}..."
            outcome = "success" if "error" not in response.lower() else "partial"
            
            from extensions.db import get_conn
            conn = get_conn()
            try:
                cur = conn.cursor()
                now = datetime.now(timezone.utc).isoformat()
                cur.execute("""
                    INSERT INTO interactions (timestamp, category, action, outcome, context)
                    VALUES (?, ?, ?, ?, ?)
                """, (now, category, action, outcome, json.dumps({
                    "message": message[:200],
                    "response_preview": response[:200],
                    "tools_used": tools_used
                })))
                conn.commit()
                log.info(f"✅ Interaction stored: [{category}] {action}")
            finally:
                conn.close()
                
        except Exception as e:
            log.warning(f"Auto-store failed: {e}")

    def chat(self, user_id: int, message: str, provider: str = None) -> str:
        """
        Enhanced chat with auto-recall before and auto-store after.
        """
        # ── STEP 1: Auto-recall context ──
        recalled_context = self._auto_recall_context(user_id, message)
        
        # ── STEP 2: Inject context into system prompt if available ──
        original_prompt = self.system_prompt
        if recalled_context:
            self.system_prompt = f"{original_prompt}\n\n{recalled_context}"
            log.info(f"📚 Injected {len(recalled_context)} chars of context")
        
        # ── STEP 3: Process message normally ──
        provider = provider or self.user_provider.get(user_id) or INTENT_PROVIDER.get("default", "claude")
        history = self.history.setdefault(user_id, [])
        history.append({"role": "user", "content": message})

        if provider == "groq":
            response = self._chat_groq(user_id, history)
        elif provider == "openai":
            response = self._chat_openai(user_id, history)
        else:
            response = self._chat_claude(user_id, history)
        
        # ── STEP 4: Auto-store interaction ──
        tools_used = [name for name in self.tools.keys() if name.lower() in message.lower()]
        self._auto_store_interaction(user_id, message, response, tools_used)
        
        # ── STEP 5: Restore original prompt ──
        self.system_prompt = original_prompt
        
        return response

    def _chat_groq(self, user_id: int, history: list) -> str:
        if not self.groq_key:
            return self._chat_claude(user_id, history)
        try:
            headers = {
                "Authorization": f"Bearer {self.groq_key}",
                "Content-Type": "application/json",
            }
            messages = [{"role": "system", "content": self.system_prompt}] + history
            payload = {
                "model": GROQ_MODELS["fast"],
                "messages": messages,
                "max_tokens": 1024,
            }
            resp = requests.post(
                "https://api.groq.com/openai/v1/chat/completions",
                headers=headers,
                json=payload,
                timeout=30,
            )
            resp.raise_for_status()
            data = resp.json()
            reply = data["choices"][0]["message"]["content"]
            self.history[user_id].append({"role": "assistant", "content": reply})
            return reply
        except Exception as e:
            log.warning(f"Groq failed, falling back to Claude: {e}")
            return self._chat_claude(user_id, history)

    def _chat_openai(self, user_id: int, history: list) -> str:
        if not self.openai:
            return self._chat_claude(user_id, history)
        try:
            messages = [{"role": "system", "content": self.system_prompt}] + history
            resp = self.openai.chat.completions.create(
                model="gpt-4o",
                messages=messages,
                max_tokens=1024,
            )
            reply = resp.choices[0].message.content
            self.history[user_id].append({"role": "assistant", "content": reply})
            return reply
        except Exception as e:
            log.warning(f"OpenAI failed, falling back to Claude: {e}")
            return self._chat_claude(user_id, history)

    def _chat_claude(self, user_id: int, history: list) -> str:
        try:
            claude_tools = build_claude_tools(self.tools)
            messages = list(history)

            while True:
                kwargs = dict(
                    model="claude-sonnet-4-20250514",
                    max_tokens=4096,
                    system=self.system_prompt,
                    messages=messages,
                )
                if claude_tools:
                    kwargs["tools"] = claude_tools

                resp = self.anthropic_client.messages.create(**kwargs)

                # Collect all text and tool_use blocks
                tool_calls = [b for b in resp.content if b.type == "tool_use"]
                text_blocks = [b for b in resp.content if b.type == "text"]

                if not tool_calls:
                    reply = text_blocks[0].text if text_blocks else ""
                    self.history[user_id].append({"role": "assistant", "content": reply})
                    return reply

                # Append assistant message with all content blocks
                messages.append({"role": "assistant", "content": resp.content})

                # Execute all tool calls and collect results
                tool_results = []
                for tool_call in tool_calls:
                    tool_name = tool_call.name
                    tool_input = tool_call.input
                    log.info(f"Tool call: {tool_name}({tool_input})")
                    try:
                        result = self.run_tool(tool_name, **tool_input)
                    except Exception as e:
                        result = {"error": str(e)}
                    tool_results.append({
                        "type": "tool_result",
                        "tool_use_id": tool_call.id,
                        "content": json.dumps(result) if not isinstance(result, str) else result,
                    })

                messages.append({"role": "user", "content": tool_results})

        except Exception as e:
            log.error(f"Claude failed: {e}")
            return f"❌ Error: {e}"

    def set_provider(self, user_id: int, provider: str) -> str:
        if provider not in PROVIDERS:
            return f"Unknown provider: {provider}. Choose from {PROVIDERS}"
        self.user_provider[user_id] = provider
        return f"✅ Provider set to {provider} for user {user_id}"

    def clear_history(self, user_id: int) -> str:
        self.history[user_id] = []
        return f"✅ History cleared for user {user_id}"
