"""Run wallet scoring on all historical data.

Usage:
    python -m src.scripts.score_wallets
"""

import click
import structlog

from src.db.engine import SessionLocal
from src.db.models import WalletScore
from src.analysis.wallet_scorer import score_all_wallets

log = structlog.get_logger()


@click.command()
@click.option("--min-score", default=0, help="Only save wallets above this score")
def main(min_score: float):
    """Score all wallets based on historical trading patterns."""
    db = SessionLocal()

    try:
        # Clear old scores
        db.query(WalletScore).delete()
        db.commit()

        scores = score_all_wallets(db)
        log.info("wallets_scored", total=len(scores))

        saved = 0
        for ws in scores:
            if ws.overall_score >= min_score:
                db.add(ws)
                saved += 1

        db.commit()
        log.info("scores_saved", count=saved)

        # Print top 20
        top = sorted(scores, key=lambda s: s.overall_score, reverse=True)[:20]
        print("\n=== Top 20 Wallets ===")
        print(f"{'Wallet':<16} {'Overall':>8} {'Timing':>8} {'Profit':>8} {'Freq':>8} {'Consist':>8} {'Tokens':>7}")
        print("-" * 75)
        for ws in top:
            print(
                f"{ws.wallet_address[:14]}.. "
                f"{ws.overall_score:>8.1f} "
                f"{ws.timing_score:>8.1f} "
                f"{ws.profit_score:>8.1f} "
                f"{ws.frequency_score:>8.1f} "
                f"{ws.consistency_score:>8.1f} "
                f"{ws.tokens_analyzed:>7d}"
            )

    finally:
        db.close()


if __name__ == "__main__":
    main()
