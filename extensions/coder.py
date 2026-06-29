"""
Extension: coder
Gives JARVIS coding capabilities — generate, review, fix, improve code.
Always uses Claude for code quality.
Remembers user's stack and coding context via memory extension.
"""
import logging
from pathlib import Path

log = logging.getLogger("jarvis.coder")

CODE_SYSTEM = (
    "You are JARVIS, an expert coding assistant for Bob White. "
    "Bob works with Python, Node.js, Solana/Web3, Telegram bots, and crypto trading systems. "
    "He deploys to Render and Railway. He works from iOS/Chromebook so keep setup simple. "
    "When writing code: be concise, include error handling, add brief comments on complex parts. "
    "When reviewing code: be direct, flag real issues only, suggest concrete fixes. "
    "Always output clean, production-ready code."
)


def generate_code(brain, user_id: int, description: str) -> str:
    mem_context = brain.run_tool("get_memory_context", user_id=user_id)
    prompt = f"{mem_context}\n\n" if mem_context and isinstance(mem_context, str) else ""
    prompt += f"Write code for the following:\n\n{description}\n\nReturn only the code with brief comments. No explanations outside the code."
    old_prompt = brain.system_prompt
    brain.system_prompt = CODE_SYSTEM
    result = brain._call_claude([{"role": "user", "content": prompt}])
    brain.system_prompt = old_prompt
    return result


def review_code(brain, user_id: int, code: str) -> str:
    prompt = (
        f"Review this code and give direct, actionable feedback:\n\n"
        f"```\n{code}\n```\n\n"
        f"Format: list real issues with line references, then suggest fixes. Be concise."
    )
    old_prompt = brain.system_prompt
    brain.system_prompt = CODE_SYSTEM
    result = brain._call_claude([{"role": "user", "content": prompt}])
    brain.system_prompt = old_prompt
    return result


def fix_code(brain, user_id: int, code: str, error: str) -> str:
    prompt = (
        f"Fix this code:\n\n```\n{code}\n```\n\n"
        f"Error:\n{error}\n\n"
        f"Return the fixed code only with a one-line comment explaining what you changed."
    )
    old_prompt = brain.system_prompt
    brain.system_prompt = CODE_SYSTEM
    result = brain._call_claude([{"role": "user", "content": prompt}])
    brain.system_prompt = old_prompt
    return result


def improve_code(brain, user_id: int, code: str, goal: str = "") -> str:
    goal_text = f"Goal: {goal}\n\n" if goal else ""
    prompt = (
        f"Improve this code:\n\n```\n{code}\n```\n\n"
        f"{goal_text}"
        f"Focus on: performance, error handling, readability. "
        f"Return improved code with comments on what changed."
    )
    old_prompt = brain.system_prompt
    brain.system_prompt = CODE_SYSTEM
    result = brain._call_claude([{"role": "user", "content": prompt}])
    brain.system_prompt = old_prompt
    return result


def explain_code(brain, user_id: int, code: str) -> str:
    prompt = (
        f"Explain this code clearly and concisely:\n\n```\n{code}\n```\n\n"
        f"Cover: what it does, how it works, any gotchas."
    )
    old_prompt = brain.system_prompt
    brain.system_prompt = CODE_SYSTEM
    result = brain._call_claude([{"role": "user", "content": prompt}])
    brain.system_prompt = old_prompt
    return result
"""
Extension: sol_price
Fetches live SOL price from Jupiter Price API v2.
"""
import logging
import requests

log = logging.getLogger("jarvis.sol_price")

SOL_MINT = "So11111111111111111111111111111111111111112"


def get_sol_price() -> dict:
    try:
        resp = requests.get(
            f"https://api.jup.ag/price/v2?ids={SOL_MINT}",
            timeout=10
        )
        resp.raise_for_status()
        data = resp.json()
        price = float(data["data"][SOL_MINT]["price"])
        return {"price": price, "symbol": "SOL"}
    except Exception as e:
        log.error(f"SOL price fetch failed: {e}")
        return {"error": str(e)}


def register(brain):
    brain.register_tool("sol_price", get_sol_price)
    log.info("sol_price extension registered")

def register(brain):
    brain.register_tool("generate_code", lambda user_id, description: generate_code(brain, user_id, description))
    brain.register_tool("review_code",   lambda user_id, code: review_code(brain, user_id, code))
    brain.register_tool("fix_code",      lambda user_id, code, error: fix_code(brain, user_id, code, error))
    brain.register_tool("improve_code",  lambda user_id, code, goal="": improve_code(brain, user_id, code, goal))
    brain.register_tool("explain_code",  lambda user_id, code: explain_code(brain, user_id, code))
    log.info("coder extension registered")
