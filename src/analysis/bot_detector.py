"""Bot detection heuristics for Solana wallets."""

from sqlalchemy import func
from sqlalchemy.orm import Session

from src.db.models import Trade
from src.constants import (
    BOT_MAX_TOTAL_TRADES,
    BOT_MAX_DUST_TRADE_RATIO,
    BOT_DUST_THRESHOLD_SOL,
)


def detect_bot(wallet_address: str, db: Session) -> dict:
    """Check if a wallet is likely a bot.

    Returns:
        {
            "is_bot": bool,
            "total_trades": int,
            "dust_ratio": float,
            "reasons": list[str],
        }
    """
    total_trades = db.query(func.count(Trade.id)).filter(
        Trade.wallet_address == wallet_address
    ).scalar() or 0

    dust_count = db.query(func.count(Trade.id)).filter(
        Trade.wallet_address == wallet_address,
        Trade.amount_sol < BOT_DUST_THRESHOLD_SOL,
        Trade.amount_sol.isnot(None),
    ).scalar() or 0

    total_with_sol = db.query(func.count(Trade.id)).filter(
        Trade.wallet_address == wallet_address,
        Trade.amount_sol.isnot(None),
    ).scalar() or 1

    dust_ratio = dust_count / total_with_sol

    reasons = []
    if total_trades >= BOT_MAX_TOTAL_TRADES:
        reasons.append(f"high_tx_count:{total_trades}")
    if dust_ratio > BOT_MAX_DUST_TRADE_RATIO:
        reasons.append(f"dust_ratio:{dust_ratio:.2f}")

    return {
        "is_bot": len(reasons) > 0,
        "total_trades": total_trades,
        "dust_ratio": round(dust_ratio, 4),
        "reasons": reasons,
    }
