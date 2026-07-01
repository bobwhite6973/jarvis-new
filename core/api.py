"""
JARVIS Web API
FastAPI server — runs alongside Telegram bot.
Serves dashboard and exposes REST endpoints.
Handles both sync and async tools.
"""
import os
import logging
import asyncio
import inspect
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

        # Status
        if lower == "/status":
            result = await run_tool("bot_control", query="show status")
            if isinstance(result, str):
                return {"reply": result}
            if isinstance(result, dict) and "error" in result:
                return {"reply": f"❌ {result['error']}"}
            return {"reply": str(result)}

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
                result = await _brain.github_approve()
                return {"reply": result}
            return {"reply": "GitHub editor not loaded."}

        # GitHub reject
        if lower == "/reject":
            if hasattr(_brain, "github_reject"):
                result = await _brain.github_reject()
                return {"reply": result}
            return {"reply": "GitHub editor not loaded."}

        # GitHub diff
        if lower == "/diff":
            if hasattr(_brain, "github_diff"):
                result = await _brain.github_diff()
                return {"reply": result}
            return {"reply": "No pending change."}

        # GitHub rollback
        if lower == "/rollback":
            if hasattr(_brain, "github_rollback"):
                result = await _brain.github_rollback()
                return {"reply": result}
            return {"reply": "GitHub editor not loaded."}

        # Default — chat
        reply = _brain.chat(req.user_id, req.message)
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
    return await run_tool("bot_control", query="show status")


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
    return {
        "extensions": list(_brain.tools.keys()) if _brain else []
    }


@app.get("/api/github/repos")
async def github_repos():
    return await run_tool("list_repos")


@app.get("/api/github/files")
async def github_files(repo: str, path: str = ""):
    return await run_tool("list_files", repo=repo, path=path)


@app.get("/api/health")
async def health():
    return {
        "status": "ok",
        "extensions": list(_brain.tools.keys()) if _brain else []
    }
