"""Stricter insider-style wallet ranking.

This module ranks wallets that repeatedly buy before announcement and then
filters down to the ones that look selective, profitable, and non-bot-like.
"""

from datetime import UTC, datetime

from sqlalchemy import distinct, func
from sqlalchemy.orm import Session

from src.analysis.bot_detector import detect_bot
from src.analysis.profit_calculator import compute_outcome
from src.analysis.wallet_scorer import score_timing
from src.constants import (
    INSIDER_NETWORK_WEIGHT,
    INSIDER_OUTCOME_WEIGHT,
    INSIDER_REPEATABILITY_WEIGHT,
    INSIDER_SELECTIVITY_WEIGHT,
    INSIDER_TIMING_WEIGHT,
    MAX_SECONDS_BEFORE_ANNOUNCEMENT,
    MIN_EARLY_TOKENS,
    MIN_PROFITABLE_TOKEN_RATIO,
    MIN_STRICT_EARLY_TOKENS,
    MIN_STRICT_TIMING_SCORE,
)
from src.db.models import FundingLink, Token, Trade, WalletScore


def score_repeatability(num_early_tokens: int) -> float:
    """Score repeated pre-announcement participation across unique tokens."""
    if num_early_tokens <= 0:
        return 0.0
    if num_early_tokens == 1:
        return 20.0
    if num_early_tokens <= 3:
        return 20 + (num_early_tokens - 1) * 20
    if num_early_tokens <= 6:
        return 60 + (num_early_tokens - 3) * 10
    return 100.0


def score_outcome_quality(
    tokens_profitable: int,
    tokens_holding: int,
    total_tokens: int,
) -> float:
    """Reward wallets that profit or still hold meaningful size."""
    if total_tokens <= 0:
        return 0.0

    positive_weight = tokens_profitable + (tokens_holding * 0.7)
    return min(100.0, (positive_weight / total_tokens) * 100)


def score_selectivity(early_tokens: int, total_tokens_traded: int) -> float:
    """Reward wallets that are early on a meaningful share of what they trade."""
    if early_tokens <= 0 or total_tokens_traded <= 0:
        return 0.0

    ratio = early_tokens / total_tokens_traded
    return min(100.0, ratio * 100)


def score_network_linkage(shared_wallet_count: int) -> float:
    """Reward wallets linked to recurring funded clusters."""
    if shared_wallet_count <= 0:
        return 0.0
    return min(100.0, shared_wallet_count * 25)


def passes_strict_insider_filter(
    *,
    is_bot: bool,
    tokens_analyzed: int,
    timing_score: float,
    tokens_profitable: int,
    tokens_holding: int,
) -> bool:
    """Apply a high-precision filter for likely insiders."""
    if is_bot:
        return False
    if tokens_analyzed < MIN_STRICT_EARLY_TOKENS:
        return False
    if timing_score < MIN_STRICT_TIMING_SCORE:
        return False

    positive_ratio = (tokens_profitable + tokens_holding) / tokens_analyzed
    return positive_ratio >= MIN_PROFITABLE_TOKEN_RATIO


def get_shared_funder_wallet_count(wallet_address: str, db: Session) -> int:
    """Count other early-buyer wallets funded by the same source(s)."""
    funders = [
        row[0]
        for row in (
            db.query(distinct(FundingLink.funder_address))
            .filter(FundingLink.wallet_address == wallet_address)
            .all()
        )
        if row[0]
    ]
    if not funders:
        return 0

    shared_count = (
        db.query(func.count(distinct(FundingLink.wallet_address)))
        .join(Trade, Trade.wallet_address == FundingLink.wallet_address)
        .join(Token, Token.mint_address == Trade.token_mint)
        .filter(
            FundingLink.funder_address.in_(funders),
            FundingLink.wallet_address != wallet_address,
            Trade.side == "buy",
            Trade.seconds_before_announcement > 0,
            Trade.seconds_before_announcement <= MAX_SECONDS_BEFORE_ANNOUNCEMENT,
            Token.announced_at.isnot(None),
        )
        .scalar()
    )
    return shared_count or 0


def rank_insider_wallets(db: Session) -> list[WalletScore]:
    """Rank wallets by stricter insider-style heuristics."""
    early_rows = (
        db.query(
            Trade.wallet_address,
            Trade.token_mint,
            func.min(Trade.seconds_before_announcement).label("closest_buy_seconds"),
        )
        .join(Token, Token.mint_address == Trade.token_mint)
        .filter(
            Trade.side == "buy",
            Trade.seconds_before_announcement > 0,
            Trade.seconds_before_announcement <= MAX_SECONDS_BEFORE_ANNOUNCEMENT,
            Token.announced_at.isnot(None),
        )
        .group_by(Trade.wallet_address, Trade.token_mint)
        .all()
    )

    wallet_data: dict[str, dict] = {}
    for wallet_address, token_mint, closest_buy_seconds in early_rows:
        data = wallet_data.setdefault(
            wallet_address,
            {"timings": [], "tokens": []},
        )
        data["timings"].append(int(closest_buy_seconds))
        data["tokens"].append(token_mint)

    results = []
    for wallet_address, data in wallet_data.items():
        early_tokens = sorted(set(data["tokens"]))
        if len(early_tokens) < MIN_EARLY_TOKENS:
            continue

        outcome_summary = {}
        tokens_profitable = 0
        tokens_holding = 0
        tokens_at_loss = 0
        realized_profit_sol = 0.0

        for token_mint in early_tokens:
            outcome = compute_outcome(wallet_address, token_mint, db)
            outcome_summary[token_mint] = outcome

            status = outcome.get("status")
            if status == "sold_profit":
                tokens_profitable += 1
            elif status == "holding":
                tokens_holding += 1
            elif status == "sold_loss":
                tokens_at_loss += 1

            realized_profit_sol += outcome.get("realized_profit_sol", 0.0)

        bot_result = detect_bot(wallet_address, db)

        total_tokens_traded = (
            db.query(func.count(distinct(Trade.token_mint)))
            .filter(Trade.wallet_address == wallet_address)
            .scalar()
            or 0
        )
        shared_wallet_count = get_shared_funder_wallet_count(wallet_address, db)

        timing_score = score_timing(data["timings"])
        repeatability_score = score_repeatability(len(early_tokens))
        outcome_score = score_outcome_quality(
            tokens_profitable=tokens_profitable,
            tokens_holding=tokens_holding,
            total_tokens=len(early_tokens),
        )
        selectivity_score = score_selectivity(len(early_tokens), total_tokens_traded)
        network_score = score_network_linkage(shared_wallet_count)

        overall_score = (
            timing_score * INSIDER_TIMING_WEIGHT
            + repeatability_score * INSIDER_REPEATABILITY_WEIGHT
            + outcome_score * INSIDER_OUTCOME_WEIGHT
            + selectivity_score * INSIDER_SELECTIVITY_WEIGHT
            + network_score * INSIDER_NETWORK_WEIGHT
        )

        if bot_result["is_bot"]:
            overall_score = min(overall_score, 10.0)

        wallet_score = WalletScore(
            wallet_address=wallet_address,
            timing_score=round(timing_score, 2),
            profit_score=round(outcome_score, 2),
            frequency_score=round(repeatability_score, 2),
            consistency_score=round(selectivity_score, 2),
            overall_score=round(overall_score, 2),
            tokens_analyzed=len(early_tokens),
            scored_at=datetime.now(UTC).replace(tzinfo=None),
            is_bot=bot_result["is_bot"],
            total_trades=bot_result["total_trades"],
            dust_trade_ratio=bot_result["dust_ratio"],
            tokens_profitable=tokens_profitable,
            tokens_holding=tokens_holding,
            tokens_at_loss=tokens_at_loss,
            realized_profit_sol=round(realized_profit_sol, 6),
            outcome_summary=outcome_summary,
            passes_strict_filter=passes_strict_insider_filter(
                is_bot=bot_result["is_bot"],
                tokens_analyzed=len(early_tokens),
                timing_score=timing_score,
                tokens_profitable=tokens_profitable,
                tokens_holding=tokens_holding,
            ),
        )
        results.append(wallet_score)

    return results
