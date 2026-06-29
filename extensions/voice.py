def speak(text: str) -> bytes:
    if not OPENAI_KEY:
        raise RuntimeError("OPENAI_API_KEY not set — cannot speak")
    if len(text) > 4096:
        text = text[:4090] + "..."

    import time
    for attempt in range(3):
        try:
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
                    "response_format": "opus",
                },
                timeout=30,
            )
            if resp.status_code == 429:
                wait = 2 ** attempt  # 1s, 2s, 4s
                log.warning(f"TTS rate limited, retrying in {wait}s...")
                time.sleep(wait)
                continue
            resp.raise_for_status()
            return resp.content
        except Exception as e:
            if attempt == 2:
                raise
            time.sleep(2 ** attempt)
    raise RuntimeError("TTS failed after 3 attempts")
