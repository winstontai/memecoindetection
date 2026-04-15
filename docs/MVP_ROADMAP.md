# MVP Roadmap

## Phase 1: Data Foundation (Week 1-2)
**Goal:** Get historical data into the database so we have something to analyze.

### Tasks
- [x] Project scaffolding, config, database models
- [ ] Get Helius API key (free tier: 50K credits/day)
- [ ] Manually curate 20-50 past Moonshot tokens that were successful
  - Need: mint address, name, symbol, announcement timestamp
  - Sources: Moonshot Twitter/announcements, DexScreener history
- [ ] Run backfill script to pull pre-announcement trades
- [ ] Verify data quality: spot-check trades, timestamps, wallet addresses
- [ ] Basic data exploration in a Jupyter notebook

### Deliverable
A populated database with trades for 20-50 historical tokens. You can query it and see who bought before announcements.

---

## Phase 2: Wallet Scoring (Week 2-3)
**Goal:** Score every wallet that appears in pre-announcement trades.

### Tasks
- [ ] Run `score_wallets.py` against historical data
- [ ] Review top-scoring wallets manually (sanity check)
- [ ] Tune scoring weights based on what you see
- [ ] Add profit calculation (track sells, not just buys)
- [ ] Basic Streamlit dashboard: wallet leaderboard + per-wallet breakdown
- [ ] Export top wallets to a watchlist

### Deliverable
A ranked list of wallets with scores. You know who the smart money is.

---

## Phase 3: Pattern Detection (Week 3-4)
**Goal:** Identify behavioral patterns that characterize pre-announcement activity.

### Tasks
- [ ] Run pattern detectors against historical tokens
- [ ] Tune thresholds (clustering window, min wallets, size ranges)
- [ ] Add funding source analysis (trace where early wallets got SOL)
- [ ] Build a "token profile" showing which patterns fired for each historical token
- [ ] Backtest: for each historical token, if the system had been running, would it have flagged it?

### Deliverable
A set of validated pattern rules with known hit rates.

---

## Phase 4: Live Monitoring (Week 4-5)
**Goal:** Watch new launches in real-time and generate signals.

### Tasks
- [ ] Run live scanner against new Solana token launches
- [ ] Integrate wallet watchlist into signal generator
- [ ] Integrate pattern detection into signal generator
- [ ] Add Telegram/Discord alerts
- [ ] Monitor for false positive rate, tune threshold

### Deliverable
A running system that alerts you when a new token shows suspicious early activity.

---

## Phase 5: Polish + Learn (Week 5-6)
**Goal:** Improve accuracy and usability based on real signals.

### Tasks
- [ ] Track signal outcomes (did the flagged tokens actually get announced?)
- [ ] Add outcome tracking to dashboard
- [ ] Refine scoring weights based on outcomes
- [ ] Add more pattern detectors if gaps emerge
- [ ] Consider: Helius webhooks for lower latency
- [ ] Consider: ML for pattern detection (only if rules plateau)

### Deliverable
A calibrated system with known accuracy metrics.

---

## Future / Post-MVP

### ML Opportunities (only if justified)
- **Wallet embedding:** Cluster wallets by behavioral similarity using unsupervised learning
- **Signal classifier:** Train a binary classifier on historical signals (hit vs miss)
- **Anomaly detection:** Flag tokens whose early activity deviates from normal launch patterns
- **Graph analysis:** Network analysis on funding links to find wallet clusters

### Infrastructure
- Helius webhooks for real-time (replace polling)
- Redis for caching hot wallet scores
- Next.js frontend for richer dashboard
- Multi-platform support (pump.fun, Raydium launches)

---

## API Keys Needed

| Service | Free Tier | What For | Sign Up |
|---------|-----------|----------|---------|
| **Helius** | 50K credits/day | Transaction data, webhooks | dev.helius.xyz |
| **Birdeye** | Limited free | Price/volume data | birdeye.so |
| **DexScreener** | Free, no key | Token discovery | N/A |
| **Telegram Bot** | Free | Alerts | t.me/BotFather |
