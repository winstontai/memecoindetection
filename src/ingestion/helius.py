"""Helius API client - primary data source for Solana transaction data."""

import httpx
import structlog
from datetime import datetime
from typing import Optional

from src.config import settings

log = structlog.get_logger()

BASE_URL = "https://api.helius.xyz/v0"
ENHANCED_BASE = "https://api.helius.xyz/v1"


class HeliusClient:
    def __init__(self, api_key: str | None = None):
        self.api_key = api_key or settings.helius_api_key
        self.client = httpx.AsyncClient(timeout=60.0)

    async def get_token_transactions(
        self,
        mint_address: str,
        before_signature: str | None = None,
        limit: int = 100,
    ) -> list[dict]:
        """Get parsed transaction history for a token.

        This is the workhorse method for historical backfill.
        Returns transactions in reverse chronological order.
        """
        url = f"{BASE_URL}/addresses/{mint_address}/transactions"
        params = {
            "api-key": self.api_key,
            "limit": limit,
        }
        if before_signature:
            params["before"] = before_signature

        resp = await self.client.get(url, params=params)
        resp.raise_for_status()
        return resp.json()

    async def get_wallet_transactions(
        self,
        wallet_address: str,
        before_signature: str | None = None,
        limit: int = 100,
    ) -> list[dict]:
        """Get parsed transaction history for a wallet."""
        url = f"{BASE_URL}/addresses/{wallet_address}/transactions"
        params = {
            "api-key": self.api_key,
            "limit": limit,
        }
        if before_signature:
            params["before"] = before_signature

        resp = await self.client.get(url, params=params)
        resp.raise_for_status()
        return resp.json()

    async def get_token_holders(self, mint_address: str) -> list[dict]:
        """Get current holders of a token via DAS API."""
        url = f"{settings.helius_rpc_url}"
        payload = {
            "jsonrpc": "2.0",
            "id": "moonshot",
            "method": "getTokenAccounts",
            "params": {
                "mint": mint_address,
                "limit": 1000,
            },
        }
        resp = await self.client.post(url, json=payload)
        resp.raise_for_status()
        data = resp.json()
        return data.get("result", {}).get("token_accounts", [])

    async def get_signatures_for_address(
        self,
        address: str,
        before: str | None = None,
        until: str | None = None,
        limit: int = 1000,
    ) -> list[dict]:
        """Get raw transaction signatures for an address (RPC method)."""
        url = settings.helius_rpc_url
        params = {"limit": limit}
        if before:
            params["before"] = before
        if until:
            params["until"] = until

        payload = {
            "jsonrpc": "2.0",
            "id": "moonshot",
            "method": "getSignaturesForAddress",
            "params": [address, params],
        }
        resp = await self.client.post(url, json=payload)
        resp.raise_for_status()
        return resp.json().get("result", [])

    async def get_parsed_transaction(self, signature: str) -> dict | None:
        """Get a single parsed transaction by signature."""
        url = f"{BASE_URL}/transactions"
        params = {"api-key": self.api_key}
        payload = {"transactions": [signature]}

        resp = await self.client.post(url, params=params, json=payload)
        resp.raise_for_status()
        results = resp.json()
        return results[0] if results else None

    async def close(self):
        await self.client.aclose()
