"""
Extension: voice
Transcription: Groq Whisper (fast, free tier)
TTS: OpenAI TTS (alloy voice — clear and neutral)

transcribe(audio_bytes) -> str
speak(text) -> bytes  (OGG/opus for Telegram voice notes)
"""

import os
import io
import logging
import requests

log = logging.getLogger("voice")

GROQ_KEY   = os.getenv("GROQ_API_KEY", "")
OPENAI_KEY = os.getenv("OPENAI_API_KEY", "")

# OpenAI TTS voice — "onyx" is the closest to a JARVIS baritone
TTS_VOICE = os.getenv("JARVIS_TTS_VOICE", "onyx")
TTS_MODEL = "tts-1"

GROQ_TRANSCRIBE_URL = "https://api.groq.com/openai/v1/audio/transcriptions"
OPENAI_TTS_URL      = "https://api.openai.com/v1/audio/speech"


def transcribe(audio_bytes: bytes, filename: str = "voice.ogg") -> str:
    """
    Send audio bytes to Groq Whisper and return transcript text.
    Accepts OGG (Telegram default), MP3, WAV, M4A.
    """
    if not GROQ_KEY:
        raise RuntimeError("GROQ_API_KEY not set — cannot transcribe")

    resp = requests.post(
        GROQ_TRANSCRIBE_URL,
        headers={"Authorization": f"Bearer {GROQ_KEY}"},
        files={"file": (filename, io.BytesIO(audio_bytes), "audio/ogg")},
        data={"model": "whisper-large-v3", "response_format": "text"},
        timeout=30,
    )
    resp.raise_for_status()
    return resp.text.strip()


def speak(text: str) -> bytes:
    """
    Convert text to speech via OpenAI TTS.
    Returns raw MP3 bytes — Telegram accepts this as a voice note.
    """
    if not OPENAI_KEY:
        raise RuntimeError("OPENAI_API_KEY not set — cannot speak")

    # Telegram voice notes max ~1 min; chunk if very long
    # OpenAI TTS handles up to 4096 chars per call
    if len(text) > 4096:
        text = text[:4090] + "..."

    resp = requests.post(
        OPENAI_TTS_URL,
        headers={
            "Authorization": f"Bearer {OPENAI_KEY}",
            "Content-Type": "application/json",
        },
        json={
            "model": TTS_MODEL,
            "voice": TTS_VOICE,
            "input": text,
            "response_format": "mp3",
        },
        timeout=30,
    )
    resp.raise_for_status()
    return resp.content


def register(brain):
    brain.register_tool("transcribe", transcribe)
    brain.register_tool("speak", speak)
    log.info(f"voice extension registered (TTS voice: {TTS_VOICE})")
