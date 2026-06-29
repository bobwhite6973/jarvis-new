"""
Extension: sol_price
Fetches live SOL price from Jupiter Price API v2.
"""
import logging
import requests

log = logging.getLogger("jarvis.sol_price")

SOL_MINT = "So11111111111111111111111111111111111111112"


def get_sol_price() -> dict:
    try:
        resp = requests.get(
            f"https://api.jup.ag/price/v2?ids={SOL_MINT}",
            timeout=10
        )
        resp.raise_for_status()
        data = resp.json()
        price = float(data["data"][SOL_MINT]["price"])
        return {"price": price, "symbol": "SOL"}
    except Exception as e:
        log.error(f"SOL price fetch failed: {e}")
        return {"error": str(e)}


def register(brain):
    brain.register_tool("sol_price", get_sol_price)
    log.info("sol_price extension registered")
