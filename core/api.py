"""
JARVIS Web API
FastAPI server — runs alongside Telegram bot.
Serves dashboard and exposes REST endpoints.
"""
import os
import logging
from pathlib import Path
from fastapi import FastAPI, HTTPException
from fastapi.responses import HTMLResponse
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

log = logging.getLogger("jarvis.api")

DB_PATH = Path("data/memory.db")

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
        mem_context = _brain.run_tool("get_memory_context", user_id=req.user_id)
        message = req.message
        if mem_context and isinstance(mem_context, str):
            message = f"{mem_context}\n\nUser message: {req.message}"

        lower = req.message.lower().strip()

        # Screenshot
        if lower.startswith("/screenshot "):
            url = req.message.split(" ", 1)[-1].strip()
            if url.startswith("http"):
                result = _brain.run_tool("browser_screenshot", url=url)
                if "error" in result:
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
                result = _brain.run_tool("browser_fetch", url=url)
                if "error" in result:
                    return {"reply": f"❌ {result['error']}"}
                summary = _brain.chat(req.user_id, f"Summarize this webpage concisely:\n\n{result['content']}")
                return {"reply": f"🌐 **{url}**\n\n{summary}"}

        # Simple browse
        if lower.startswith("/browse "):
            url = req.message.split(" ", 1)[-1].strip()
            if url.startswith("http"):
                result = _brain.run_tool("browse", url=url)
                if "error" in result:
                    return {"reply": f"❌ {result['error']}"}
                summary = _brain.chat(req.user_id, f"Summarize this webpage concisely:\n\n{result['content']}")
                return {"reply": f"🌐 **{url}**\n\n{summary}"}

        # Search
        if lower.startswith("/search "):
            query = req.message.split(" ", 1)[-1].strip()
            result = _brain.run_tool("web_search", query=query)
            summary = _brain.chat(req.user_id, f"Summarize these search results for '{query}':\n\n{result}")
            return {"reply": summary}

        # SOL price
        if lower == "/sol":
            result = _brain.run_tool("sol_price")
            if "error" in result:
                return {"reply": f"❌ {result['error']}"}
            return {"reply": f"◎ **SOL Price**: ${result['price']:,.2f}"}

        # Arb scan
        if lower == "/arb":
            result = _brain.run_tool("solana_market")
            if "error" in result:
                return {"reply": f"❌ {result['error']}"}
            opps = result.get("opportunities", [])
            if not opps:
                return {"reply": "No executable spreads found right now."}
            lines = ["**📈 Solana DEX Spreads**\n"]
            for o in opps[:8]:
                lines.append(f"**{o['token']}** | {o['buy_dex']} → {o['sell_dex']} | Net: {o.get('net_spread_pct',0):.2f}% | Est: ${o.get('est_profit_usd',0):.4f}")
            return {"reply": "\n".join(lines)}

        # Status
        if lower == "/status":
            result = _brain.run_tool("bot_status")
            if "error" in result:
                return {"reply": f"❌ {result['error']}"}
            bots = result.get("bots", [])
            if not bots:
                return {"reply": "No bots registered."}
            lines = ["**⚙️ Bot Status**\n"]
            for b in bots:
                icon = "🟢" if b.get("status") == "running" else "🔴"
                lines.append(f"{icon} **{b['name']}** — {b.get('status','unknown')}")
            return {"reply": "\n".join(lines)}

        # PnL
        if lower == "/pnl":
            result = _brain.run_tool("pnl_report")
            if "error" in result:
                return {"reply": f"❌ {result['error']}"}
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
            result = _brain.run_tool("recall", user_id=req.user_id, query=query)
            memories = result.get("memories", [])
            if not memories:
                return {"reply": "No memories found."}
            lines = ["**🧠 JARVIS Memory**\n"]
            for m in memories:
                lines.append(f"• **{m['key']}**: {m['value']}")
            return {"reply": "\n".join(lines)}

        # GitHub repos
        if lower == "/github repos":
            result = _brain.run_tool("list_repos")
            if "error" in result:
                return {"reply": f"❌ {result['error']}"}
            lines = ["**📁 Your Repos**\n"]
            for r in result.get("repos", []):
                icon = "🔒" if r["private"] else "📂"
                desc = f" — {r['description']}" if r.get("description") else ""
                lines.append(f"{icon} **{r['name']}**{desc}")
            return {"reply": "\n".join(lines)}

        # Default — chat
        reply = _brain.chat(req.user_id, message)
        return {"reply": reply}

    except Exception as e:
        log.error(f"Chat error: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/sol")
async def sol_price():
    if not _brain:
        raise HTTPException(status_code=503, detail="Brain not initialized")
    result = _brain.run_tool("sol_price")
    if "error" in result:
        raise HTTPException(status_code=500, detail=result["error"])
    return result


@app.get("/api/status")
async def bot_status():
    if not _brain:
        raise HTTPException(status_code=503, detail="Brain not initialized")
    return _brain.run_tool("bot_status")


@app.get("/api/arb")
async def arb():
    if not _brain:
        raise HTTPException(status_code=503, detail="Brain not initialized")
    return _brain.run_tool("solana_market")


@app.get("/api/memory")
async def get_memory(user_id: int = 1):
    if not _brain:
        raise HTTPException(status_code=503, detail="Brain not initialized")
    return _brain.run_tool("recall", user_id=user_id)


@app.delete("/api/memory/{key}")
async def delete_memory(key: str, user_id: int = 1):
    if not _brain:
        raise HTTPException(status_code=503, detail="Brain not initialized")
    return _brain.run_tool("forget", user_id=user_id, key=key)


@app.get("/api/search")
async def search(q: str):
    if not _brain:
        raise HTTPException(status_code=503, detail="Brain not initialized")
    return _brain.run_tool("web_search", query=q)


@app.get("/api/pnl")
async def pnl():
    if not _brain:
        raise HTTPException(status_code=503, detail="Brain not initialized")
    return _brain.run_tool("pnl_report")


@app.get("/api/health")
async def health():
    return {
        "status": "ok",
        "extensions": list(_brain.tools.keys()) if _brain else []
    }
