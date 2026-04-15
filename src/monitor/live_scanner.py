"""Live scanner - monitors new token launches and generates signals.

MVP approach: poll DexScreener/Birdeye for new tokens, then pull
trades via Helius and run the signal generator.

Future: replace polling with Helius webhooks for lower latency.
"""

import asyncio
import structlog
from datetime import datetime, timedelta
from sqlalchemy.orm import Session

from src.config import settings
from src.db.engine import SessionLocal
from src.db.models import Token, Trade, TokenSignal
from src.ingestion.helius import HeliusClient
from src.ingestion.dexscreener import DexScreenerClient
from src.analysis.signal_generator import generate_signal

log = structlog.get_logger()


class LiveScanner:
    def __init__(self):
        self.helius = HeliusClient()
        self.dexscreener = DexScreenerClient()
        self.seen_tokens: set[str] = set()

    async def discover_new_tokens(self) -> list[dict]:
        """Find tokens we haven't seen before."""
        pairs = await self.dexscreener.get_new_pairs()
        new_tokens = []
        for pair in pairs:
            mint = pair.get("tokenAddress")
            if mint and mint not in self.seen_tokens:
                self.seen_tokens.add(mint)
                new_tokens.append(pair)
        return new_tokens

    async def analyze_token(self, mint_address: str, db: Session) -> TokenSignal | None:
        """Pull early trades for a token and run signal generation."""
        raw_txs = await self.helius.get_token_transactions(mint_address, limit=100)

        trades = []
        for tx in raw_txs:
            parsed = self._parse_helius_swap(tx, mint_address)
            if parsed:
                trades.append(parsed)

        if not trades:
            return None

        # Determine pool creation time (earliest trade)
        pool_created_at = min(t["timestamp"] for t in trades)

        signal = generate_signal(
            token_mint=mint_address,
            trades=trades,
            db=db,
            pool_created_at=pool_created_at,
        )

        return signal

    def _parse_helius_swap(self, tx: dict, target_mint: str) -> dict | None:
        """Parse a Helius enhanced transaction into our trade format."""
        try:
            ts = tx.get("timestamp")
            if not ts:
                return None

            timestamp = datetime.utcfromtimestamp(ts)
            signature = tx.get("signature", "")
            fee_payer = tx.get("feePayer", "")

            # Helius swap events
            events = tx.get("events", {})
            swap = events.get("swap")
            if not swap:
                return None

            token_inputs = swap.get("tokenInputs", [])
            token_outputs = swap.get("tokenOutputs", [])
            native_input = swap.get("nativeInput", {})
            native_output = swap.get("nativeOutput", {})

            # Determine if this is a buy or sell of the target token
            is_buy = any(
                t.get("mint") == target_mint for t in token_outputs
            )
            is_sell = any(
                t.get("mint") == target_mint for t in token_inputs
            )

            if not (is_buy or is_sell):
                return None

            # Calculate SOL amount
            sol_amount = 0
            if is_buy and native_input:
                sol_amount = native_input.get("amount", 0) / 1e9
            elif is_sell and native_output:
                sol_amount = native_output.get("amount", 0) / 1e9

            # Calculate token amount
            token_amount = 0
            if is_buy:
                for t in token_outputs:
                    if t.get("mint") == target_mint:
                        token_amount = t.get("rawTokenAmount", {}).get("tokenAmount", 0)
                        decimals = t.get("rawTokenAmount", {}).get("decimals", 9)
                        token_amount = float(token_amount) / (10 ** decimals)
            else:
                for t in token_inputs:
                    if t.get("mint") == target_mint:
                        token_amount = t.get("rawTokenAmount", {}).get("tokenAmount", 0)
                        decimals = t.get("rawTokenAmount", {}).get("decimals", 9)
                        token_amount = float(token_amount) / (10 ** decimals)

            return {
                "tx_signature": signature,
                "wallet_address": fee_payer,
                "token_mint": target_mint,
                "timestamp": timestamp,
                "side": "buy" if is_buy else "sell",
                "amount_tokens": token_amount,
                "amount_sol": sol_amount,
                "price_usd": None,  # Filled from Birdeye if needed
            }

        except Exception as e:
            log.warning("failed_to_parse_swap", error=str(e), tx_sig=tx.get("signature"))
            return None

    async def run(self):
        """Main polling loop."""
        log.info("live_scanner_started", poll_interval=settings.poll_interval_seconds)

        while True:
            try:
                new_tokens = await self.discover_new_tokens()
                log.info("discovered_tokens", count=len(new_tokens))

                db = SessionLocal()
                try:
                    for token_info in new_tokens:
                        mint = token_info.get("tokenAddress")
                        if not mint:
                            continue

                        signal = await self.analyze_token(mint, db)
                        if signal:
                            db.add(signal)
                            db.commit()
                            log.info(
                                "signal_generated",
                                token=mint,
                                score=signal.score,
                                reason=signal.reason,
                            )
                finally:
                    db.close()

            except Exception as e:
                log.error("scanner_error", error=str(e))

            await asyncio.sleep(settings.poll_interval_seconds)

    async def shutdown(self):
        await self.helius.close()
        await self.dexscreener.close()
