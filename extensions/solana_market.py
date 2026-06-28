"""
Extension: solana_market
Real cross-DEX spread scanner — fetches actual pool prices from each DEX.

Sources (in order of call):
  1. DexPaprika  — per-DEX pool prices for Raydium, Orca, Meteora (no key needed)
  2. Jupiter v2  — aggregate best price + confidence as reference/fallback

Returns structured text for the active LLM to summarize naturally.
"""

import httpx
import asyncio
import logging
from datetime import datetime, timezone

log = logging.getLogger("jarvis.ext.solana_market")

# ── Token mints ───────────────────────────────────────────────────────────────
TOKENS = {
    "SOL":  "So11111111111111111111111111111111111111112",
    "JUP":  "JUPyiwrYJFskUPiHa7hkeR8VUtAeFoSYbKedZNsDvCN",
    "ETH":  "7vfCXTUXx5WJV5JADk17DUJ4ksgau7utNKj4b963voxs",
    "BONK": "DezXAZ8z7PnrnRJjz3wXBoRgixCa6xjnB7YaB1pPB263",
    "WIF":  "EKpQGSJtjMFqKZ9KQanSqYXRcF8fBopzLHYxdM65zcjm",
}

SCAN_TOKENS = ["SOL", "JUP", "ETH", "BONK", "WIF"]

# DexPaprika DEX IDs on Solana
DEX_IDS = {"raydium", "raydium_clmm", "orca", "meteora"}
DEX_LABEL = {
    "raydium": "Raydium",
    "raydium_clmm": "Raydium",
    "orca": "Orca",
    "meteora": "Meteora",
}

DEXPAPRIKA_URL = "https://api.dexpaprika.com/networks/solana/tokens/{mint}/pools"
JUPITER_PRICE_URL = "https://api.jup.ag/price/v2"

# Estimated cost per two-leg Solana arb (fees + slippage per leg)
EST_GAS_USD = 0.004
FEE_PER_LEG_PCT = 0.75  # 0.75% per swap leg


# ── DexPaprika: real per-DEX prices ──────────────────────────────────────────

async def fetch_dex_prices(client: httpx.AsyncClient, token: str) -> dict[str, float]:
    """
    Fetch best price per DEX for a token vs USDC from DexPaprika.
    Returns {"Raydium": 148.32, "Orca": 148.51, "Meteora": 148.29} or subset.
    """
    mint = TOKENS.get(token)
    if not mint:
        return {}

    try:
        resp = await client.get(
            DEXPAPRIKA_URL.format(mint=mint),
            params={"page": 0, "limit": 50, "sort": "desc", "order_by": "volume_usd"},
            timeout=10,
        )
        if resp.status_code == 429:
            log.warning(f"DexPaprika 429 for {token}")
            return {}
        if resp.status_code != 200:
            log.warning(f"DexPaprika {resp.status_code} for {token}")
            return {}

        pools = resp.json().get("pools", [])
        dex_prices: dict[str, float] = {}

        for pool in pools:
            dex_id = pool.get("dex_id", "").lower()
            if dex_id not in DEX_IDS:
                continue
            label = DEX_LABEL[dex_id]
            if label in dex_prices:
                continue  # already got best (highest volume) pool for this DEX

            pool_tokens = [t.get("symbol", "") for t in pool.get("tokens", [])]
            if "USDC" not in pool_tokens:
                continue

            price = float(pool.get("price_usd") or 0)
            if price > 0:
                dex_prices[label] = price

            if len(dex_prices) >= 3:
                break

        return dex_prices

    except Exception as e:
        log.error(f"DexPaprika error for {token}: {e}")
        return {}


# ── Jupiter: aggregate reference price ───────────────────────────────────────

async def fetch_jupiter_prices(client: httpx.AsyncClient) -> dict[str, dict]:
    """Fetch Jupiter aggregate prices for all tokens in one call."""
    try:
        mints = ",".join(TOKENS.values())
        resp = await client.get(JUPITER_PRICE_URL, params={"ids": mints}, timeout=10)
        resp.raise_for_status()
        return resp.json().get("data", {})
    except Exception as e:
        log.error(f"Jupiter price fetch failed: {e}")
        return {}


# ── Spread calculator ─────────────────────────────────────────────────────────

def find_spreads(token: str, dex_prices: dict[str, float], position_size_usd: float = 100.0) -> list[dict]:
    """Compare all DEX pairs and return profitable spread opportunities."""
    opportunities = []
    dexes = list(dex_prices.items())

    for i in range(len(dexes)):
        for j in range(i + 1, len(dexes)):
            name_a, price_a = dexes[i]
            name_b, price_b = dexes[j]
            if price_a <= 0 or price_b <= 0:
                continue

            spread_pct = abs(price_a - price_b) / min(price_a, price_b) * 100
            if spread_pct < 0.1:
                continue

            buy_dex  = name_a if price_a < price_b else name_b
            sell_dex = name_b if price_a < price_b else name_a
            buy_price  = min(price_a, price_b)
            sell_price = max(price_a, price_b)

            # Net spread after 0.75% fee per leg
            net_pct = spread_pct - (FEE_PER_LEG_PCT * 2)
            gross = (net_pct / 100) * position_size_usd
            est_profit = round(gross - EST_GAS_USD, 6)
            executable = spread_pct >= 1.5 and est_profit > 0

            opportunities.append({
                "token": token,
                "pair": f"{token}/USDC",
                "buy_dex": buy_dex,
                "sell_dex": sell_dex,
                "buy_price": round(buy_price, 8),
                "sell_price": round(sell_price, 8),
                "spread_pct": round(spread_pct, 4),
                "net_spread_pct": round(net_pct, 4),
                "est_profit_usd": est_profit,
                "est_gas_usd": EST_GAS_USD,
                "executable": executable,
            })

    return sorted(opportunities, key=lambda x: x["spread_pct"], reverse=True)


# ── Main entry point ──────────────────────────────────────────────────────────

async def get_spreads(_query: str = "") -> str:
    """
    Fetch real per-DEX prices and compute cross-DEX spread opportunities.
    Called by Brain on 'arbitrage/spread' intent.
    """
    ts = datetime.now(timezone.utc).strftime("%H:%M UTC")
    lines = [f"Cross-DEX Spread Scan @ {ts}\n"]
    all_opps = []

    async with httpx.AsyncClient() as client:
        # Fetch Jupiter aggregate + all DEX prices concurrently
        jup_task = asyncio.create_task(fetch_jupiter_prices(client))

        # DexPaprika: stagger 1s between tokens to avoid 429
        dex_results: dict[str, dict[str, float]] = {}
        for token in SCAN_TOKENS:
            dex_results[token] = await fetch_dex_prices(client, token)
            if token != SCAN_TOKENS[-1]:
                await asyncio.sleep(1.2)

        jup_data = await jup_task

    # Build mint→symbol reverse map for Jupiter lookup
    mint_to_sym = {v: k for k, v in TOKENS.items()}

    for token in SCAN_TOKENS:
        dex_prices = dex_results.get(token, {})
        mint = TOKENS[token]
        jup_info = jup_data.get(mint, {})
        jup_price = float(jup_info.get("price", 0))
        jup_conf = jup_info.get("extraInfo", {}).get("confidenceLevel", "?")

        # Header per token
        dex_str = "  |  ".join(f"{d}: ${p:,.6f}" for d, p in dex_prices.items()) or "no pool data"
        lines.append(f"{'─'*50}")
        lines.append(f"{token}/USDC")
        lines.append(f"  DEX prices:  {dex_str}")
        if jup_price > 0:
            lines.append(f"  Jupiter agg: ${jup_price:,.6f} [{jup_conf} confidence]")

        if len(dex_prices) >= 2:
            opps = find_spreads(token, dex_prices)
            if opps:
                for opp in opps:
                    flag = "⚡ EXECUTABLE" if opp["executable"] else "·"
                    lines.append(
                        f"  {flag} {opp['buy_dex']}→{opp['sell_dex']}: "
                        f"{opp['spread_pct']:.3f}% spread  "
                        f"(net {opp['net_spread_pct']:.3f}%  est ${opp['est_profit_usd']:+.4f})"
                    )
                all_opps.extend(opps)
            else:
                lines.append("  No meaningful spreads detected")
        elif len(dex_prices) == 1:
            lines.append("  Only 1 DEX returned data — need 2+ to compare")
        else:
            lines.append("  No DEX pool data available")

    lines.append(f"\n{'═'*50}")
    executable = [o for o in all_opps if o["executable"]]
    if executable:
        best = max(executable, key=lambda x: x["est_profit_usd"])
        lines.append(
            f"BEST OPPORTUNITY: {best['token']} — "
            f"{best['buy_dex']}→{best['sell_dex']} "
            f"{best['spread_pct']:.3f}% spread  est ${best['est_profit_usd']:+.4f}"
        )
    else:
        lines.append("No executable arb opportunities right now (need >1.5% spread net of fees)")

    lines.append(f"\nScanned: {', '.join(SCAN_TOKENS)} | DEX fees: {FEE_PER_LEG_PCT}%/leg | Gas: ~${EST_GAS_USD}")
    return "\n".join(lines)


def register(brain):
    brain.register_extension("solana_market", get_spreads)
