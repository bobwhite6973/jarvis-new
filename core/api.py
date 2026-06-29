"""
JARVIS Web API
FastAPI server — runs alongside Telegram bot.
Serves dashboard and exposes REST endpoints.
"""
import os
import logging
import sqlite3
from pathlib import Path
from fastapi import FastAPI, HTTPException
from fastapi.responses import HTMLResponse, FileResponse
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


# ── Dashboard ──────────────────────────────────────────────────────────────────

@app.get("/", response_class=HTMLResponse)
async def dashboard():
    html_path = Path(__file__).parent / "dashboard.html"
    return HTMLResponse(content=html_path.read_text())


# ── API endpoints ──────────────────────────────────────────────────────────────

class ChatRequest(BaseModel):
    message: str
    user_id: int = 0


@app.post("/api/chat")
async def chat(req: ChatRequest):
    if not _brain:
        raise HTTPException(status_code=503, detail="Brain not initialized")
    try:
        mem_context = _brain.run_tool("get_memory_context", user_id=req.user_id)
        message = req.message
        if mem_context and isinstance(mem_context, str):
            message = f"{mem_context}\n\nUser message: {req.message}"
        reply = _brain.chat(req.user_id, message)
        return {"reply": reply}
    except Exception as e:
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
    result = _brain.run_tool("bot_status")
    return result


@app.get("/api/arb")
async def arb():
    if not _brain:
        raise HTTPException(status_code=503, detail="Brain not initialized")
    result = _brain.run_tool("solana_market")
    return result


@app.get("/api/memory")
async def get_memory(user_id: int = 0):
    if not _brain:
        raise HTTPException(status_code=503, detail="Brain not initialized")
    result = _brain.run_tool("recall", user_id=user_id)
    return result


@app.delete("/api/memory/{key}")
async def delete_memory(key: str, user_id: int = 0):
    if not _brain:
        raise HTTPException(status_code=503, detail="Brain not initialized")
    result = _brain.run_tool("forget", user_id=user_id, key=key)
    return result


@app.get("/api/search")
async def search(q: str):
    if not _brain:
        raise HTTPException(status_code=503, detail="Brain not initialized")
    result = _brain.run_tool("web_search", query=q)
    return result


@app.get("/api/pnl")
async def pnl():
    if not _brain:
        raise HTTPException(status_code=503, detail="Brain not initialized")
    result = _brain.run_tool("pnl_report")
    return result


@app.get("/api/health")
async def health():
    return {"status": "ok", "extensions": list(_brain.tools.keys()) if _brain else []}
