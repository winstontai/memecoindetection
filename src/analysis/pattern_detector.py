"""Pattern detection engine.

Identifies behavioral patterns among early buyers that can be used
to detect similar activity on new tokens, even from unknown wallets.
"""

from datetime import datetime, timedelta
from dataclasses import dataclass
from sqlalchemy.orm import Session

from src.db.models import Trade, Token, FundingLink
from src.constants import CLUSTER_WINDOW_SECONDS, CLUSTER_MIN_WALLETS


@dataclass
class PatternMatch:
    pattern_name: str
    score: float          # 0-100
    description: str
    evidence: dict


def detect_buy_clustering(
    trades: list[dict],
    window_seconds: int = CLUSTER_WINDOW_SECONDS,
    min_wallets: int = CLUSTER_MIN_WALLETS,
) -> PatternMatch | None:
    """Detect if multiple unique wallets bought within a tight time window.

    This is the strongest early signal - coordinated buying from
    multiple wallets in quick succession.

    Args:
        trades: List of trade dicts with 'wallet_address' and 'timestamp'.
        window_seconds: Time window to check for clustering.
        min_wallets: Minimum unique wallets to count as a cluster.
    """
    if len(trades) < min_wallets:
        return None

    buy_trades = [t for t in trades if t["side"] == "buy"]
    buy_trades.sort(key=lambda t: t["timestamp"])

    best_cluster = []
    for i, trade in enumerate(buy_trades):
        window_end = trade["timestamp"] + timedelta(seconds=window_seconds)
        cluster_wallets = set()
        cluster_trades = []

        for j in range(i, len(buy_trades)):
            if buy_trades[j]["timestamp"] <= window_end:
                cluster_wallets.add(buy_trades[j]["wallet_address"])
                cluster_trades.append(buy_trades[j])
            else:
                break

        if len(cluster_wallets) >= min_wallets and len(cluster_wallets) > len(best_cluster):
            best_cluster = list(cluster_wallets)

    if len(best_cluster) >= min_wallets:
        score = min(100, (len(best_cluster) / min_wallets) * 50 + 30)
        return PatternMatch(
            pattern_name="buy_clustering",
            score=score,
            description=f"{len(best_cluster)} unique wallets bought within {window_seconds}s",
            evidence={
                "wallet_count": len(best_cluster),
                "wallets": best_cluster[:10],
                "window_seconds": window_seconds,
            },
        )
    return None


def detect_early_timing(
    trades: list[dict],
    pool_created_at: datetime,
) -> PatternMatch | None:
    """Detect buys that happen suspiciously fast after pool creation.

    Buying within the first few blocks of a pool suggests automated
    sniping or insider knowledge.
    """
    buy_trades = [t for t in trades if t["side"] == "buy"]
    if not buy_trades:
        return None

    early_buys = []
    for trade in buy_trades:
        seconds_after_pool = (trade["timestamp"] - pool_created_at).total_seconds()
        if 0 < seconds_after_pool < 60:  # Within first minute
            early_buys.append({
                "wallet": trade["wallet_address"],
                "seconds_after_pool": seconds_after_pool,
            })

    if not early_buys:
        return None

    # More early buys = stronger signal
    score = min(100, len(early_buys) * 25)
    return PatternMatch(
        pattern_name="early_timing",
        score=score,
        description=f"{len(early_buys)} buys within 60s of pool creation",
        evidence={
            "early_buys": early_buys[:10],
            "pool_created_at": pool_created_at.isoformat(),
        },
    )


def detect_funding_cluster(
    wallet_addresses: list[str],
    db: Session,
    min_shared_funder: int = 2,
) -> PatternMatch | None:
    """Detect if multiple early buyers were funded by the same source.

    This suggests coordinated wallets controlled by the same entity.
    """
    funding = (
        db.query(FundingLink.wallet_address, FundingLink.funder_address)
        .filter(FundingLink.wallet_address.in_(wallet_addresses))
        .all()
    )

    if not funding:
        return None

    # Count how many tracked wallets each funder funded
    funder_counts: dict[str, list[str]] = {}
    for wallet, funder in funding:
        funder_counts.setdefault(funder, []).append(wallet)

    # Find funders that funded multiple early buyers
    shared_funders = {
        funder: wallets
        for funder, wallets in funder_counts.items()
        if len(wallets) >= min_shared_funder
    }

    if not shared_funders:
        return None

    max_shared = max(len(w) for w in shared_funders.values())
    score = min(100, max_shared * 30)

    return PatternMatch(
        pattern_name="funding_cluster",
        score=score,
        description=f"{len(shared_funders)} funding sources linked to multiple early buyers",
        evidence={
            "shared_funders": {
                funder: wallets[:5]
                for funder, wallets in shared_funders.items()
            },
        },
    )


def detect_size_pattern(
    trades: list[dict],
    typical_range_sol: tuple[float, float] = (0.5, 5.0),
) -> PatternMatch | None:
    """Detect if early buy sizes match the typical 'insider' range.

    Historical analysis shows insiders tend to buy in a consistent
    range - not too small (noise) and not too large (obvious).
    """
    buy_trades = [t for t in trades if t["side"] == "buy" and t.get("amount_sol")]
    if not buy_trades:
        return None

    in_range = [
        t for t in buy_trades
        if typical_range_sol[0] <= t["amount_sol"] <= typical_range_sol[1]
    ]

    if not in_range:
        return None

    ratio = len(in_range) / len(buy_trades)
    if ratio < 0.3:
        return None

    score = ratio * 70
    return PatternMatch(
        pattern_name="size_pattern",
        score=score,
        description=f"{len(in_range)}/{len(buy_trades)} buys in {typical_range_sol[0]}-{typical_range_sol[1]} SOL range",
        evidence={
            "in_range_count": len(in_range),
            "total_buys": len(buy_trades),
            "ratio": round(ratio, 2),
            "range_sol": typical_range_sol,
        },
    )


def run_all_detectors(
    trades: list[dict],
    pool_created_at: datetime | None = None,
    wallet_addresses: list[str] | None = None,
    db: Session | None = None,
) -> list[PatternMatch]:
    """Run all pattern detectors and return matches.

    This is the main entry point for pattern detection.
    """
    results = []

    clustering = detect_buy_clustering(trades)
    if clustering:
        results.append(clustering)

    if pool_created_at:
        timing = detect_early_timing(trades, pool_created_at)
        if timing:
            results.append(timing)

    if wallet_addresses and db:
        funding = detect_funding_cluster(wallet_addresses, db)
        if funding:
            results.append(funding)

    size = detect_size_pattern(trades)
    if size:
        results.append(size)

    return results
