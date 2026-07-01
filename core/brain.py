"""
JARVIS Brain — Multi-provider LLM router with native tool use.

Default: Groq (llama-3.1-8b-instant) — free, fast, high rate limits
Fallback: Claude (claude-sonnet-4-6) — if credits available
Optional: OpenAI (gpt-4o)
"""

import os
import json
import logging
import inspect
import anthropic
import requests
from openai import OpenAI

log = logging.getLogger("brain")

PROVIDERS = ["groq", "claude", "openai"]

INTENT_PROVIDER = {
    "arb":     "groq",
    "pnl":     "groq",
    "status":  "groq",
    "genbot":  "groq",
    "default": "groq",
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

    def register_tool(self, name: str, fn: callable):
        self.tools[name] = fn
        log.info(f"Tool registered: {name}")

    def register_extension(self, name: str, fn: callable):
        self.register_tool(name, fn)

    def run_tool(self, name: str, **kwargs):
        if name not in self.tools:
            return {"error": f"Unknown tool: {name}"}
        try:
            return self.tools[name](**kwargs)
        except Exception as e:
            log.error(f"Tool {name} error: {e}")
            return {"error": str(e)}

    def _execute_tool(self, name: str, tool_input: dict):
        if name not in self.tools:
            return {"error": f"Unknown tool: {name}"}
        try:
            result = self.tools[name](**tool_input)
            if inspect.iscoroutine(result):
                import asyncio
                import concurrent.futures
                try:
                    loop = asyncio.get_event_loop()
                    if loop.is_running():
                        with concurrent.futures.ThreadPoolExecutor() as pool:
                            future = pool.submit(asyncio.run, result)
                            result = future.result(timeout=30)
                    else:
                        result = loop.run_until_complete(result)
                except Exception as e:
                    return {"error": f"Async tool error: {e}"}
            return result
        except Exception as e:
            log.error(f"Tool {name} execution error: {e}")
            return {"error": str(e)}

    def resolve_provider(self, user_id: int, intent: str = "default") -> str:
        if user_id in self.user_provider:
            return self.user_provider[user_id]
        return INTENT_PROVIDER.get(intent, "groq")

    def set_provider(self, user_id: int, provider: str):
        if provider not in PROVIDERS:
            raise ValueError(f"Unknown provider: {provider}")
        self.user_provider[user_id] = provider

    def _available_providers(self) -> list[str]:
        available = []
        if self.groq_key:
            available.append("groq")
        if os.getenv("ANTHROPIC_API_KEY"):
            available.append("claude")
        if self.openai:
            available.append("openai")
        return available

    def chat(self, user_id: int, message: str, intent: str = "default") -> str:
        preferred = self.resolve_provider(user_id, intent)
        history = self.history.setdefault(user_id, [])
        history.append({"role": "user", "content": message})

        # Keep history short to avoid payload limits
        if len(history) > 10:
            self.history[user_id] = history[-10:]
            history = self.history[user_id]

        available = self._available_providers()
        if not available:
            return "No API keys configured. Add GROQ_API_KEY to Render environment."

        order = [preferred] + [p for p in PROVIDERS if p != preferred and p in available]
        order = [p for p in order if p in available]

        for p in order:
            try:
                reply = self._call(p, list(history))
                history.append({"role": "assistant", "content": reply})
                return reply
            except Exception as e:
                log.warning(f"Provider {p} failed: {e}")

        return "All providers failed. Check API keys in Render environment."

    def _call(self, provider: str, history: list) -> str:
        if provider == "groq":
            return self._call_groq(history)
        elif provider == "claude":
            return self._call_claude(history)
        elif provider == "openai":
            return self._call_openai(history)
        raise ValueError(f"Unknown provider: {provider}")

    def _call_groq(self, history: list) -> str:
        if not self.groq_key:
            raise RuntimeError("GROQ_API_KEY not set")
        tool_list = "\n".join(
            f"- {name}" for name in self.tools
            if name not in EXCLUDE_FROM_CLAUDE_TOOLS
        )
        groq_system = self.system_prompt + f"\n\nAvailable tools:\n{tool_list}"

        # Trim history content to avoid 413
        trimmed = []
        for msg in history[-6:]:  # Only last 6 messages
            content = msg["content"]
            if isinstance(content, str) and len(content) > 1000:
                content = content[:1000] + "...[truncated]"
            trimmed.append({"role": msg["role"], "content": content})

        resp = requests.post(
            "https://api.groq.com/openai/v1/chat/completions",
            headers={"Authorization": f"Bearer {self.groq_key}"},
            json={
                "model": GROQ_MODELS["fast"],
                "messages": [{"role": "system", "content": groq_system}] + trimmed,
                "max_tokens": 2048,
            },
            timeout=30,
        )
        resp.raise_for_status()
        return resp.json()["choices"][0]["message"]["content"]

    def _call_claude(self, history: list) -> str:
        claude_tools = build_claude_tools(self.tools)
        messages = list(history)
        max_rounds = 5
        tools_called = set()

        for round_num in range(max_rounds):
            kwargs = {
                "model": "claude-sonnet-4-6",
                "max_tokens": 4096,
                "system": self.system_prompt,
                "messages": messages,
            }
            if claude_tools:
                kwargs["tools"] = claude_tools

            resp = self.anthropic_client.messages.create(**kwargs)

            if resp.stop_reason == "end_turn":
                for block in resp.content:
                    if hasattr(block, "text"):
                        return block.text
                return "Done."

            elif resp.stop_reason == "tool_use":
                tool_results = []
                assistant_content = resp.content

                for block in resp.content:
                    if block.type == "tool_use":
                        tool_name = block.name
                        tool_input = block.input
                        tool_use_id = block.id

                        call_key = f"{tool_name}:{str(tool_input)[:100]}"
                        if call_key in tools_called:
                            result = {"error": f"Duplicate call blocked: {tool_name}"}
                        else:
                            tools_called.add(call_key)
                            log.info(f"Claude calling tool: {tool_name}({tool_input})")
                            result = self._execute_tool(tool_name, tool_input)

                        result_str = json.dumps(result, default=str) if isinstance(result, dict) else str(result)
                        tool_results.append({
                            "type": "tool_result",
                            "tool_use_id": tool_use_id,
                            "content": result_str,
                        })

                messages.append({"role": "assistant", "content": assistant_content})
                messages.append({"role": "user", "content": tool_results})

            else:
                for block in resp.content:
                    if hasattr(block, "text"):
                        return block.text
                return f"Stopped: {resp.stop_reason}"

        messages.append({"role": "user", "content": "Summarize what you did."})
        final = self.anthropic_client.messages.create(
            model="claude-sonnet-4-6",
            max_tokens=1024,
            system=self.system_prompt,
            messages=messages,
        )
        for block in final.content:
            if hasattr(block, "text"):
                return block.text
        return "Completed."

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
