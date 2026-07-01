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


# ── Request model
class ChatRequest(BaseModel):
    message: str
    user_id: int = 1


class SpeakRequest(BaseModel):
    text: str


# ── Routes

@app.get("/", response_class=HTMLResponse)
async def dashboard():
    html_path = Path(__file__).parent / "dashboard.html"
    return HTMLResponse(content=html_path.read_text())


@app.post("/api/chat")
async def chat(req: ChatRequest):
    if not _brain:
        raise HTTPException(503, "Brain not ready")

    msg = req.message.strip()
    uid = req.user_id

    # Slash command shortcuts
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
        bots = get_bot_status_from_db()
        if not bots:
            return {"reply": "No bots registered."}
        lines = [f"• {b['name']}: {b['status']} | PnL: {b['pnl']}" for b in bots]
        return {"reply": "\n".join(lines)}

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

    if msg.startswith("/commit"):
        return {"reply": "Use the full commit syntax: /commit <repo> <path> <message>"}

    # Default: brain handles it
    try:
        reply = await chat_with_tools(uid, msg)
        return {"reply": reply}
    except Exception as e:
        log.error(f"Chat error: {e}")
        raise HTTPException(500, str(e))


@app.get("/api/sol")
async def sol():
    result = await run_tool("sol_price")
    return result


@app.get("/api/arb")
async def arb():
    result = await run_tool("solana_market")
    return result


@app.get("/api/pnl")
async def pnl():
    result = await run_tool("pnl_report")
    return result


@app.get("/api/status")
async def status():
    bots = get_bot_status_from_db()
    return {"bots": bots, "count": len(bots)}


@app.get("/api/memory")
async def memory(user_id: int = 1):
    result = await run_tool("recall", user_id=user_id, query="")
    return {"memories": result}


@app.get("/api/search")
async def search(q: str):
    result = await run_tool("web_search", query=q)
    return result


@app.get("/api/extensions")
async def extensions():
    if not _brain:
        return {"extensions": []}
    tools = list(_brain.tools.keys())
    return {"extensions": tools, "count": len(tools)}


@app.get("/api/github")
async def github():
    result = await run_tool("list_repos")
    return result


# ── Voice endpoints

@app.post("/api/speak")
async def speak_endpoint(req: SpeakRequest):
    """Convert text to speech using ElevenLabs Adam voice. Returns MP3 audio."""
    if not _brain:
        raise HTTPException(503, "Brain not ready")
    try:
        audio_bytes = await run_tool("speak", text=req.text)
        if isinstance(audio_bytes, dict) and "error" in audio_bytes:
            raise HTTPException(500, audio_bytes["error"])
        return StreamingResponse(
            io.BytesIO(audio_bytes),
            media_type="audio/mpeg",
            headers={"Content-Disposition": "inline; filename=speech.mp3"}
        )
    except HTTPException:
        raise
    except Exception as e:
        log.error(f"TTS error: {e}")
        raise HTTPException(500, f"TTS failed: {e}")


@app.post("/api/transcribe")
async def transcribe_endpoint(file: UploadFile = File(...)):
    """Transcribe uploaded audio file to text using Groq Whisper."""
    if not _brain:
        raise HTTPException(503, "Brain not ready")
    try:
        audio_bytes = await file.read()
        text = await run_tool("transcribe", audio_bytes=audio_bytes, filename=file.filename or "voice.ogg")
        if isinstance(text, dict) and "error" in text:
            raise HTTPException(500, text["error"])
        return {"text": str(text)}
    except HTTPException:
        raise
    except Exception as e:
        log.error(f"Transcription error: {e}")
        raise HTTPException(500, f"Transcription failed: {e}")
