"""
TTS Module - Text to Speech
Provides voice synthesis using OpenAI's TTS engine or Groq's speech capabilities.

Usage:
    from tts import speak_text, speak_async
    
    # Synchronous speech (blocks until complete)
    speak_text("Hello World")
    
    # Asynchronous speech (non-blocking)
    speak_async("Hello World")
"""

import os
import io
import logging
import requests
import concurrent.futures
from typing import Optional, Callable

log = logging.getLogger("tts")

# Configuration from environment
OPENAI_KEY = os.getenv("OPENAI_API_KEY", "")
GROQ_KEY = os.getenv("GROQ_API_KEY", "")
TTS_VOICE = os.getenv("JARVIS_TTS_VOICE", "onyx")  # onyx, fable, nova, shimmer, echo, alloy
TTS_MODEL = "tts-1"

OPENAI_TTS_URL = "https://api.openai.com/v1/audio/speech"

# Thread pool for async operations
_executor = concurrent.futures.ThreadPoolExecutor(max_workers=2, thread_name_prefix="tts-")


def speak_text(text: str, voice: Optional[str] = None, callback: Optional[Callable] = None) -> bytes:
    """
    Synthesize text to speech and return audio bytes.
    
    Args:
        text: Text to convert to speech
        voice: Voice to use (default: JARVIS_TTS_VOICE env var or 'onyx')
        callback: Optional callback function for completion
    
    Returns:
        Audio bytes in MP3 format
        
    Raises:
        RuntimeError: If OPENAI_API_KEY is not set
        requests.HTTPError: If OpenAI API request fails
    """
    if not OPENAI_KEY:
        error_msg = "OPENAI_API_KEY not set — cannot synthesize speech"
        log.error(error_msg)
        raise RuntimeError(error_msg)
    
    voice = voice or TTS_VOICE
    
    # Truncate if too long (OpenAI limit is 4096 chars)
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
        log.info(f"Speech synthesized successfully ({len(audio_bytes)} bytes)")
        
        if callback:
            callback(audio_bytes)
        
        return audio_bytes
        
    except requests.HTTPError as e:
        error_msg = f"OpenAI TTS API error: {e.response.status_code} — {e.response.text}"
        log.error(error_msg)
        raise
    except Exception as e:
        error_msg = f"Speech synthesis failed: {e}"
        log.error(error_msg)
        raise RuntimeError(error_msg) from e


def speak_async(text: str, voice: Optional[str] = None, callback: Optional[Callable] = None) -> concurrent.futures.Future:
    """
    Synthesize text to speech asynchronously (non-blocking).
    
    Args:
        text: Text to convert to speech
        voice: Voice to use (default: JARVIS_TTS_VOICE env var or 'onyx')
        callback: Optional callback function(audio_bytes) called on completion
    
    Returns:
        Future object — call .result() to wait for completion and get audio bytes
        
    Example:
        future = speak_async("Hello World")
        # ... do other work ...
        audio_bytes = future.result()  # Blocks until ready
    """
    log.debug(f"Queuing async speech synthesis for {len(text)} chars")
    return _executor.submit(speak_text, text, voice, callback)


def speak_and_play_local(text: str, voice: Optional[str] = None) -> None:
    """
    Synthesize speech and play it locally (requires system audio setup).
    
    Args:
        text: Text to convert to speech
        voice: Voice to use
        
    Note: Requires pydub and ffplay/pygame for playback. For Telegram, use speak_text() instead.
    """
    try:
        from pydub import AudioSegment
        from pydub.playback import play
    except ImportError:
        error_msg = "pydub not installed — cannot play audio locally. Install with: pip install pydub"
        log.error(error_msg)
        raise RuntimeError(error_msg)
    
    try:
        audio_bytes = speak_text(text, voice)
        audio = AudioSegment.from_mp3(io.BytesIO(audio_bytes))
        log.info(f"Playing audio ({len(audio)}ms)")
        play(audio)
    except Exception as e:
        log.error(f"Playback failed: {e}")
        raise


def shutdown():
    """Clean up thread pool."""
    _executor.shutdown(wait=True)
    log.info("TTS executor shut down")
