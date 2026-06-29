"""
Extension: web_search
Uses DuckDuckGo Instant Answer API — no key required.
web_search(query) -> dict with results
"""
import logging
import requests

log = logging.getLogger("web_search")

DDGR_URL = "https://api.duckduckgo.com/"


def web_search(query: str, max_results: int = 5) -> dict:
    try:
        resp = requests.get(
            DDGR_URL,
            params={"q": query, "format": "json", "no_redirect": 1, "no_html": 1},
            timeout=10,
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

        return {"query": query, "results": results[:max_results]}

    except Exception as e:
        log.error(f"Web search failed: {e}")
        return {"error": str(e)}


def register(brain):
    brain.register_tool("web_search", web_search)
    brain.system_prompt += (
        "\n\nYou have a web_search tool available. "
        "When asked about current events, news, prices, or anything time-sensitive, "
        "let the user know they can use /search <query> to get live results."
    )
    log.info("web_search extension registered")
