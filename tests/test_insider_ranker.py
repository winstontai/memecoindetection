from datetime import datetime, timedelta

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from src.analysis.insider_ranker import rank_insider_wallets
from src.db.models import Base, FundingLink, Token, Trade, Wallet


def make_session():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    session_factory = sessionmaker(bind=engine)
    return session_factory()


def add_wallet(db, address: str, first_seen: datetime):
    db.add(Wallet(address=address, category="unknown", first_seen=first_seen))


def add_token(db, mint: str, announced_at: datetime):
    db.add(
        Token(
            mint_address=mint,
            name=mint,
            symbol=mint[:3].upper(),
            announced_at=announced_at,
            is_historical=True,
        )
    )


def add_trade(
    db,
    *,
    tx_signature: str,
    wallet_address: str,
    token_mint: str,
    timestamp: datetime,
    side: str,
    amount_tokens: float,
    amount_sol: float,
    seconds_before_announcement: int | None,
):
    db.add(
        Trade(
            tx_signature=tx_signature,
            wallet_address=wallet_address,
            token_mint=token_mint,
            timestamp=timestamp,
            side=side,
            amount_tokens=amount_tokens,
            amount_sol=amount_sol,
            seconds_before_announcement=seconds_before_announcement,
        )
    )


def test_rank_insider_wallets_flags_selective_profitable_wallet():
    db = make_session()
    base_time = datetime(2026, 1, 1, 12, 0, 0)

    add_wallet(db, "wallet1", base_time)
    add_wallet(db, "wallet2", base_time)
    for mint, offset in [("tokenA", 0), ("tokenB", 1), ("tokenC", 2)]:
        add_token(db, mint, base_time + timedelta(days=offset))

    add_trade(
        db,
        tx_signature="a-buy",
        wallet_address="wallet1",
        token_mint="tokenA",
        timestamp=base_time - timedelta(minutes=10),
        side="buy",
        amount_tokens=10.0,
        amount_sol=1.0,
        seconds_before_announcement=600,
    )
    add_trade(
        db,
        tx_signature="a-sell",
        wallet_address="wallet1",
        token_mint="tokenA",
        timestamp=base_time + timedelta(minutes=5),
        side="sell",
        amount_tokens=10.0,
        amount_sol=2.0,
        seconds_before_announcement=-300,
    )
    add_trade(
        db,
        tx_signature="b-buy",
        wallet_address="wallet1",
        token_mint="tokenB",
        timestamp=base_time + timedelta(days=1, minutes=-20),
        side="buy",
        amount_tokens=12.0,
        amount_sol=1.2,
        seconds_before_announcement=1200,
    )
    add_trade(
        db,
        tx_signature="b-sell",
        wallet_address="wallet1",
        token_mint="tokenB",
        timestamp=base_time + timedelta(days=1, minutes=15),
        side="sell",
        amount_tokens=12.0,
        amount_sol=2.4,
        seconds_before_announcement=-900,
    )
    add_trade(
        db,
        tx_signature="c-buy",
        wallet_address="wallet1",
        token_mint="tokenC",
        timestamp=base_time + timedelta(days=2, minutes=-30),
        side="buy",
        amount_tokens=20.0,
        amount_sol=2.0,
        seconds_before_announcement=1800,
    )

    add_trade(
        db,
        tx_signature="peer-buy",
        wallet_address="wallet2",
        token_mint="tokenA",
        timestamp=base_time - timedelta(minutes=9),
        side="buy",
        amount_tokens=5.0,
        amount_sol=0.8,
        seconds_before_announcement=540,
    )

    db.add(FundingLink(wallet_address="wallet1", funder_address="shared-funder"))
    db.add(FundingLink(wallet_address="wallet2", funder_address="shared-funder"))
    db.commit()

    scores = {ws.wallet_address: ws for ws in rank_insider_wallets(db)}
    wallet_score = scores["wallet1"]

    assert wallet_score.is_bot is False
    assert wallet_score.tokens_analyzed == 3
    assert wallet_score.tokens_profitable == 2
    assert wallet_score.tokens_holding == 1
    assert wallet_score.tokens_at_loss == 0
    assert wallet_score.passes_strict_filter is True
    assert wallet_score.overall_score > 60


def test_rank_insider_wallets_penalizes_bot_like_wallet():
    db = make_session()
    base_time = datetime(2026, 1, 1, 12, 0, 0)

    add_wallet(db, "spamwallet", base_time)
    for mint, offset in [("tokenA", 0), ("tokenB", 1), ("tokenC", 2)]:
        add_token(db, mint, base_time + timedelta(days=offset))

    add_trade(
        db,
        tx_signature="spam-a-buy",
        wallet_address="spamwallet",
        token_mint="tokenA",
        timestamp=base_time - timedelta(minutes=10),
        side="buy",
        amount_tokens=10.0,
        amount_sol=1.0,
        seconds_before_announcement=600,
    )
    add_trade(
        db,
        tx_signature="spam-b-buy",
        wallet_address="spamwallet",
        token_mint="tokenB",
        timestamp=base_time + timedelta(days=1, minutes=-10),
        side="buy",
        amount_tokens=10.0,
        amount_sol=1.0,
        seconds_before_announcement=600,
    )
    add_trade(
        db,
        tx_signature="spam-c-buy",
        wallet_address="spamwallet",
        token_mint="tokenC",
        timestamp=base_time + timedelta(days=2, minutes=-10),
        side="buy",
        amount_tokens=10.0,
        amount_sol=1.0,
        seconds_before_announcement=600,
    )

    extra_trades = []
    for i in range(497):
        extra_trades.append(
            Trade(
                tx_signature=f"spam-dust-{i}",
                wallet_address="spamwallet",
                token_mint="tokenA",
                timestamp=base_time + timedelta(minutes=i),
                side="buy",
                amount_tokens=1.0,
                amount_sol=0.001,
                seconds_before_announcement=-i,
            )
        )

    db.add_all(extra_trades)
    db.commit()

    scores = {ws.wallet_address: ws for ws in rank_insider_wallets(db)}
    wallet_score = scores["spamwallet"]

    assert wallet_score.is_bot is True
    assert wallet_score.total_trades == 500
    assert wallet_score.passes_strict_filter is False
    assert wallet_score.overall_score <= 10
