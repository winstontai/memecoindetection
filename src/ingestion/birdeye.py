"""Birdeye API client - token price, volume, and discovery data."""

import httpx
import structlog
from src.config import settings

log = structlog.get_logger()

BASE_URL = "https://public-api.birdeye.so"


class BirdeyeClient:
    def __init__(self, api_key: str | None = None):
        self.api_key = api_key or settings.birdeye_api_key
        self.headers = {
            "X-API-KEY": self.api_key,
            "x-chain": "solana",
        }
        self.client = httpx.AsyncClient(timeout=30.0, headers=self.headers)

    async def get_token_overview(self, mint_address: str) -> dict:
        """Get token overview including price, volume, market cap."""
        resp = await self.client.get(
            f"{BASE_URL}/defi/token_overview",
            params={"address": mint_address},
        )
        resp.raise_for_status()
        return resp.json().get("data", {})

    async def get_token_price_history(
        self,
        mint_address: str,
        interval: str = "15m",
        time_from: int | None = None,
        time_to: int | None = None,
    ) -> list[dict]:
        """Get OHLCV price history for a token.

        Args:
            interval: 1m, 5m, 15m, 30m, 1H, 4H, 1D
            time_from: Unix timestamp
            time_to: Unix timestamp
        """
        params = {"address": mint_address, "type": interval}
        if time_from:
            params["time_from"] = time_from
        if time_to:
            params["time_to"] = time_to

        resp = await self.client.get(
            f"{BASE_URL}/defi/ohlcv",
            params=params,
        )
        resp.raise_for_status()
        return resp.json().get("data", {}).get("items", [])

    async def get_token_trades(
        self,
        mint_address: str,
        offset: int = 0,
        limit: int = 50,
        sort_type: str = "desc",
    ) -> list[dict]:
        """Get recent trades for a token."""
        resp = await self.client.get(
            f"{BASE_URL}/defi/txs/token",
            params={
                "address": mint_address,
                "offset": offset,
                "limit": limit,
                "sort_type": sort_type,
            },
        )
        resp.raise_for_status()
        return resp.json().get("data", {}).get("items", [])

    async def get_new_listings(self, limit: int = 50) -> list[dict]:
        """Get newly listed tokens."""
        resp = await self.client.get(
            f"{BASE_URL}/defi/v3/token/new_listing",
            params={"limit": limit},
        )
        resp.raise_for_status()
        return resp.json().get("data", {}).get("items", [])

    async def close(self):
        await self.client.aclose()
