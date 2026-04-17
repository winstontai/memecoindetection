from datetime import datetime, timedelta

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from src.analysis.bot_detector import detect_bot
from src.analysis.profit_calculator import compute_outcome
from src.db.models import Base, Token, Trade, Wallet


def make_session():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    session_factory = sessionmaker(bind=engine)
    return session_factory()


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


def seed_wallet_and_token(db):
    announced_at = datetime(2026, 1, 1, 12, 0, 0)
    wallet = Wallet(address="wallet1", category="unknown", first_seen=announced_at)
    token = Token(
        mint_address="token1",
        name="Token One",
        symbol="ONE",
        announced_at=announced_at,
        is_historical=True,
    )
    db.add_all([wallet, token])
    db.commit()
    return announced_at


def test_compute_outcome_ignores_post_announcement_rebuy_inventory():
    db = make_session()
    announced_at = seed_wallet_and_token(db)

    add_trade(
        db,
        tx_signature="buy-early",
        wallet_address="wallet1",
        token_mint="token1",
        timestamp=announced_at - timedelta(hours=1),
        side="buy",
        amount_tokens=10.0,
        amount_sol=1.0,
        seconds_before_announcement=3600,
    )
    add_trade(
        db,
        tx_signature="buy-late",
        wallet_address="wallet1",
        token_mint="token1",
        timestamp=announced_at + timedelta(minutes=5),
        side="buy",
        amount_tokens=1000.0,
        amount_sol=10.0,
        seconds_before_announcement=-300,
    )
    add_trade(
        db,
        tx_signature="sell-late",
        wallet_address="wallet1",
        token_mint="token1",
        timestamp=announced_at + timedelta(minutes=10),
        side="sell",
        amount_tokens=1000.0,
        amount_sol=20.0,
        seconds_before_announcement=-600,
    )
    db.commit()

    outcome = compute_outcome("wallet1", "token1", db)

    assert outcome["status"] == "sold_loss"
    assert outcome["tokens_bought"] == 10.0
    assert outcome["tokens_sold"] == 10.0
    assert outcome["tokens_remaining"] == 0.0
    assert outcome["sol_received"] == 0.2
    assert outcome["realized_profit_sol"] == -0.8


def test_compute_outcome_prorates_partial_sell_to_early_inventory():
    db = make_session()
    announced_at = seed_wallet_and_token(db)

    add_trade(
        db,
        tx_signature="buy-early",
        wallet_address="wallet1",
        token_mint="token1",
        timestamp=announced_at - timedelta(hours=2),
        side="buy",
        amount_tokens=10.0,
        amount_sol=1.0,
        seconds_before_announcement=7200,
    )
    add_trade(
        db,
        tx_signature="sell-mixed",
        wallet_address="wallet1",
        token_mint="token1",
        timestamp=announced_at + timedelta(minutes=15),
        side="sell",
        amount_tokens=25.0,
        amount_sol=5.0,
        seconds_before_announcement=-900,
    )
    db.commit()

    outcome = compute_outcome("wallet1", "token1", db)

    assert outcome["status"] == "sold_profit"
    assert outcome["tokens_sold"] == 10.0
    assert outcome["tokens_remaining"] == 0.0
    assert outcome["sol_received"] == 2.0
    assert outcome["realized_profit_sol"] == 1.0


def test_detect_bot_flags_exact_trade_threshold():
    db = make_session()
    announced_at = seed_wallet_and_token(db)

    trades = []
    for i in range(500):
        trades.append(
            Trade(
                tx_signature=f"tx-{i}",
                wallet_address="wallet1",
                token_mint="token1",
                timestamp=announced_at + timedelta(seconds=i),
                side="buy",
                amount_tokens=1.0,
                amount_sol=0.5,
                seconds_before_announcement=-i,
            )
        )

    db.add_all(trades)
    db.commit()

    result = detect_bot("wallet1", db)

    assert result["total_trades"] == 500
    assert result["is_bot"] is True
    assert "high_tx_count:500" in result["reasons"]
