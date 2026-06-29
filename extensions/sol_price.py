"""
Extension: sol_price
Fetches live SOL price from DexPaprika (no auth required).
"""
import logging
import requests

log = logging.getLogger("jarvis.sol_price")


def get_sol_price() -> dict:
    try:
        resp = requests.get(
            "https://api.dexpaprika.com/tokens/solana/So11111111111111111111111111111111111111112",
            timeout=10
        )
        resp.raise_for_status()
        data = resp.json()
        price = float(data["price_usd"])
        return {"price": price, "symbol": "SOL"}
    except Exception as e:
        log.error(f"SOL price fetch failed: {e}")
        return {"error": str(e)}


def register(brain):
    brain.register_tool("sol_price", get_sol_price)
    log.info("sol_price extension registered")
