"""
JARVIS Brain — Multi-provider LLM router with native tool use.

Default: Claude (claude-sonnet-4-6) with native tool calling
Fast data queries: Groq (llama-3.3-70b-versatile)
Optional third: OpenAI (gpt-4o)

Claude uses native tool_use API — tools actually execute.
Groq/OpenAI use text-based tool calling as fallback.
"""

import os
import json
import logging
import inspect
import anthropic
import requests
from openai import OpenAI

log = logging.getLogger("brain")

PROVIDERS = ["claude", "groq", "openai"]

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
    "IMPORTANT RULES FOR GITHUB:\n"
    "1. commit_file pushes to 'jarvis-changes' branch — NOT main. Bob merges to main.\n"
    "2. Only commit files to extensions/ folder unless Bob explicitly says otherwise.\n"
    "3. Always syntax-check Python before committing — the tool does this automatically.\n"
    "4. When Bob asks you to write and push code, use generate_code then commit_file.\n"
    "5. NEVER fabricate tool responses. Report actual results."
)


def build_claude_tools(tools: dict) -> list:
    """
    Convert registered tools into Claude's native tool format.
    Inspects function signatures to build input schemas.
    """
    claude_tools = []
    for name, fn in tools.items():
        try:
            sig = inspect.signature(fn)
            properties = {}
            required = []
            for param_name, param in sig.parameters.items():
                if param_name in ("self", "brain"):
                    continue
                prop = {"type": "string", "description": f"{param_name} parameter"}
                # Try to infer type from annotation
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
        self.anthropic_client = anthropic.Anthropic(api_key=os.getenv("ANTHROPIC_API_KEY"))
        self.groq_key = os.getenv("GROQ_API_KEY")
        self.openai = OpenAI(api_key=os.getenv("OPENAI_API_KEY")) if os.getenv("OPENAI_API_KEY") else None

        self.user_provider: dict[int, str] = {}
        self.tools: dict[str, callable] = {}
        self.history: dict[int, list] = {}

        # Keep for Groq/OpenAI text-based tool awareness
        self.system_prompt = SYSTEM_PROMPT

    # ── Extension API ──────────────────────────────────────────────────────────

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
            log.error(f"Tool {name} error: {e}")
            return {"error": str(e)}

    def _execute_tool(self, name: str, tool_input: dict):
        """Execute a tool call from Claude's native tool use."""
        if name not in self.tools:
            return {"error": f"Unknown tool: {name}"}
        try:
            result = self.tools[name](**tool_input)
            # Handle coroutines — run them synchronously
            if inspect.iscoroutine(result):
                import asyncio
                try:
                    loop = asyncio.get_event_loop()
                    if loop.is_running():
                        import concurrent.futures
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
        history = self.history.setdefault(user_id, [])
        history.append({"role": "user", "content": message})

        order = [provider] + [p for p in PROVIDERS if p != provider]
        for p in order:
            try:
                reply = self._call(p, list(history))
                history.append({"role": "assistant", "content": reply})
                if len(history) > 40:
                    self.history[user_id] = history[-40:]
                return reply
            except Exception as e:
                log.warning(f"Provider {p} failed: {e}")

        return "All providers failed. Check API keys."

    def _call(self, provider: str, history: list) -> str:
        if provider == "claude":
            return self._call_claude(history)
        elif provider == "groq":
            return self._call_groq(history)
        elif provider == "openai":
            return self._call_openai(history)
        raise ValueError(f"Unknown provider: {provider}")

    def _call_claude(self, history: list) -> str:
        """
        Claude with native tool use.
        Runs a tool use loop until Claude returns a text response.
        """
        claude_tools = build_claude_tools(self.tools)
        messages = list(history)
        max_rounds = 5

        for round_num in range(max_rounds):
            kwargs = {
                "model": "claude-sonnet-4-6",
                "max_tokens": 4096,
                "system": SYSTEM_PROMPT,
                "messages": messages,
            }
            if claude_tools:
                kwargs["tools"] = claude_tools

            resp = self.anthropic_client.messages.create(**kwargs)

            # Check stop reason
            if resp.stop_reason == "end_turn":
                # Extract text response
                for block in resp.content:
                    if hasattr(block, "text"):
                        return block.text
                return "Done."

            elif resp.stop_reason == "tool_use":
                # Execute all tool calls
                tool_results = []
                assistant_content = resp.content

                for block in resp.content:
                    if block.type == "tool_use":
                        tool_name = block.name
                        tool_input = block.input
                        tool_use_id = block.id

                        log.info(f"Claude calling tool: {tool_name}({tool_input})")
                        result = self._execute_tool(tool_name, tool_input)
                        result_str = json.dumps(result, default=str) if isinstance(result, dict) else str(result)
                        log.info(f"Tool {tool_name} result: {result_str[:200]}")

                        tool_results.append({
                            "type": "tool_result",
                            "tool_use_id": tool_use_id,
                            "content": result_str,
                        })

                # Add assistant message with tool use blocks
                messages.append({"role": "assistant", "content": assistant_content})
                # Add tool results
                messages.append({"role": "user", "content": tool_results})

            else:
                # Unexpected stop reason — extract whatever text we have
                for block in resp.content:
                    if hasattr(block, "text"):
                        return block.text
                return f"Stopped: {resp.stop_reason}"

        return "Tool use loop exceeded max rounds."

    def _call_groq(self, history: list) -> str:
        if not self.groq_key:
            raise RuntimeError("GROQ_API_KEY not set")
        # Build tool-aware system prompt for Groq
        tool_list = "\n".join(f"- {name}({', '.join(inspect.signature(fn).parameters.keys())})"
                              for name, fn in self.tools.items()
                              if name not in ("self", "brain"))
        groq_system = SYSTEM_PROMPT + f"\n\nAvailable tools:\n{tool_list}"

        resp = requests.post(
            "https://api.groq.com/openai/v1/chat/completions",
            headers={"Authorization": f"Bearer {self.groq_key}"},
            json={
                "model": GROQ_MODELS["smart"],
                "messages": [{"role": "system", "content": groq_system}] + history,
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
            messages=[{"role": "system", "content": SYSTEM_PROMPT}] + history,
            max_tokens=2048,
        )
        return resp.choices[0].message.content

    def clear_history(self, user_id: int):
        self.history.pop(user_id, None)
