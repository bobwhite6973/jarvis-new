"""
JARVIS Web API
FastAPI server — runs alongside Telegram bot.
Serves dashboard and exposes REST endpoints.
Handles both sync and async tools.
Parses and executes <tool_call> blocks from LLM responses.
"""
import os
import json
import re
import logging
import inspect
import sqlite3
from pathlib import Path
from fastapi import FastAPI, HTTPException
from fastapi.responses import HTMLResponse
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

log = logging.getLogger("jarvis.api")

app = FastAPI(title="JARVIS API", docs_url=None, redoc_url=None)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

_brain = None


def set_brain(brain):
    global _brain
    _brain = brain


async def run_tool(name: str, **kwargs):
    """Run a tool — handles both sync and async tools."""
    if not _brain:
        return {"error": "Brain not initialized"}
    if name not in _brain.tools:
        return {"error": f"Tool not found: {name}"}
    try:
        result = _brain.tools[name](**kwargs)
        if inspect.iscoroutine(result):
            result = await result
        return result
    except Exception as e:
        log.error(f"Tool {name} error: {e}")
        return {"error": str(e)}


def get_bot_status_from_db() -> list:
    db = Path("data/memory.db")
    if not db.exists():
        return []
    with sqlite3.connect(db) as conn:
        rows = conn.execute(
            "SELECT bot_name, status, last_pnl, updated_at FROM bot_status"
        ).fetchall()
    return [{"name": r[0], "status": r[1], "pnl": r[2], "updated": r[3]} for r in rows]


def extract_tool_calls(text: str) -> list[dict]:
    """Extract all <tool_call> JSON blocks from LLM response."""
    calls = []
    # Match both <tool_call>...</tool_call> and raw JSON tool_call blocks
    patterns = [
        r'<tool_call>\s*(\{.*?\})\s*</tool_call>',
        r'```tool_call\s*(\{.*?\})\s*```',
    ]
    for pattern in patterns:
        for match in re.finditer(pattern, text, re.DOTALL):
            try:
                data = json.loads(match.group(1))
                calls.append(data)
            except json.JSONDecodeError:
                pass
    return calls


def strip_tool_calls(text: str) -> str:
    """Remove tool_call blocks from response text."""
    text = re.sub(r'<tool_call>.*?</tool_call>', '', text, flags=re.DOTALL)
    text = re.sub(r'```tool_call.*?```', '', text, flags=re.DOTALL)
    text = re.sub(r'<tool_response>.*?</tool_response>', '', text, flags=re.DOTALL)
    return text.strip()


async def execute_tool_calls(calls: list[dict]) -> list[str]:
    """Execute a list of tool calls and return formatted results."""
    results = []
    for call in calls:
        name = call.get("name") or call.get("tool")
        args = call.get("arguments") or call.get("parameters") or call.get("args") or {}
        if not name:
            continue
        log.info(f"Executing tool call: {name}({args})")
        result = await run_tool(name, **args)
        result_str = json.dumps(result, default=str) if isinstance(result, dict) else str(result)
        results.append(f"[{name}] → {result_str}")
    return results


async def chat_with_tools(user_id: int, message: str, max_rounds: int = 3) -> str:
    """
    Chat loop that:
    1. Sends message to brain
    2. Parses tool_call blocks from response
    3. Executes tools
    4. Feeds results back to brain
    5. Returns final response
    """
    history_addition = message

    for round_num in range(max_rounds):
        reply = _brain.chat(user_id, history_addition)

        tool_calls = extract_tool_calls(reply)

        if not tool_calls:
            # No tool calls — clean response and return
            return strip_tool_calls(reply)

        # Execute all tool calls
        tool_results = await execute_tool_calls(tool_calls)

        # Feed results back into brain
        tool_context = "\n".join(tool_results)
        history_addition = (
            f"Tool execution results:\n{tool_context}\n\n"
            f"Based on these results, provide a clear summary to the user."
        )

        log.info(f"Round {round_num+1}: executed {len(tool_calls)} tool(s), feeding results back")

    # Final pass — summarize
    return _brain.chat(user_id, history_addition)


@app.get("/", response_class=HTMLResponse)
async def dashboard():
    html_path = Path(__file__).parent / "dashboard.html"
    return HTMLResponse(content=html_path.read_text())


class ChatRequest(BaseModel):
    message: str
    user_id: int = 1


@app.post("/api/chat")
async def chat(req: ChatRequest):
    if not _brain:
        raise HTTPException(status_code=503, detail="Brain not initialized")
    try:
        lower = req.message.lower().strip()

        # Screenshot
        if lower.startswith("/screenshot "):
            url = req.message.split(" ", 1)[-1].strip()
            if url.startswith("http"):
                result = await run_tool("browser_screenshot", url=url)
                if isinstance(result, dict) and "error" in result:
                    return {"reply": f"❌ {result['error']}"}
                return {
                    "reply": f"📸 Screenshot of {url}",
                    "image_b64": result.get("screenshot_b64", ""),
                    "type": "screenshot"
                }

        # Full browser render
        if lower.startswith("/browser "):
            url = req.message.split(" ", 1)[-1].strip()
            if url.startswith("http"):
                result = await run_tool("browser_fetch", url=url)
                if isinstance(result, dict) and "error" in result:
                    return {"reply": f"❌ {result['error']}"}
                summary = _brain.chat(req.user_id, f"Summarize this webpage concisely:\n\n{result['content']}")
                return {"reply": f"🌐 **{url}**\n\n{summary}"}

        # Simple browse
        if lower.startswith("/browse "):
            url = req.message.split(" ", 1)[-1].strip()
            if url.startswith("http"):
                result = await run_tool("browse", url=url)
                if isinstance(result, dict) and "error" in result:
                    return {"reply": f"❌ {result['error']}"}
                summary = _brain.chat(req.user_id, f"Summarize this webpage concisely:\n\n{result['content']}")
                return {"reply": f"🌐 **{url}**\n\n{summary}"}

        # Search
        if lower.startswith("/search "):
            query = req.message.split(" ", 1)[-1].strip()
            result = await run_tool("web_search", query=query)
            summary = _brain.chat(req.user_id, f"Summarize these search results for '{query}':\n\n{result}")
            return {"reply": summary}

        # SOL price
        if lower == "/sol":
            result = await run_tool("sol_price")
            if isinstance(result, dict) and "error" in result:
                return {"reply": f"❌ {result['error']}"}
            price = result.get("price") if isinstance(result, dict) else result
            return {"reply": f"◎ **SOL Price**: ${float(price):,.2f}"}

        # Arb scan
        if lower == "/arb":
            result = await run_tool("solana_market")
            if isinstance(result, dict) and "error" in result:
                return {"reply": f"❌ {result['error']}"}
            if isinstance(result, str):
                return {"reply": result}
            opps = result.get("opportunities", []) if isinstance(result, dict) else []
            if not opps:
                return {"reply": "No executable spreads found right now."}
            lines = ["**📈 Solana DEX Spreads**\n"]
            for o in opps[:8]:
                lines.append(f"**{o['token']}** | {o['buy_dex']} → {o['sell_dex']} | Net: {o.get('net_spread_pct',0):.2f}% | Est: ${o.get('est_profit_usd',0):.4f}")
            return {"reply": "\n".join(lines)}

        # Status — reads directly from SQLite
        if lower == "/status":
            bots = get_bot_status_from_db()
            if not bots:
                return {"reply": "No bots registered yet."}
            lines = ["**⚙️ Bot Status**\n"]
            for b in bots:
                icon = "🟢" if b["status"] == "running" else "🔴"
                pnl_str = f" | PnL: {b['pnl']:+.4f}" if b["pnl"] else ""
                lines.append(f"{icon} **{b['name']}** — {b['status']}{pnl_str}")
            return {"reply": "\n".join(lines)}

        # PnL
        if lower == "/pnl":
            result = await run_tool("pnl_report")
            if isinstance(result, dict) and "error" in result:
                return {"reply": f"❌ {result['error']}"}
            if isinstance(result, str):
                return {"reply": result}
            return {"reply": (
                f"**📊 P&L Report**\n\n"
                f"Today: {result.get('today_pnl','N/A')}\n"
                f"7d: {result.get('week_pnl','N/A')}\n"
                f"Trades: {result.get('trade_count','N/A')}\n"
                f"Win rate: {result.get('win_rate','N/A')}"
            )}

        # Recall
        if lower == "/recall" or lower.startswith("/recall "):
            query = req.message.split(" ", 1)[-1].strip() if " " in req.message else ""
            result = await run_tool("recall", user_id=req.user_id, query=query)
            if isinstance(result, str):
                return {"reply": result}
            memories = result.get("memories", []) if isinstance(result, dict) else []
            if not memories:
                return {"reply": "No memories found."}
            lines = ["**🧠 JARVIS Memory**\n"]
            for m in memories:
                lines.append(f"• **{m['key']}**: {m['value']}")
            return {"reply": "\n".join(lines)}

        # GitHub repos
        if lower in ["/github repos", "github repos"] or any(k in lower for k in ["list repos", "my repos", "list my repo", "show repos"]):
            result = await run_tool("list_repos")
            if isinstance(result, dict) and "error" in result:
                return {"reply": f"❌ {result['error']}"}
            lines = ["**📁 Your GitHub Repos**\n"]
            for r in result.get("repos", []):
                icon = "🔒" if r["private"] else "📂"
                desc = f" — {r['description']}" if r.get("description") else ""
                lines.append(f"{icon} **{r['name']}**{desc}")
            return {"reply": "\n".join(lines)}

        # GitHub approve
        if lower == "/approve":
            if hasattr(_brain, "github_approve"):
                result = _brain.github_approve()
                return {"reply": result}
            return {"reply": "GitHub editor not loaded."}

        # GitHub reject
        if lower == "/reject":
            if hasattr(_brain, "github_reject"):
                result = _brain.github_reject()
                return {"reply": result}
            return {"reply": "GitHub editor not loaded."}

        # GitHub diff
        if lower == "/diff":
            if hasattr(_brain, "github_diff"):
                result = _brain.github_diff()
                return {"reply": result}
            return {"reply": "No pending change."}

        # GitHub rollback
        if lower == "/rollback":
            if hasattr(_brain, "github_rollback"):
                result = _brain.github_rollback()
                return {"reply": result}
            return {"reply": "GitHub editor not loaded."}

        # Direct commit_file shortcut
        if lower.startswith("/commit "):
            # Format: /commit path/to/file.py | commit message
            parts = req.message[8:].split("|", 1)
            if len(parts) == 2:
                path = parts[0].strip()
                message = parts[1].strip()
                content_result = await run_tool("read_file", path=path)
                if isinstance(content_result, dict) and "content" in content_result:
                    result = await run_tool("commit_file",
                        repo="jarvis-new",
                        path=path,
                        content=content_result["content"],
                        message=message
                    )
                    return {"reply": str(result)}
            return {"reply": "Usage: /commit path/to/file.py | commit message"}

        # Default — chat with tool execution
        reply = await chat_with_tools(req.user_id, req.message)
        return {"reply": reply}

    except Exception as e:
        log.error(f"Chat error: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/sol")
async def sol_price():
    result = await run_tool("sol_price")
    if isinstance(result, dict) and "error" in result:
        raise HTTPException(status_code=500, detail=result["error"])
    return result


@app.get("/api/status")
async def bot_status():
    return {"bots": get_bot_status_from_db()}


@app.get("/api/arb")
async def arb():
    return await run_tool("solana_market")


@app.get("/api/memory")
async def get_memory(user_id: int = 1):
    return await run_tool("recall", user_id=user_id)


@app.delete("/api/memory/{key}")
async def delete_memory(key: str, user_id: int = 1):
    return await run_tool("forget", user_id=user_id, key=key)


@app.get("/api/search")
async def search(q: str):
    return await run_tool("web_search", query=q)


@app.get("/api/pnl")
async def pnl():
    return await run_tool("pnl_report")


@app.get("/api/extensions")
async def extensions():
    return {"extensions": list(_brain.tools.keys()) if _brain else []}


@app.get("/api/github/repos")
async def github_repos():
    return await run_tool("list_repos")


@app.get("/api/github/files")
async def github_files(repo: str, path: str = ""):
    return await run_tool("list_files", repo=repo, path=path)


@app.post("/api/commit")
async def commit_file_endpoint(repo: str, path: str, content: str, message: str):
    """Direct commit endpoint — bypasses chat, calls commit_file directly."""
    result = await run_tool("commit_file", repo=repo, path=path, content=content, message=message)
    return result


@app.get("/api/health")
async def health():
    return {
        "status": "ok",
        "extensions": list(_brain.tools.keys()) if _brain else []
    }
