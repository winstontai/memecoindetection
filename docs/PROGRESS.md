# Progress Log

## Session 1 — 2026-04-16

### Completed
- Full system architecture designed (see docs/ARCHITECTURE.md)
- Project scaffolded: 20+ Python modules across ingestion, analysis, monitoring, alerts
- Database schema: 6 tables (Token, Wallet, Trade, WalletScore, TokenSignal, FundingLink)
- SQLite configured for MVP (easy switch to Postgres later via DATABASE_URL)
- API clients built: Helius, Birdeye, DexScreener
- Scoring engine: wallet scorer (4 components), pattern detector (4 detectors), signal generator
- Live scanner with Helius transaction parser (handles Meteora/PumpAMM/standard swaps)
- Telegram alert formatter
- Backfill + wallet scoring CLI scripts
- 3 seed tokens added: $unc, $Bull, $BURNIE
- Dependencies installed, .env configured with Helius + Birdeye keys
- Repo pushed to GitHub: https://github.com/winstontai/memecoindetection

### Blocked: Historical Backfill
**Problem:** Helius enhanced transaction API returns ALL transaction types (not just trades). High-volume tokens like $Bull have 50K+ transactions per day, making it impossible to paginate back to pre-announcement dates.

- $unc (announced Apr 15): 500 pages only reached Apr 16 04:22 (never reached pre-announcement)
- $Bull (announced Apr 11): 500 pages only reached Apr 16 01:56 (5 days short)
- $BURNIE (announced Apr 4): didn't even start due to timeout

**Solution needed:** Switch backfill to use **Birdeye trade history API** (`/defi/txs/token`) which supports time-based filtering (`tx_type=swap`, `before_time`, `after_time`). This will let us directly request trades in the pre-announcement window instead of paginating through millions of non-trade transactions.

### Next Steps
1. **Rewrite backfill to use Birdeye** — use `/defi/txs/token` with time range filtering
2. **Re-run backfill** for all 3 tokens, targeting announcement_date - 7 days to announcement_date
3. **Run wallet scoring** (`python -m src.scripts.score_wallets`)
4. **Build Streamlit dashboard** — wallet leaderboard + token breakdown
5. **Test pattern detection** against historical data
