"""
extensions/sol_checker.py
Simple SOL price checker using the Jupiter Price API (no API key required).
"""

import httpx
from datetime import datetime


SOL_MINT = "So11111111111111111111111111111111111111112"
JUPITER_PRICE_URL = f"https://price.jup.ag/v6/price?ids={SOL_MINT}"


def get_sol_price() -> dict:
    """
    Fetch the current SOL price in USD from Jupiter Price API.

    Returns:
        dict with keys:
            price (float)   — current SOL/USD price
            timestamp (str) — UTC timestamp of the fetch
            source (str)    — data source label
    """
    response = httpx.get(JUPITER_PRICE_URL, timeout=10)
    response.raise_for_status()

    data = response.json()
    price = data["data"][SOL_MINT]["price"]

    return {
        "price": price,
        "timestamp": datetime.utcnow().isoformat() + "Z",
        "source": "Jupiter Price API v6",
    }


def format_sol_price() -> str:
    """
    Returns a human-readable SOL price string.

    Example:
        "SOL/USD: $142.57  |  2025-06-10T14:32:01Z  (Jupiter Price API v6)"
    """
    result = get_sol_price()
    return (
        f"SOL/USD: ${result['price']:.2f}"
        f"  |  {result['timestamp']}"
        f"  (source: {result['source']})"
    )


if __name__ == "__main__":
    print(format_sol_price())
