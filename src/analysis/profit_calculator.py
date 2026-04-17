"""Realized profit and hold-status calculator.

For each wallet+token pair:
1. Build the pre-announcement inventory position
2. Walk later sells and match only the early inventory
3. Classify: holding, sold_profit, or sold_loss
"""

from sqlalchemy.orm import Session

from src.db.models import Trade, Token
from src.constants import MIN_HOLD_RATIO


def compute_outcome(wallet_address: str, token_mint: str, db: Session) -> dict:
    """Compute the outcome for a wallet on a specific token.

    Returns:
        {
            "status": "holding" | "sold_profit" | "sold_loss" | "no_data",
            "tokens_bought": float,
            "tokens_sold": float,
            "tokens_remaining": float,
            "sol_spent": float,
            "sol_received": float,
            "realized_profit_sol": float,
        }
    """
    token = db.get(Token, token_mint)
    if not token or not token.announced_at:
        return {"status": "no_data"}

    # Pre-announcement buys define the position we want to evaluate.
    buys = (
        db.query(Trade)
        .filter(
            Trade.wallet_address == wallet_address,
            Trade.token_mint == token_mint,
            Trade.side == "buy",
            Trade.seconds_before_announcement > 0,
        )
        .all()
    )

    if not buys:
        return {"status": "no_data"}

    tokens_bought = sum(t.amount_tokens or 0 for t in buys)
    sol_spent = sum(t.amount_sol or 0 for t in buys)

    # Walk later sells in time order and only count the portion that closes
    # the pre-announcement position. Post-announcement buys are intentionally
    # ignored so they do not distort the early-position outcome.
    sells = (
        db.query(Trade)
        .filter(
            Trade.wallet_address == wallet_address,
            Trade.token_mint == token_mint,
            Trade.side == "sell",
        )
        .order_by(Trade.timestamp.asc(), Trade.id.asc())
        .all()
    )

    tokens_sold = 0.0
    sol_received = 0.0
    early_inventory = tokens_bought

    for sell in sells:
        if early_inventory <= 0:
            break

        sell_tokens = sell.amount_tokens or 0.0
        sell_sol = sell.amount_sol or 0.0
        if sell_tokens <= 0:
            continue

        matched_tokens = min(sell_tokens, early_inventory)
        matched_ratio = matched_tokens / sell_tokens

        tokens_sold += matched_tokens
        sol_received += sell_sol * matched_ratio
        early_inventory -= matched_tokens

    tokens_remaining = max(0.0, early_inventory)

    # Classify
    if tokens_bought > 0 and tokens_remaining > tokens_bought * MIN_HOLD_RATIO:
        status = "holding"
    elif sol_received > sol_spent:
        status = "sold_profit"
    else:
        status = "sold_loss"

    return {
        "status": status,
        "tokens_bought": round(tokens_bought, 4),
        "tokens_sold": round(tokens_sold, 4),
        "tokens_remaining": round(tokens_remaining, 4),
        "sol_spent": round(sol_spent, 6),
        "sol_received": round(sol_received, 6),
        "realized_profit_sol": round(sol_received - sol_spent, 6),
    }
