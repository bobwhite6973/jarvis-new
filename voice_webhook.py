"""
voice_webhook.py — HTTP endpoint for iOS Shortcut voice interface.

Accepts POST /voice with text or audio, returns JARVIS response as plain text.
Runs alongside the Telegram bot in a background thread.

Environment:
    VOICE_PORT: Port to run on (default: 8081)
    VOICE_WEBHOOK_SECRET: Optional authentication token in X-Secret header
"""

import os
import json
import threading
import logging
import asyncio
from http.server import HTTPServer, BaseHTTPRequestHandler

log = logging.getLogger("jarvis.voice_webhook")

_brain = None
_loop = None
_initialized = False


class VoiceHandler(BaseHTTPRequestHandler):
    """HTTP request handler for voice webhook."""

    def log_message(self, format, *args):
        """Suppress default HTTP server logging."""
        pass

    def _send(self, text: str, code: int = 200):
        """
        Send HTTP response.
        
        Args:
            text: Response body
            code: HTTP status code
        """
        try:
            body = text.encode('utf-8', errors='replace')
            self.send_response(code)
            self.send_header("Content-Type", "text/plain; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Access-Control-Allow-Origin", "*")
            self.end_headers()
            self.wfile.write(body)
        except Exception as e:
            log.error(f"Failed to send response: {e}")

    def _auth(self) -> bool:
        """
        Validate request authentication.
        
        Returns:
            True if authenticated (or no secret required), False otherwise
        """
        secret = os.environ.get("VOICE_WEBHOOK_SECRET", "")
        if not secret:
            return True  # No auth required
        
        client_secret = self.headers.get("X-Secret", "")
        is_valid = client_secret == secret
        
        if not is_valid:
            log.warning(f"Unauthorized request from {self.client_address[0]}")
        
        return is_valid

    def do_OPTIONS(self):
        """Handle CORS preflight requests."""
        self.send_response(200)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "POST, GET, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type, X-Secret")
        self.end_headers()

    def do_GET(self):
        """Handle GET requests (health check)."""
        if self.path == "/health":
            self._send("JARVIS voice webhook online")
        else:
            self._send("Not found", 404)

    def do_POST(self):
        """
        Handle voice queries.
        
        POST /voice with JSON body:
            {
                "text": "your query here",
                "user_id": "optional_user_id"
            }
        
        Optional headers:
            X-Secret: Authentication token (if VOICE_WEBHOOK_SECRET is set)
        """
        # Authentication check
        if not self._auth():
            self._send("Unauthorized", 401)
            return

        # Route validation
        if self.path != "/voice":
            self._send("Not found", 404)
            return

        # Content length validation
        try:
            length = int(self.headers.get("Content-Length", 0))
        except ValueError:
            self._send("Invalid Content-Length", 400)
            return
        
        if not length:
            self._send("No body", 400)
            return

        # Read request body
        try:
            body = self.rfile.read(length)
        except Exception as e:
            log.error(f"Failed to read request body: {e}")
            self._send("Read error", 400)
            return

        # Parse JSON or plain text
        query = None
        user_id = "siri_user"
        
        try:
            data = json.loads(body)
            query = data.get("text", "").strip()
            user_id = data.get("user_id", "siri_user")
        except json.JSONDecodeError:
            # Fallback to plain text
            query = body.decode("utf-8", errors="ignore").strip()

        # Validate query
        if not query:
            self._send("Empty query", 400)
            return

        # Brain initialization check
        if _brain is None or _loop is None or not _initialized:
            log.error("Brain not initialized — cannot process query")
            self._send("Brain not initialized (service starting up?)", 503)
            return

        # Process query asynchronously
        try:
            log.debug(f"Processing voice query from {user_id}: '{query[:80]}...'")
            
            future = asyncio.run_coroutine_threadsafe(
                _brain.think(user_id, query), _loop
            )
            
            try:
                response = future.result(timeout=30)
                log.info(f"Query processed successfully: '{response[:100]}...'")
            except asyncio.TimeoutError:
                response = "Query timed out after 30 seconds"
                log.warning(response)
            except Exception as e:
                response = f"Error processing query: {type(e).__name__}: {str(e)[:100]}"
                log.error(response)

            self._send(response)
            
        except Exception as e:
            error_msg = f"Unexpected error: {type(e).__name__}: {e}"
            log.error(error_msg)
            self._send(error_msg, 500)


def start(brain, loop):
    """
    Start the voice webhook server.
    
    Args:
        brain: JARVIS brain instance with think() async method
        loop: Event loop for async operations
    
    Returns:
        Thread running the webhook server
    
    Note:
        Call this AFTER brain and event loop are fully initialized.
    """
    global _brain, _loop, _initialized
    
    if brain is None or loop is None:
        log.error("Cannot start webhook: brain and loop must not be None")
        raise ValueError("brain and loop are required")
    
    _brain = brain
    _loop = loop
    _initialized = True

    port = int(os.environ.get("VOICE_PORT", 8081))

    def _serve():
        """Server thread target."""
        try:
            server = HTTPServer(("0.0.0.0", port), VoiceHandler)
            log.info(f"✓ Voice webhook listening on :{port} — POST /voice with JSON")
            server.serve_forever()
        except Exception as e:
            log.error(f"✗ Voice webhook failed to start: {e}")
            _initialized = False

    t = threading.Thread(target=_serve, daemon=True, name="voice-webhook")
    t.start()
    log.info(f"Voice webhook thread started")
    return t
