"""
Extension: voice
Transcription: Groq Whisper (fast, free tier)
TTS: OpenAI TTS (onyx voice — deep and neutral, like JARVIS)

Functions:
    transcribe(audio_bytes) -> str
    speak(text) -> bytes  (MP3 format, suitable for Telegram voice notes)
    register(brain) -> None (register tools with brain)
"""

import os
import io
import logging
import requests
from typing import Optional

log = logging.getLogger("voice")

GROQ_KEY   = os.getenv("GROQ_API_KEY", "")
OPENAI_KEY = os.getenv("OPENAI_API_KEY", "")

# OpenAI TTS voice — "onyx" is deep and neutral (JARVIS-like)
TTS_VOICE = os.getenv("JARVIS_TTS_VOICE", "onyx")
TTS_MODEL = "tts-1"

GROQ_TRANSCRIBE_URL = "https://api.groq.com/openai/v1/audio/transcriptions"
OPENAI_TTS_URL      = "https://api.openai.com/v1/audio/speech"


def transcribe(audio_bytes: bytes, filename: str = "voice.ogg") -> str:
    """
    Send audio bytes to Groq Whisper and return transcript text.
    
    Accepts OGG (Telegram default), MP3, WAV, M4A.
    
    Args:
        audio_bytes: Raw audio data
        filename: Original filename for MIME detection (default: "voice.ogg")
    
    Returns:
        Transcribed text (stripped of whitespace)
    
    Raises:
        RuntimeError: If GROQ_API_KEY is not set
        requests.HTTPError: If Groq API request fails
    """
    if not GROQ_KEY:
        error_msg = "GROQ_API_KEY not set — cannot transcribe audio"
        log.error(error_msg)
        raise RuntimeError(error_msg)

    try:
        log.debug(f"Transcribing {len(audio_bytes)} bytes of audio ({filename})")
        
        resp = requests.post(
            GROQ_TRANSCRIBE_URL,
            headers={"Authorization": f"Bearer {GROQ_KEY}"},
            files={"file": (filename, io.BytesIO(audio_bytes), "audio/ogg")},
            data={"model": "whisper-large-v3", "response_format": "text"},
            timeout=30,
        )
        resp.raise_for_status()
        
        text = resp.text.strip()
        log.info(f"Transcription complete: '{text[:80]}{'...' if len(text) > 80 else ''}'")
        return text
        
    except requests.HTTPError as e:
        error_msg = f"Groq transcription API error {e.response.status_code}: {e.response.text}"
        log.error(error_msg)
        raise RuntimeError(error_msg) from e
    except requests.Timeout:
        error_msg = "Groq transcription request timed out (30s)"
        log.error(error_msg)
        raise RuntimeError(error_msg)
    except Exception as e:
        error_msg = f"Transcription failed: {type(e).__name__}: {e}"
        log.error(error_msg)
        raise RuntimeError(error_msg) from e


def speak(text: str, voice: Optional[str] = None) -> bytes:
    """
    Convert text to speech via OpenAI TTS.
    
    Returns raw MP3 bytes — Telegram accepts this as a voice note.
    
    Args:
        text: Text to synthesize (max 4096 chars)
        voice: Voice name (default: JARVIS_TTS_VOICE or "onyx")
               Options: alloy, echo, fable, onyx, nova, shimmer
    
    Returns:
        Audio data in MP3 format
    
    Raises:
        RuntimeError: If OPENAI_API_KEY is not set
        requests.HTTPError: If OpenAI API request fails
    """
    if not OPENAI_KEY:
        error_msg = "OPENAI_API_KEY not set — cannot synthesize speech"
        log.error(error_msg)
        raise RuntimeError(error_msg)

    voice = voice or TTS_VOICE
    
    # Telegram voice notes max ~1 min; OpenAI TTS handles up to 4096 chars per call
    if len(text) > 4096:
        log.warning(f"Text too long ({len(text)} chars), truncating to 4090")
        text = text[:4090] + "..."

    try:
        log.debug(f"Synthesizing speech ({len(text)} chars, voice={voice})")
        
        resp = requests.post(
            OPENAI_TTS_URL,
            headers={
                "Authorization": f"Bearer {OPENAI_KEY}",
                "Content-Type": "application/json",
            },
            json={
                "model": TTS_MODEL,
                "voice": voice,
                "input": text,
                "response_format": "mp3",
            },
            timeout=30,
        )
        resp.raise_for_status()
        
        audio_bytes = resp.content
        log.info(f"Speech synthesized: {len(audio_bytes)} bytes")
        return audio_bytes
        
    except requests.HTTPError as e:
        error_msg = f"OpenAI TTS API error {e.response.status_code}: {e.response.text}"
        log.error(error_msg)
        raise RuntimeError(error_msg) from e
    except requests.Timeout:
        error_msg = "OpenAI TTS request timed out (30s)"
        log.error(error_msg)
        raise RuntimeError(error_msg)
    except Exception as e:
        error_msg = f"Speech synthesis failed: {type(e).__name__}: {e}"
        log.error(error_msg)
        raise RuntimeError(error_msg) from e


def register(brain):
    """
    Register voice functions with the JARVIS brain.
    
    Args:
        brain: Brain instance with register_tool() method
    """
    try:
        brain.register_tool("transcribe", transcribe)
        brain.register_tool("speak", speak)
        log.info(f"✓ voice extension registered (TTS voice: {TTS_VOICE})")
    except Exception as e:
        log.error(f"Failed to register voice extension: {e}")
        raise
