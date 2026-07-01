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
import io
from pathlib import Path
from fastapi import FastAPI, HTTPException, UploadFile, File
from fastapi.responses import HTMLResponse, StreamingResponse
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
            return strip_tool_calls(reply)

        tool_results = await execute_tool_calls(tool_calls)

        tool_context = "\n".join(tool_results)
        history_addition = f"Tool results:\n{tool_context}\n\nPlease provide your final response based on these results."

    return strip_tool_calls(reply)


# ── Request models ──────────────────────────────────────────────
class ChatRequest(BaseModel):
    message: str
    user_id: int = 1


class SpeakRequest(BaseModel):
    text: str


# ── Voice endpoints ─────────────────────────────────────────────

@app.post("/api/speak")
async def api_speak(req: SpeakRequest):
    """Convert text to MP3 audio using ElevenLabs Adam voice."""
    try:
        from extensions.voice import speak
        audio_bytes = speak(req.text)
        return StreamingResponse(
            iter([audio_bytes]),
            media_type="audio/mpeg",
            headers={"Content-Disposition": "inline; filename=response.mp3"}
        )
    except Exception as e:
        log.error(f"TTS error: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/api/transcribe")
async def api_transcribe(file: UploadFile = File(...)):
    """Transcribe uploaded audio file using Groq Whisper."""
    try:
        from extensions.voice import transcribe
        audio_bytes = await file.read()
        text = transcribe(audio_bytes, filename=file.filename or "voice.webm")
        return {"text": text}
    except Exception as e:
        log.error(f"Transcribe error: {e}")
        raise HTTPException(status_code=500, detail=str(e))


# ── Chat endpoint ────────────────────────────────────────────────

@app.post("/api/chat")
async def api_chat(req: ChatRequest):
    if not _brain:
        raise HTTPException(status_code=503, detail="Brain not ready")

    msg = req.message.strip()
    uid = req.user_id

    # Slash command routing
    if msg.startswith("/sol"):
        result = await run_tool("sol_price")
        return {"reply": str(result)}

    if msg.startswith("/arb"):
        result = await run_tool("solana_market")
        return {"reply": str(result)}

    if msg.startswith("/pnl"):
        result = await run_tool("pnl_report")
        return {"reply": str(result)}

    if msg.startswith("/status"):
        result = await run_tool("bot_control", query="status")
        return {"reply": str(result)}

    if msg.startswith("/search "):
        query = msg[8:].strip()
        result = await run_tool("web_search", query=query)
        return {"reply": str(result)}

    if msg.startswith("/screenshot "):
        url = msg[12:].strip()
        result = await run_tool("browser_screenshot", url=url)
        return {"reply": str(result)}

    if msg.startswith("/recall"):
        result = await run_tool("recall", user_id=uid, query=msg[7:].strip() or "")
        return {"reply": str(result)}

    if msg.startswith("/commit "):
        parts = msg[8:].strip().split(" ", 1)
        result = await run_tool("commit_file", path=parts[0], content=parts[1] if len(parts) > 1 else "")
        return {"reply": str(result)}

    # Default: route through brain with tool support
    reply = await chat_with_tools(uid, msg)
    return {"reply": reply}


# ── Status / utility endpoints ───────────────────────────────────

@app.get("/api/sol")
async def api_sol():
    result = await run_tool("sol_price")
    return result


@app.get("/api/arb")
async def api_arb():
    result = await run_tool("solana_market")
    return result


@app.get("/api/pnl")
async def api_pnl():
    result = await run_tool("pnl_report")
    return result


@app.get("/api/status")
async def api_status():
    bots = get_bot_status_from_db()
    return {"bots": bots, "count": len(bots)}


@app.get("/api/extensions")
async def api_extensions():
    if not _brain:
        return {"extensions": []}
    tools = list(_brain.tools.keys())
    return {"extensions": tools, "count": len(tools)}


@app.get("/api/memory")
async def api_memory(user_id: int = 1):
    result = await run_tool("recall", user_id=user_id, query="")
    return result

@app.get("/api/github")
async def github():
    result = await run_tool("list_repos")
    return result

@app.get("/api/search")
async def api_search(q: str = ""):
    if not q:
        return {"results": []}
    result = await run_tool("web_search", query=q)
    return result

# ── Voice endpoints

@app.get("/api/github")
async def api_github():
    result = await run_tool("list_repos")
    return result


# ── Dashboard ────────────────────────────────────────────────────

@app.get("/", response_class=HTMLResponse)
async def dashboard():
    html_path = Path(__file__).parent / "dashboard.html"
    if html_path.exists():
        return HTMLResponse(content=html_path.read_text())
    return HTMLResponse(content="<h1>JARVIS</h1><p>Dashboard not found.</p>")
