"""Wallet scoring engine.

Scores wallets based on their historical behavior across tracked tokens.
Each component score is 0-100, combined into a weighted overall score.
"""

from datetime import datetime
from sqlalchemy import func, and_
from sqlalchemy.orm import Session

from src.db.models import Wallet, Trade, Token, WalletScore
from src.constants import (
    WALLET_TIMING_WEIGHT, WALLET_PROFIT_WEIGHT,
    WALLET_FREQUENCY_WEIGHT, WALLET_CONSISTENCY_WEIGHT,
    TIMING_BUCKETS, MIN_EARLY_TOKENS,
    MAX_SECONDS_BEFORE_ANNOUNCEMENT,
)


def score_timing(seconds_before: list[int]) -> float:
    """Score how early the wallet tends to buy before announcements.

    Args:
        seconds_before: List of seconds-before-announcement for each early buy.
                        Positive = before announcement.

    Returns:
        Score 0-100. Higher = consistently earlier.
    """
    if not seconds_before:
        return 0.0

    scores = []
    for secs in seconds_before:
        if secs <= 0:
            scores.append(0)
            continue
        score = 10  # Default for very early (> 7 days)
        for threshold, bucket_score in TIMING_BUCKETS:
            if secs <= threshold:
                score = bucket_score
                break
        scores.append(score)

    return sum(scores) / len(scores)


def score_profit(profits_usd: list[float]) -> float:
    """Score average profit on early buys.

    Args:
        profits_usd: List of USD profit per early buy.

    Returns:
        Score 0-100. Capped to prevent outlier distortion.
    """
    if not profits_usd:
        return 0.0

    avg_profit = sum(profits_usd) / len(profits_usd)

    # Scale: $0 = 0, $100 = 30, $1K = 60, $10K = 80, $100K+ = 100
    if avg_profit <= 0:
        return 0.0
    elif avg_profit < 100:
        return (avg_profit / 100) * 30
    elif avg_profit < 1000:
        return 30 + ((avg_profit - 100) / 900) * 30
    elif avg_profit < 10000:
        return 60 + ((avg_profit - 1000) / 9000) * 20
    else:
        return min(80 + ((avg_profit - 10000) / 90000) * 20, 100.0)


def score_frequency(num_early_buys: int) -> float:
    """Score how many tokens the wallet was early on.

    Returns:
        Score 0-100.
    """
    # Scale: 1 = 15, 2 = 30, 5 = 55, 10 = 75, 20+ = 100
    if num_early_buys <= 0:
        return 0.0
    elif num_early_buys == 1:
        return 15.0
    elif num_early_buys <= 5:
        return 15 + (num_early_buys - 1) * 10
    elif num_early_buys <= 10:
        return 55 + (num_early_buys - 5) * 4
    elif num_early_buys <= 20:
        return 75 + (num_early_buys - 10) * 2.5
    else:
        return 100.0


def score_consistency(early_buys: int, total_early_attempts: int) -> float:
    """Score what percentage of the wallet's early buys were on tokens that succeeded.

    Args:
        early_buys: Number of early buys on tokens that got announced.
        total_early_attempts: Total early buys including tokens that never got announced.

    Returns:
        Score 0-100.
    """
    if total_early_attempts == 0:
        return 0.0
    ratio = early_buys / total_early_attempts
    return ratio * 100


def compute_wallet_score(
    timing_scores: list[int],
    profits: list[float],
    num_early_buys: int,
    total_early_attempts: int,
) -> dict:
    """Compute full wallet score breakdown.

    Returns:
        Dict with component scores and overall score.
    """
    t = score_timing(timing_scores)
    p = score_profit(profits)
    f = score_frequency(num_early_buys)
    c = score_consistency(num_early_buys, total_early_attempts)

    overall = (
        t * WALLET_TIMING_WEIGHT +
        p * WALLET_PROFIT_WEIGHT +
        f * WALLET_FREQUENCY_WEIGHT +
        c * WALLET_CONSISTENCY_WEIGHT
    )

    return {
        "timing_score": round(t, 2),
        "profit_score": round(p, 2),
        "frequency_score": round(f, 2),
        "consistency_score": round(c, 2),
        "overall_score": round(overall, 2),
    }


def score_all_wallets(db: Session) -> list[WalletScore]:
    """Score all wallets that have enough historical data.

    This is the main entry point for batch scoring.
    Queries the database for early-buyer wallets and scores them.
    """
    # Find wallets with early buys on announced tokens
    early_trades = (
        db.query(
            Trade.wallet_address,
            Trade.token_mint,
            Trade.seconds_before_announcement,
            Trade.amount_sol,
            Trade.price_usd,
        )
        .join(Token, Trade.token_mint == Token.mint_address)
        .filter(
            Trade.side == "buy",
            Trade.seconds_before_announcement > 0,
            Trade.seconds_before_announcement <= MAX_SECONDS_BEFORE_ANNOUNCEMENT,
            Token.announced_at.isnot(None),
        )
        .all()
    )

    # Group by wallet
    wallet_data: dict[str, dict] = {}
    for wallet_addr, token_mint, secs_before, amount_sol, price_usd in early_trades:
        if wallet_addr not in wallet_data:
            wallet_data[wallet_addr] = {
                "timings": [],
                "profits": [],
                "tokens": set(),
            }
        wallet_data[wallet_addr]["timings"].append(secs_before)
        wallet_data[wallet_addr]["tokens"].add(token_mint)
        # Simplified profit: we'll compute actual profit in a later phase
        # For now, use amount_sol as a proxy
        wallet_data[wallet_addr]["profits"].append(amount_sol or 0)

    results = []
    for wallet_addr, data in wallet_data.items():
        num_tokens = len(data["tokens"])
        if num_tokens < MIN_EARLY_TOKENS:
            continue

        scores = compute_wallet_score(
            timing_scores=data["timings"],
            profits=data["profits"],
            num_early_buys=num_tokens,
            total_early_attempts=num_tokens,  # Refined later with non-announced tokens
        )

        wallet_score = WalletScore(
            wallet_address=wallet_addr,
            timing_score=scores["timing_score"],
            profit_score=scores["profit_score"],
            frequency_score=scores["frequency_score"],
            consistency_score=scores["consistency_score"],
            overall_score=scores["overall_score"],
            tokens_analyzed=num_tokens,
            scored_at=datetime.utcnow(),
        )
        results.append(wallet_score)

    return results
