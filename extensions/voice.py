"""
Extension: voice
Transcription: Groq Whisper (fast, free tier)
TTS: ElevenLabs (Adam voice — deep, confident, natural)
transcribe(audio_bytes, filename) -> str
speak(text) -> bytes (MP3 audio)
"""
import os
import io
import time
import logging
import requests

log = logging.getLogger("voice")

GROQ_KEY = os.getenv("GROQ_API_KEY", "")
ELEVENLABS_KEY = os.getenv("ELEVENLABS_API_KEY", "")
ELEVENLABS_VOICE_ID = os.getenv("ELEVENLABS_VOICE_ID", "pNInz6obpgDQGcFmaJgB")  # Adam
ELEVENLABS_TTS_URL = f"https://api.elevenlabs.io/v1/text-to-speech/{ELEVENLABS_VOICE_ID}"

GROQ_TRANSCRIBE_URL = "https://api.groq.com/openai/v1/audio/transcriptions"


def transcribe(audio_bytes: bytes, filename: str = "voice.ogg") -> str:
    """Transcribe audio bytes to text using Groq Whisper."""
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
    """Convert text to MP3 speech using ElevenLabs Adam voice."""
    if not ELEVENLABS_KEY:
        raise RuntimeError("ELEVENLABS_API_KEY not set — cannot speak")
    if len(text) > 4096:
        text = text[:4090] + "..."
    for attempt in range(3):
        try:
            resp = requests.post(
                ELEVENLABS_TTS_URL,
                headers={
                    "xi-api-key": ELEVENLABS_KEY,
                    "Content-Type": "application/json",
                },
                json={
                    "text": text,
                    "model_id": "eleven_monolingual_v1",
                    "voice_settings": {
                        "stability": 0.75,
                        "similarity_boost": 0.85,
                        "style": 0.20,
                        "use_speaker_boost": True
                    }
                },
                timeout=30,
            )
            if resp.status_code == 429:
                wait = 2 ** attempt
                log.warning(f"TTS rate limited, retrying in {wait}s...")
                time.sleep(wait)
                continue
            resp.raise_for_status()
            return resp.content
        except Exception as e:
            if attempt == 2:
                raise
            time.sleep(2 ** attempt)
    raise RuntimeError("ElevenLabs TTS failed after 3 attempts")


def register(brain):
    brain.register_tool("transcribe", transcribe)
    brain.register_tool("speak", speak)
    log.info(f"voice extension registered (TTS: ElevenLabs Adam voice {ELEVENLABS_VOICE_ID})")
