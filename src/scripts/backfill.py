"""Historical backfill script.

Pulls trade data for a list of known tokens and populates the database.
This is the first script you run to seed the system with historical data.

Usage:
    python -m src.scripts.backfill --tokens-file data/seed_tokens.json
"""

import asyncio
import json
import click
import structlog
from datetime import datetime
from pathlib import Path

from src.db.engine import SessionLocal
from src.db.models import Base, Token, Wallet, Trade
from src.db.engine import engine
from src.ingestion.helius import HeliusClient
from src.monitor.live_scanner import LiveScanner

log = structlog.get_logger()


def create_tables():
    """Create all database tables."""
    Base.metadata.create_all(engine)
    log.info("database_tables_created")


async def backfill_token(helius: HeliusClient, mint_address: str, db) -> int:
    """Pull all swap transactions for a token and save to database.

    Returns number of trades saved.
    """
    scanner = LiveScanner()
    all_trades = []
    last_sig = None

    # Paginate through all transactions
    while True:
        txs = await helius.get_token_transactions(
            mint_address, before_signature=last_sig, limit=100
        )
        if not txs:
            break

        for tx in txs:
            parsed = scanner._parse_helius_swap(tx, mint_address)
            if parsed:
                all_trades.append(parsed)

        last_sig = txs[-1].get("signature")
        if len(txs) < 100:
            break

    log.info("backfill_pulled", token=mint_address, trades=len(all_trades))

    # Save to database
    saved = 0
    for trade_data in all_trades:
        # Upsert wallet
        wallet = db.query(Wallet).get(trade_data["wallet_address"])
        if not wallet:
            wallet = Wallet(
                address=trade_data["wallet_address"],
                first_seen=trade_data["timestamp"],
                category="unknown",
            )
            db.add(wallet)

        # Check for duplicate trade
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

    # Update seconds_before_announcement for trades
    token = db.query(Token).get(mint_address)
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
        helius = HeliusClient()
        db = SessionLocal()

        try:
            for token_data in tokens:
                mint = token_data["mint_address"]

                # Upsert token record
                token = db.query(Token).get(mint)
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

                saved = await backfill_token(helius, mint, db)
                log.info("token_backfilled", token=mint, trades_saved=saved)

        finally:
            db.close()
            await helius.close()

    asyncio.run(run())


if __name__ == "__main__":
    main()
