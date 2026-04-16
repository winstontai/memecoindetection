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
        """Parse a Helius enhanced transaction into our trade format.

        Handles multiple sources: standard DEX swaps (events.swap),
        Meteora/Moonshot swaps (tokenTransfers), and Pump AMM swaps.
        """
        try:
            ts = tx.get("timestamp")
            if not ts:
                return None

            timestamp = datetime.utcfromtimestamp(ts)
            signature = tx.get("signature", "")
            fee_payer = tx.get("feePayer", "")

            WSOL_MINT = "So11111111111111111111111111111111"

            # Strategy 1: Use events.swap if available (standard DEX swaps)
            events = tx.get("events", {})
            swap = events.get("swap")
            if swap:
                token_inputs = swap.get("tokenInputs", [])
                token_outputs = swap.get("tokenOutputs", [])
                native_input = swap.get("nativeInput", {})
                native_output = swap.get("nativeOutput", {})

                is_buy = any(t.get("mint") == target_mint for t in token_outputs)
                is_sell = any(t.get("mint") == target_mint for t in token_inputs)

                if not (is_buy or is_sell):
                    return None

                sol_amount = 0
                if is_buy and native_input:
                    sol_amount = float(native_input.get("amount", 0)) / 1e9
                elif is_sell and native_output:
                    sol_amount = float(native_output.get("amount", 0)) / 1e9

                token_amount = 0
                source_list = token_outputs if is_buy else token_inputs
                for t in source_list:
                    if t.get("mint") == target_mint:
                        raw = t.get("rawTokenAmount", {})
                        token_amount = float(raw.get("tokenAmount", 0)) / (10 ** raw.get("decimals", 9))

                return {
                    "tx_signature": signature,
                    "wallet_address": fee_payer,
                    "token_mint": target_mint,
                    "timestamp": timestamp,
                    "side": "buy" if is_buy else "sell",
                    "amount_tokens": token_amount,
                    "amount_sol": sol_amount,
                    "price_usd": None,
                }

            # Strategy 2: Use tokenTransfers (Meteora, Pump AMM, etc.)
            token_transfers = tx.get("tokenTransfers", [])
            native_transfers = tx.get("nativeTransfers", [])

            if not token_transfers:
                return None

            # Find transfers of our target token
            target_transfers = [t for t in token_transfers if t.get("mint") == target_mint]
            if not target_transfers:
                return None

            # Find SOL/wSOL transfers
            sol_transfers = [t for t in token_transfers if t.get("mint") == WSOL_MINT]

            # Determine buy vs sell: if fee_payer receives the target token, it's a buy
            is_buy = any(t.get("toUserAccount") == fee_payer for t in target_transfers)
            is_sell = any(t.get("fromUserAccount") == fee_payer for t in target_transfers)

            if not (is_buy or is_sell):
                # Check if any transfer involves the fee payer indirectly
                return None

            # Sum token amount
            token_amount = 0
            for t in target_transfers:
                amt = float(t.get("tokenAmount", 0))
                if is_buy and t.get("toUserAccount") == fee_payer:
                    token_amount += amt
                elif is_sell and t.get("fromUserAccount") == fee_payer:
                    token_amount += amt

            # Sum SOL amount from wSOL transfers or native transfers
            sol_amount = 0
            for t in sol_transfers:
                amt = float(t.get("tokenAmount", 0))
                if is_buy and t.get("fromUserAccount") == fee_payer:
                    sol_amount += amt
                elif is_sell and t.get("toUserAccount") == fee_payer:
                    sol_amount += amt

            # Fallback: use native transfers if no wSOL found
            if sol_amount == 0:
                for t in native_transfers:
                    amt = float(t.get("amount", 0)) / 1e9
                    if is_buy and t.get("fromUserAccount") == fee_payer:
                        sol_amount += amt
                    elif is_sell and t.get("toUserAccount") == fee_payer:
                        sol_amount += amt

            return {
                "tx_signature": signature,
                "wallet_address": fee_payer,
                "token_mint": target_mint,
                "timestamp": timestamp,
                "side": "buy" if is_buy else "sell",
                "amount_tokens": token_amount,
                "amount_sol": sol_amount,
                "price_usd": None,
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
