"""Historical backfill script.

Pulls trade data for a list of known tokens and populates the database.
Uses Birdeye's trade API which returns only swaps and supports offset pagination.

Usage:
    python -m src.scripts.backfill --tokens-file data/seed_tokens.json --create-db
"""

import asyncio
import json
import click
import structlog
import httpx
from datetime import datetime, timedelta, timezone
from pathlib import Path

from src.db.engine import SessionLocal
from src.db.models import Base, Token, Wallet, Trade
from src.db.engine import engine
from src.ingestion.birdeye import BirdeyeClient

log = structlog.get_logger()

BATCH_SIZE = 50  # Birdeye max per request


def create_tables():
    """Create all database tables."""
    Base.metadata.create_all(engine)
    log.info("database_tables_created")


WSOL_ADDRESS = "So11111111111111111111111111111111111111112"


def parse_birdeye_trade(trade: dict, token_mint: str) -> dict:
    """Convert a Birdeye trade object into our internal format."""
    ts = datetime.fromtimestamp(trade["blockUnixTime"], tz=timezone.utc).replace(tzinfo=None)
    price_usd = trade.get("tokenPrice")

    # Birdeye sometimes swaps base/quote. Identify SOL by address.
    quote = trade.get("quote", {})
    base = trade.get("base", {})

    if quote.get("address") == WSOL_ADDRESS:
        sol_amount = abs(quote.get("uiAmount", 0))
        token_amount = abs(base.get("uiAmount", 0))
    elif base.get("address") == WSOL_ADDRESS:
        sol_amount = abs(base.get("uiAmount", 0))
        token_amount = abs(quote.get("uiAmount", 0))
    else:
        # Neither is SOL (e.g. token/USDC pair) — use quote as fallback
        sol_amount = abs(quote.get("uiAmount", 0))
        token_amount = abs(base.get("uiAmount", 0))

    return {
        "tx_signature": trade["txHash"],
        "wallet_address": trade["owner"],
        "token_mint": token_mint,
        "timestamp": ts,
        "side": trade["side"],
        "amount_tokens": token_amount,
        "amount_sol": sol_amount,
        "price_usd": price_usd,
    }


async def backfill_token(
    birdeye: BirdeyeClient,
    mint_address: str,
    db,
    announced_at: datetime | None = None,
) -> int:
    """Pull all swap trades for a token via Birdeye and save to database.

    Uses ascending sort (oldest first) so we naturally walk from token
    creation through announcement.
    """
    all_trades = []
    offset = 0

    # We want all trades up to announcement + 24h (to capture immediate post-announcement)
    cutoff_ts = None
    if announced_at:
        cutoff_ts = announced_at + timedelta(hours=24)

    max_offset = 9950  # Birdeye caps at 10K offset
    while offset <= max_offset:
        try:
            items = await birdeye.get_token_trades(
                mint_address, offset=offset, limit=BATCH_SIZE, sort_type="asc"
            )
        except httpx.HTTPStatusError as e:
            if e.response.status_code == 400:
                log.info("birdeye_offset_limit", token=mint_address[:12], offset=offset)
                break
            if e.response.status_code in (429, 502, 503, 504):
                log.warning("birdeye_rate_limit", status=e.response.status_code, offset=offset)
                await asyncio.sleep(3)
                continue
            raise
        except (httpx.ReadError, httpx.ReadTimeout, httpx.ConnectError):
            log.warning("birdeye_network_error", token=mint_address[:12], offset=offset)
            await asyncio.sleep(3)
            continue

        if not items:
            break

        reached_cutoff = False
        for item in items:
            parsed = parse_birdeye_trade(item, mint_address)
            if cutoff_ts and parsed["timestamp"] > cutoff_ts:
                reached_cutoff = True
                break
            all_trades.append(parsed)

        offset += len(items)

        if offset % 200 == 0:
            oldest = all_trades[0]["timestamp"].strftime("%Y-%m-%d %H:%M") if all_trades else "?"
            newest = all_trades[-1]["timestamp"].strftime("%Y-%m-%d %H:%M") if all_trades else "?"
            log.info("backfill_progress", token=mint_address[:12],
                     trades=len(all_trades), range=f"{oldest} -> {newest}")

        if reached_cutoff:
            log.info("reached_cutoff", token=mint_address[:12], trades=len(all_trades))
            break

        if len(items) < BATCH_SIZE:
            break

        await asyncio.sleep(0.3)

    log.info("backfill_pulled", token=mint_address[:12], total_trades=len(all_trades))

    # Save to database
    saved = 0
    for trade_data in all_trades:
        # Upsert wallet
        wallet = db.get(Wallet, trade_data["wallet_address"])
        if not wallet:
            wallet = Wallet(
                address=trade_data["wallet_address"],
                first_seen=trade_data["timestamp"],
                category="unknown",
            )
            db.add(wallet)

        # Skip duplicates
        existing = db.query(Trade).filter_by(tx_signature=trade_data["tx_signature"]).first()
        if existing:
            continue

        trade = Trade(
            tx_signature=trade_data["tx_signature"],
            wallet_address=trade_data["wallet_address"],
            token_mint=trade_data["token_mint"],
            timestamp=trade_data["timestamp"],
            side=trade_data["side"],
            amount_tokens=trade_data["amount_tokens"],
            amount_sol=trade_data["amount_sol"],
            price_usd=trade_data["price_usd"],
        )
        db.add(trade)
        saved += 1

    db.commit()

    # Compute seconds_before_announcement for each trade
    token = db.get(Token, mint_address)
    if token and token.announced_at:
        trades = db.query(Trade).filter_by(token_mint=mint_address).all()
        for trade in trades:
            delta = (token.announced_at - trade.timestamp).total_seconds()
            trade.seconds_before_announcement = int(delta)
        db.commit()

    return saved


@click.command()
@click.option("--tokens-file", required=True, help="Path to JSON file with token list")
@click.option("--create-db", is_flag=True, help="Create database tables first")
def main(tokens_file: str, create_db: bool):
    """Backfill historical trade data for a list of tokens."""
    if create_db:
        create_tables()

    tokens_path = Path(tokens_file)
    if not tokens_path.exists():
        log.error("tokens_file_not_found", path=str(tokens_path))
        return

    with open(tokens_path) as f:
        tokens = json.load(f)

    log.info("starting_backfill", token_count=len(tokens))

    async def run():
        birdeye = BirdeyeClient()
        db = SessionLocal()

        try:
            for token_data in tokens:
                mint = token_data["mint_address"]

                # Upsert token record
                token = db.get(Token, mint)
                if not token:
                    token = Token(
                        mint_address=mint,
                        name=token_data.get("name", ""),
                        symbol=token_data.get("symbol", ""),
                        platform=token_data.get("platform", "moonshot"),
                        announced_at=datetime.fromisoformat(token_data["announced_at"])
                        if token_data.get("announced_at") else None,
                        is_historical=True,
                    )
                    db.add(token)
                    db.commit()

                saved = await backfill_token(birdeye, mint, db, announced_at=token.announced_at)
                log.info("token_backfilled", token=mint[:12], symbol=token_data.get("symbol"), trades_saved=saved)

        finally:
            db.close()
            await birdeye.close()

    asyncio.run(run())


if __name__ == "__main__":
    main()
