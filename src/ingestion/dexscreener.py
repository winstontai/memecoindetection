"""DexScreener client - free, no API key needed. Good for token discovery."""

import httpx
import structlog

log = structlog.get_logger()

BASE_URL = "https://api.dexscreener.com/latest"


class DexScreenerClient:
    def __init__(self):
        self.client = httpx.AsyncClient(timeout=30.0)

    async def get_token_pairs(self, mint_address: str) -> list[dict]:
        """Get all trading pairs for a token."""
        resp = await self.client.get(
            f"{BASE_URL}/dex/tokens/{mint_address}"
        )
        resp.raise_for_status()
        return resp.json().get("pairs", [])

    async def search_tokens(self, query: str) -> list[dict]:
        """Search for tokens by name or symbol."""
        resp = await self.client.get(
            f"{BASE_URL}/dex/search",
            params={"q": query},
        )
        resp.raise_for_status()
        return resp.json().get("pairs", [])

    async def get_new_pairs(self) -> list[dict]:
        """Get recently created pairs on Solana."""
        resp = await self.client.get(
            f"https://api.dexscreener.com/token-profiles/latest/v1",
        )
        resp.raise_for_status()
        return [p for p in resp.json() if p.get("chainId") == "solana"]

    async def close(self):
        await self.client.aclose()
