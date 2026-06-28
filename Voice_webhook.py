"""
voice_webhook.py — HTTP endpoint for iOS Shortcut voice interface.

Accepts POST /voice with text or audio, returns JARVIS response as plain text.
Runs alongside the Telegram bot in a background thread.
"""

import os
import json
import threading
import logging
from http.server import HTTPServer, BaseHTTPRequestHandler

log = logging.getLogger("jarvis.voice_webhook")

_brain = None
_loop = None


class VoiceHandler(BaseHTTPRequestHandler):

    def log_message(self, format, *args):
        pass

    def _send(self, text: str, code: int = 200):
        body = text.encode()
        self.send_response(code)
        self.send_header("Content-Type", "text/plain; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Access-Control-Allow-Origin", "*")
        self.end_headers()
        self.wfile.write(body)

    def _auth(self) -> bool:
        secret = os.environ.get("VOICE_WEBHOOK_SECRET", "")
        if not secret:
            return True
        return self.headers.get("X-Secret", "") == secret

    def do_OPTIONS(self):
        self.send_response(200)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "POST, GET, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type, X-Secret")
        self.end_headers()

    def do_GET(self):
        if self.path == "/health":
            self._send("JARVIS voice webhook online")
        else:
            self._send("Not found", 404)

    def do_POST(self):
        if not self._auth():
            self._send("Unauthorized", 401)
            return

        if self.path != "/voice":
            self._send("Not found", 404)
            return

        length = int(self.headers.get("Content-Length", 0))
        if not length:
            self._send("No body", 400)
            return

        body = self.rfile.read(length)
        try:
            data = json.loads(body)
            query = data.get("text", "").strip()
            user_id = data.get("user_id", "siri_user")
        except Exception:
            query = body.decode("utf-8", errors="ignore").strip()
            user_id = "siri_user"

        if not query:
            self._send("Empty query", 400)
            return

        if _brain is None or _loop is None:
            self._send("Brain not initialized", 503)
            return

        import asyncio
        future = asyncio.run_coroutine_threadsafe(
            _brain.think(user_id, query), _loop
        )
        try:
            response = future.result(timeout=30)
        except Exception as e:
            response = f"Error: {e}"

        self._send(response)


def start(brain, loop):
    global _brain, _loop
    _brain = brain
    _loop = loop

    port = int(os.environ.get("VOICE_PORT", 8081))

    def _serve():
        try:
            server = HTTPServer(("0.0.0.0", port), VoiceHandler)
            log.info(f"Voice webhook on :{port} — POST /voice")
            server.serve_forever()
        except Exception as e:
            log.error(f"Voice webhook failed: {e}")

    t = threading.Thread(target=_serve, daemon=True, name="voice-webhook")
    t.start()
    return t
