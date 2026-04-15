# Moonshot Wallet Intelligence

## Project
Hybrid wallet-intelligence system for Solana meme coins. Detects pre-announcement accumulation patterns on Moonshot.

## Tech Stack
- Python 3.11+
- PostgreSQL (SQLAlchemy ORM, Alembic migrations)
- Helius API (primary Solana data), Birdeye (price data), DexScreener (discovery)
- Streamlit (dashboard), Telegram (alerts)

## Architecture
- `src/config.py` - Settings from .env via pydantic-settings
- `src/constants.py` - Scoring weights and thresholds (tune here)
- `src/db/models.py` - SQLAlchemy models (Token, Wallet, Trade, WalletScore, TokenSignal, FundingLink)
- `src/ingestion/` - API clients (helius.py, birdeye.py, dexscreener.py)
- `src/analysis/` - Scoring engine (wallet_scorer.py, pattern_detector.py, signal_generator.py)
- `src/monitor/live_scanner.py` - Real-time monitoring loop
- `src/alerts/telegram.py` - Alert delivery
- `src/scripts/` - CLI scripts (backfill.py, score_wallets.py)

## Commands
- `python -m src.scripts.backfill --tokens-file data/seed_tokens.json --create-db` - Backfill historical data
- `python -m src.scripts.score_wallets` - Score all wallets

## Conventions
- Async throughout (httpx, asyncio)
- Structured logging via structlog
- All scoring weights in constants.py (not scattered)
- Rule-based scoring first, ML only if justified
