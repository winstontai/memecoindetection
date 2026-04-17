"""Run stricter insider-style wallet scoring on all historical data.

Usage:
    python -m src.scripts.score_wallets
    python -m src.scripts.score_wallets --strict-only
    python -m src.scripts.score_wallets --recreate-db
"""

import click
import structlog

from src.db.engine import SessionLocal, engine
from src.db.models import WalletScore
from src.analysis.insider_ranker import rank_insider_wallets

log = structlog.get_logger()


@click.command()
@click.option("--min-score", default=0, help="Only save wallets above this score")
@click.option("--strict-only", is_flag=True, help="Print only wallets passing strict filter")
@click.option("--recreate-db", is_flag=True, help="Drop and recreate wallet_scores table (needed after model changes)")
def main(min_score: float, strict_only: bool, recreate_db: bool):
    """Score wallets using stricter insider-style heuristics."""
    if recreate_db:
        WalletScore.__table__.drop(engine, checkfirst=True)
        WalletScore.__table__.create(engine, checkfirst=True)
        log.info("wallet_scores_table_recreated")

    db = SessionLocal()

    try:
        # Clear old scores
        db.query(WalletScore).delete()
        db.commit()

        scores = rank_insider_wallets(db)
        log.info("wallets_scored", total=len(scores))

        # Filter funnel stats
        bots = sum(1 for s in scores if s.is_bot)
        strict = sum(1 for s in scores if s.passes_strict_filter)

        saved = 0
        for ws in scores:
            if ws.overall_score >= min_score:
                db.add(ws)
                saved += 1

        db.commit()
        log.info("scores_saved", count=saved, bots=bots, strict=strict)

        print("\n=== Filter Funnel ===")
        print(f"Wallets scored:         {len(scores)}")
        print(f"  Flagged as bot:       {bots}")
        print(f"  PASSED strict filter: {strict}")

        # Print top 20
        display = [s for s in scores if s.passes_strict_filter] if strict_only else scores
        top = sorted(display, key=lambda s: s.overall_score, reverse=True)[:20]

        header = "=== Top 20 Strict Insider Wallets ===" if strict_only else "=== Top 20 Wallets ==="
        print(f"\n{header}")
        print(
            f"{'Wallet':<16} {'Score':>6} {'Time':>5} {'Prof':>4} {'Hold':>4} {'Loss':>4} "
            f"{'SOL P/L':>8} {'Tok':>4} {'Bot':>4} {'Strict':>6}"
        )
        print("-" * 85)
        for ws in top:
            print(
                f"{ws.wallet_address[:14]}.. "
                f"{ws.overall_score:>6.1f} "
                f"{ws.timing_score:>5.0f} "
                f"{ws.tokens_profitable:>4d} "
                f"{ws.tokens_holding:>4d} "
                f"{ws.tokens_at_loss:>4d} "
                f"{ws.realized_profit_sol:>8.2f} "
                f"{ws.tokens_analyzed:>4d} "
                f"{'Y' if ws.is_bot else 'N':>4} "
                f"{'Y' if ws.passes_strict_filter else 'N':>6}"
            )

    finally:
        db.close()


if __name__ == "__main__":
    main()
