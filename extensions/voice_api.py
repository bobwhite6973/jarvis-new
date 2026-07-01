"""
Voice API endpoints — mounts /api/transcribe and /api/speak onto the JARVIS FastAPI app.
Transcribe: POST /api/transcribe  (multipart: file=audio)  -> {"text": "..."}
Speak:      POST /api/speak       (JSON: {"text": "..."})   -> MP3 audio stream
"""
import logging
from fastapi import UploadFile, File, HTTPException
from fastapi.responses import Response
from pydantic import BaseModel

log = logging.getLogger("voice_api")


class SpeakRequest(BaseModel):
    text: str


def register(brain):
    """Register voice HTTP endpoints onto the shared FastAPI app."""
    try:
        from core.api import app
    except ImportError:
        log.error("voice_api: could not import FastAPI app")
        return

    @app.post("/api/transcribe")
    async def transcribe_endpoint(file: UploadFile = File(...)):
        """Receive audio file, return transcribed text."""
        if "transcribe" not in brain.tools:
            raise HTTPException(503, "transcribe tool not registered")
        try:
            audio_bytes = await file.read()
            filename = file.filename or "voice.ogg"
            text = brain.tools["transcribe"](audio_bytes, filename)
            log.info(f"Transcribed {len(audio_bytes)} bytes -> {len(text)} chars")
            return {"text": text}
        except Exception as e:
            log.error(f"Transcribe error: {e}")
            raise HTTPException(500, str(e))

    @app.post("/api/speak")
    async def speak_endpoint(req: SpeakRequest):
        """Receive text, return MP3 audio bytes."""
        if "speak" not in brain.tools:
            raise HTTPException(503, "speak tool not registered")
        try:
            audio_bytes = brain.tools["speak"](req.text)
            log.info(f"Spoke {len(req.text)} chars -> {len(audio_bytes)} bytes MP3")
            return Response(
                content=audio_bytes,
                media_type="audio/mpeg",
                headers={"Content-Disposition": "inline; filename=jarvis.mp3"}
            )
        except Exception as e:
            log.error(f"Speak error: {e}")
            raise HTTPException(500, str(e))

    log.info("voice_api: /api/transcribe and /api/speak registered")
