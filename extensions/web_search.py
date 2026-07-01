"""
Extension: web_search
Primary: DuckDuckGo HTML endpoint (more reliable than the JSON Instant Answer API,
which times out from some hosting environments).
Fallback: DuckDuckGo Instant Answer JSON API.
Second fallback: Wikipedia search API (for factual/reference queries).
web_search(query) -> dict with results

NOTE: DDG HTML endpoint MUST be called with GET, not POST. Render's datacenter
IPs get blocked/anti-bot-challenged on POST requests to html.duckduckgo.com.
GET has been confirmed working live. Do not change this back to POST.
"""
import logging
import requests
from html.parser import HTMLParser

log = logging.getLogger("web_search")

DDG_HTML_URL = "https://html.duckduckgo.com/html/"
DDG_JSON_URL = "https://api.duckduckgo.com/"
WIKI_URL = "https://en.wikipedia.org/w/api.php"

HEADERS = {
    "User-Agent": "Mozilla/5.0 (compatible; JarvisBot/1.0; +https://render.com)"
}


class _DDGResultParser(HTMLParser):
    """Minimal parser to pull result links/snippets from DDG HTML results page."""

    def __init__(self):
        super().__init__()
        self.results = []
        self._in_result_title = False
        self._in_snippet = False
        self._current = {}

    def handle_starttag(self, tag, attrs):
        attrs_d = dict(attrs)
        cls = attrs_d.get("class", "")
        if tag == "a" and "result__a" in cls:
            self._in_result_title = True
            self._current = {"title": "", "url": attrs_d.get("href", ""), "snippet": ""}
        elif tag == "a" and "result__snippet" in cls:
            self._in_snippet = True

    def handle_data(self, data):
        if self._in_result_title:
            self._current["title"] += data
        elif self._in_snippet:
            self._current["snippet"] += data

    def handle_endtag(self, tag):
        if tag == "a" and self._in_result_title:
            self._in_result_title = False
        if tag == "a" and self._in_snippet:
            self._in_snippet = False
            if self._current.get("title"):
                self.results.append(self._current)
                self._current = {}


def _search_ddg_html(query: str, max_results: int) -> list:
    resp = requests.get(
        DDG_HTML_URL,
        params={"q": query},
        headers=HEADERS,
        timeout=12,
    )
    resp.raise_for_status()
    parser = _DDGResultParser()
    parser.feed(resp.text)
    return parser.results[:max_results]


def _search_ddg_json(query: str, max_results: int) -> list:
    resp = requests.get(
        DDG_JSON_URL,
        params={"q": query, "format": "json", "no_redirect": 1, "no_html": 1},
        headers=HEADERS,
        timeout=8,
    )
    resp.raise_for_status()
    data = resp.json()
    results = []
    if data.get("Abstract"):
        results.append({
            "title": data.get("Heading", "Summary"),
            "snippet": data["Abstract"],
            "url": data.get("AbstractURL", ""),
        })
    for topic in data.get("RelatedTopics", [])[:max_results]:
        if "Text" in topic and "FirstURL" in topic:
            results.append({
                "title": topic.get("Text", "")[:80],
                "snippet": topic.get("Text", ""),
                "url": topic.get("FirstURL", ""),
            })
    return results[:max_results]


def _search_wikipedia(query: str, max_results: int) -> list:
    resp = requests.get(
        WIKI_URL,
        params={
            "action": "query",
            "list": "search",
            "srsearch": query,
            "format": "json",
            "srlimit": max_results,
        },
        headers=HEADERS,
        timeout=8,
    )
    resp.raise_for_status()
    data = resp.json()
    results = []
    for item in data.get("query", {}).get("search", [])[:max_results]:
        title = item.get("title", "")
        snippet = item.get("snippet", "").replace('<span class="searchmatch">', "").replace("</span>", "")
        results.append({
            "title": title,
            "snippet": snippet,
            "url": f"https://en.wikipedia.org/wiki/{title.replace(' ', '_')}",
        })
    return results


def web_search(query: str, max_results: int = 5) -> dict:
    errors = []

    for name, fn in [
        ("ddg_html", _search_ddg_html),
        ("ddg_json", _search_ddg_json),
        ("wikipedia", _search_wikipedia),
    ]:
        try:
            results = fn(query, max_results)
            if results:
                return {"query": query, "source": name, "results": results}
        except Exception as e:
            errors.append(f"{name}: {e}")
            log.warning("web_search %s failed: %s", name, e)

    return {"query": query, "source": None, "results": [], "errors": errors}
