"""Signal generator - combines wallet scores and pattern detection into actionable signals."""

from datetime import datetime
from sqlalchemy.orm import Session

from src.db.models import Token, Trade, WalletScore, TokenSignal
from src.analysis.pattern_detector import run_all_detectors
from src.constants import (
    SIGNAL_KNOWN_WALLET_WEIGHT, SIGNAL_BUY_CLUSTERING_WEIGHT,
    SIGNAL_TIMING_PATTERN_WEIGHT, SIGNAL_FUNDING_PATTERN_WEIGHT,
    SIGNAL_VOLUME_PATTERN_WEIGHT, SIGNAL_ALERT_THRESHOLD,
)


def generate_signal(
    token_mint: str,
    trades: list[dict],
    db: Session,
    pool_created_at: datetime | None = None,
) -> TokenSignal | None:
    """Analyze a token's early trading activity and generate a signal if warranted.

    This is called for each new token being monitored.

    Args:
        token_mint: The token's mint address.
        trades: List of trade dicts for this token.
        db: Database session.
        pool_created_at: When the liquidity pool was created.

    Returns:
        TokenSignal if the score exceeds threshold, None otherwise.
    """
    if not trades:
        return None

    buy_trades = [t for t in trades if t["side"] == "buy"]
    if not buy_trades:
        return None

    early_wallets = list({t["wallet_address"] for t in buy_trades})

    # 1. Check for known high-score wallets
    known_scores = (
        db.query(WalletScore)
        .filter(WalletScore.wallet_address.in_(early_wallets))
        .all()
    )

    known_wallet_score = 0.0
    matched_wallets = []
    if known_scores:
        # Weighted average of known wallet scores, capped at 100
        total_weight = 0
        weighted_sum = 0
        for ws in known_scores:
            weighted_sum += ws.overall_score * ws.overall_score  # Self-weighted
            total_weight += ws.overall_score
            matched_wallets.append({
                "address": ws.wallet_address,
                "score": ws.overall_score,
            })
        known_wallet_score = min(100, weighted_sum / total_weight if total_weight else 0)

    # 2. Run pattern detectors
    patterns = run_all_detectors(
        trades=trades,
        pool_created_at=pool_created_at,
        wallet_addresses=early_wallets,
        db=db,
    )

    pattern_scores = {p.pattern_name: p.score for p in patterns}

    # 3. Compute composite signal score
    clustering_score = pattern_scores.get("buy_clustering", 0)
    timing_score = pattern_scores.get("early_timing", 0)
    funding_score = pattern_scores.get("funding_cluster", 0)
    size_score = pattern_scores.get("size_pattern", 0)

    # Volume/size pattern serves as the volume component for now
    composite = (
        known_wallet_score * SIGNAL_KNOWN_WALLET_WEIGHT +
        clustering_score * SIGNAL_BUY_CLUSTERING_WEIGHT +
        timing_score * SIGNAL_TIMING_PATTERN_WEIGHT +
        funding_score * SIGNAL_FUNDING_PATTERN_WEIGHT +
        size_score * SIGNAL_VOLUME_PATTERN_WEIGHT
    )

    if composite < SIGNAL_ALERT_THRESHOLD:
        return None

    # 4. Build the signal
    reasons = []
    if matched_wallets:
        top = sorted(matched_wallets, key=lambda w: w["score"], reverse=True)[:3]
        reasons.append(f"Known wallets: {', '.join(w['address'][:8] + '...' for w in top)}")
    for pattern in patterns:
        reasons.append(f"{pattern.pattern_name}: {pattern.description}")

    signal = TokenSignal(
        token_mint=token_mint,
        signal_type="composite",
        score=round(composite, 2),
        triggered_at=datetime.utcnow(),
        reason=" | ".join(reasons),
        details={
            "component_scores": {
                "known_wallet": round(known_wallet_score, 2),
                "buy_clustering": round(clustering_score, 2),
                "early_timing": round(timing_score, 2),
                "funding_cluster": round(funding_score, 2),
                "size_pattern": round(size_score, 2),
            },
            "wallets_matched": matched_wallets,
            "patterns_matched": [p.pattern_name for p in patterns],
            "total_early_buyers": len(early_wallets),
        },
        outcome="pending",
    )

    return signal
