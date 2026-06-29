"""
Extension: browser
Full headless browser access via Browserless.io
Renders JS, clicks, fills forms, takes screenshots.
"""
import os
import logging
import requests

log = logging.getLogger("jarvis.browser")

TOKEN = os.getenv("BROWSERLESS_TOKEN", "")
BASE = "https://chrome.browserless.io"


def browser_fetch(url: str, wait_for: str = "", max_chars: int = 6000) -> dict:
    """Fetch a fully rendered page including JS content."""
    if not TOKEN:
        return {"error": "BROWSERLESS_TOKEN not set"}
    try:
        payload = {
            "url": url,
            "gotoOptions": {"waitUntil": "networkidle2", "timeout": 30000},
        }
        if wait_for:
            payload["waitForSelector"] = wait_for

        resp = requests.post(
            f"{BASE}/content?token={TOKEN}",
            json=payload,
            timeout=35,
        )
        resp.raise_for_status()
        html = resp.text

        # Extract text from HTML
        from html.parser import HTMLParser
        class TextExtractor(HTMLParser):
            def __init__(self):
                super().__init__()
                self.text = []
                self.skip = False
            def handle_starttag(self, tag, attrs):
                if tag in ('script', 'style', 'nav', 'footer', 'head', 'meta'):
                    self.skip = True
            def handle_endtag(self, tag):
                if tag in ('script', 'style', 'nav', 'footer', 'head', 'meta'):
                    self.skip = False
            def handle_data(self, data):
                if not self.skip:
                    t = data.strip()
                    if t:
                        self.text.append(t)
            def get_text(self):
                return '\n'.join(self.text)

        parser = TextExtractor()
        parser.feed(html)
        text = parser.get_text()

        if len(text) > max_chars:
            text = text[:max_chars] + '\n...[truncated]'

        return {"url": url, "content": text, "length": len(text)}

    except Exception as e:
        log.error(f"Browser fetch failed for {url}: {e}")
        return {"error": str(e), "url": url}


def browser_screenshot(url: str) -> dict:
    """Take a screenshot of a page and return base64."""
    if not TOKEN:
        return {"error": "BROWSERLESS_TOKEN not set"}
    try:
        resp = requests.post(
            f"{BASE}/screenshot?token={TOKEN}",
            json={
                "url": url,
                "options": {"fullPage": False, "type": "png"},
                "gotoOptions": {"waitUntil": "networkidle2", "timeout": 30000},
            },
            timeout=35,
        )
        resp.raise_for_status()
        import base64
        b64 = base64.b64encode(resp.content).decode()
        return {"url": url, "screenshot_b64": b64, "size": len(resp.content)}
    except Exception as e:
        log.error(f"Screenshot failed for {url}: {e}")
        return {"error": str(e)}


def browser_scrape(url: str, selector: str) -> dict:
    """Extract specific elements from a page using CSS selector."""
    if not TOKEN:
        return {"error": "BROWSERLESS_TOKEN not set"}
    try:
        script = f"""
        module.exports = async ({{ page }}) => {{
            await page.goto('{url}', {{ waitUntil: 'networkidle2' }});
            const elements = await page.$$eval('{selector}', els => els.map(el => el.innerText));
            return {{ url: '{url}', selector: '{selector}', results: elements }};
        }};
        """
        resp = requests.post(
            f"{BASE}/function?token={TOKEN}",
            json={"code": script},
            timeout=35,
        )
        resp.raise_for_status()
        return resp.json()
    except Exception as e:
        log.error(f"Scrape failed for {url}: {e}")
        return {"error": str(e)}


def browser_run(script: str) -> dict:
    """Run custom Puppeteer script on Browserless."""
    if not TOKEN:
        return {"error": "BROWSERLESS_TOKEN not set"}
    try:
        resp = requests.post(
            f"{BASE}/function?token={TOKEN}",
            json={"code": script},
            timeout=35,
        )
        resp.raise_for_status()
        return resp.json()
    except Exception as e:
        log.error(f"Browser script failed: {e}")
        return {"error": str(e)}


def register(brain):
    brain.register_tool("browser_fetch", browser_fetch)
    brain.register_tool("browser_screenshot", browser_screenshot)
    brain.register_tool("browser_scrape", browser_scrape)
    brain.register_tool("browser_run", browser_run)
    log.info("browser extension registered")
