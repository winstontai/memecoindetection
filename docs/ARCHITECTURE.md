# Moonshot Wallet Intelligence - System Architecture

## Overview

A hybrid wallet-intelligence system that learns from historical pre-announcement meme coin activity on Solana and detects future tokens showing similar early accumulation patterns.

## System Layers

```
┌─────────────────────────────────────────────────────────────────┐
│                        DATA SOURCES                             │
│  Helius API  │  Birdeye API  │  DexScreener  │  Solana RPC     │
└──────┬───────┴───────┬───────┴───────┬───────┴────────┬────────┘
       │               │               │                │
┌──────▼───────────────▼───────────────▼────────────────▼────────┐
│                    INGESTION LAYER                              │
│                                                                 │
│  ┌──────────────┐  ┌──────────────┐  ┌───────────────────┐     │
│  │  Historical   │  │    Token     │  │   Live TX Stream  │     │
│  │   Backfill    │  │  Discovery   │  │   (Helius WS)     │     │
│  └──────┬───────┘  └──────┬───────┘  └────────┬──────────┘     │
└─────────┼─────────────────┼───────────────────┼────────────────┘
          │                 │                   │
┌─────────▼─────────────────▼───────────────────▼────────────────┐
│                 STORAGE LAYER (PostgreSQL)                      │
│                                                                 │
│  tokens │ wallets │ trades │ wallet_scores │ signals │ funding  │
│                                                                 │
└─────────┬─────────────────────────────────┬────────────────────┘
          │                                 │
┌─────────▼─────────────────────────────────▼────────────────────┐
│                    ANALYSIS ENGINE                              │
│                                                                 │
│  ┌────────────────┐  ┌─────────────────┐  ┌─────────────────┐  │
│  │ Wallet Scorer  │  │ Pattern Detector│  │ Signal Generator│  │
│  │                │  │                 │  │                 │  │
│  │ - timing       │  │ - buy clustering│  │ - wallet match  │  │
│  │ - profit       │  │ - funding links │  │ - pattern match │  │
│  │ - frequency    │  │ - size patterns │  │ - composite     │  │
│  │ - consistency  │  │ - hold duration │  │ - risk rating   │  │
│  └────────────────┘  └─────────────────┘  └─────────────────┘  │
└─────────┬─────────────────────────────────┬────────────────────┘
          │                                 │
┌─────────▼─────────────────────────────────▼────────────────────┐
│                    OUTPUT LAYER                                 │
│                                                                 │
│  ┌──────────────┐  ┌──────────────┐  ┌───────────────────┐     │
│  │  Streamlit   │  │  Telegram    │  │  Discord Webhook  │     │
│  │  Dashboard   │  │  Bot         │  │                   │     │
│  └──────────────┘  └──────────────┘  └───────────────────┘     │
└────────────────────────────────────────────────────────────────┘
```

## Data Source Strategy

| Source | Purpose | Tier |
|--------|---------|------|
| **Helius API** | Parsed transactions, webhooks, token metadata | Primary - covers 80% of needs |
| **Birdeye API** | Token price/volume, OHLCV, token discovery | Secondary - price data |
| **DexScreener** | New pair discovery, trending tokens | Secondary - discovery |
| **Solana RPC** | Fallback for raw transaction data | Tertiary - edge cases |

### Why Helius is Primary
- Parsed transaction data (no manual instruction decoding)
- Webhook support for real-time monitoring
- Enhanced transaction history API
- DAS API for token metadata
- Free tier: 50K credits/day (enough for MVP)

## Key Design Decisions

1. **PostgreSQL over MongoDB** - Data is highly relational (wallets <-> trades <-> tokens). Heavy use of JOINs, aggregations, and time-range queries.

2. **No message queue for MVP** - Simple polling loop. Add Redis/RabbitMQ only when processing >100 tokens/hour.

3. **Rule-based scoring first** - Tunable weights, interpretable signals. ML only if rules plateau.

4. **Helius webhooks for live monitoring** - Push-based, not polling. Reduces API calls and latency.

5. **Modular scoring** - Each score component is a standalone function. Easy to add/remove/tune.

## Scoring Architecture

### Wallet Score (0-100)
Composite of four independent scores:

```
wallet_score = (
    timing_score * 0.30 +      # How early before announcement
    profit_score * 0.25 +       # Average ROI on early buys
    frequency_score * 0.25 +    # How many successful early buys
    consistency_score * 0.20    # Hit rate (successful / total early buys)
)
```

### Token Signal Score (0-100)
Triggered when monitoring new launches:

```
token_signal = (
    known_wallet_score * 0.35 +     # Weighted sum of known wallet scores buying in
    buy_clustering_score * 0.20 +   # Multiple early buys in tight window
    timing_pattern_score * 0.15 +   # Buy timing relative to pool creation
    funding_pattern_score * 0.15 +  # Common funding sources among buyers
    volume_pattern_score * 0.15     # Volume pattern matching historical winners
)
```

## Data Flow

### Historical (Batch)
1. Curate list of past Moonshot tokens with announcement timestamps
2. For each token: pull all trades from creation to announcement + 24h after
3. Identify wallets that bought before announcement
4. Score each wallet across all tokens
5. Extract behavioral patterns from top wallets

### Live (Streaming)
1. Helius webhook fires on new token creation / new trades
2. System checks: is any known high-score wallet buying?
3. System checks: do buyer behaviors match historical patterns?
4. If score > threshold: generate signal, push to dashboard + alerts
