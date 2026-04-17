"""SQLAlchemy models - the core database schema."""

from datetime import datetime

from sqlalchemy import (
    Column, String, Float, Integer, Boolean, DateTime, Integer,
    ForeignKey, Index, Text, JSON
)
from sqlalchemy.orm import DeclarativeBase, relationship


class Base(DeclarativeBase):
    pass


class Token(Base):
    """A meme coin token tracked by the system."""
    __tablename__ = "tokens"

    mint_address = Column(String(44), primary_key=True)
    name = Column(String(200))
    symbol = Column(String(20))
    platform = Column(String(50), default="moonshot")  # moonshot, pump.fun, etc.

    # Key timestamps
    created_at = Column(DateTime)          # When the token/pool was created on-chain
    announced_at = Column(DateTime)        # When it was publicly announced/listed
    discovered_at = Column(DateTime)       # When our system first saw it

    # Metrics at announcement time (for historical scoring)
    market_cap_at_announcement = Column(Float)
    volume_24h_at_announcement = Column(Float)
    holders_at_announcement = Column(Integer)

    # Current status
    status = Column(String(20), default="active")  # active, dead, graduated
    is_historical = Column(Boolean, default=False)  # True = used for training scores

    # Metadata
    metadata_ = Column("metadata", JSON)

    trades = relationship("Trade", back_populates="token")

    __table_args__ = (
        Index("ix_tokens_platform", "platform"),
        Index("ix_tokens_created_at", "created_at"),
        Index("ix_tokens_announced_at", "announced_at"),
    )


class Wallet(Base):
    """A Solana wallet address we're tracking."""
    __tablename__ = "wallets"

    address = Column(String(44), primary_key=True)
    label = Column(String(200))            # Optional human label
    category = Column(String(50))          # insider, sniper, bot, organic, unknown
    first_seen = Column(DateTime)

    # Aggregate stats (updated periodically)
    total_tokens_traded = Column(Integer, default=0)
    total_early_buys = Column(Integer, default=0)   # Buys before announcement
    total_profit_usd = Column(Float, default=0.0)
    win_rate = Column(Float, default=0.0)            # % of early buys that were profitable

    trades = relationship("Trade", back_populates="wallet")
    scores = relationship("WalletScore", back_populates="wallet")
    funding_received = relationship("FundingLink", back_populates="wallet",
                                     foreign_keys="FundingLink.wallet_address")

    __table_args__ = (
        Index("ix_wallets_category", "category"),
    )


class Trade(Base):
    """A single trade (buy or sell) for a token by a wallet."""
    __tablename__ = "trades"

    id = Column(Integer, primary_key=True, autoincrement=True)
    tx_signature = Column(String(88), unique=True, nullable=False)
    wallet_address = Column(String(44), ForeignKey("wallets.address"), nullable=False)
    token_mint = Column(String(44), ForeignKey("tokens.mint_address"), nullable=False)

    timestamp = Column(DateTime, nullable=False)
    side = Column(String(4), nullable=False)          # "buy" or "sell"
    amount_tokens = Column(Float)
    amount_sol = Column(Float)
    price_usd = Column(Float)

    # Computed fields (filled during analysis)
    seconds_before_announcement = Column(Integer)      # Negative = after announcement

    wallet = relationship("Wallet", back_populates="trades")
    token = relationship("Token", back_populates="trades")

    __table_args__ = (
        Index("ix_trades_wallet", "wallet_address"),
        Index("ix_trades_token", "token_mint"),
        Index("ix_trades_timestamp", "timestamp"),
        Index("ix_trades_wallet_token", "wallet_address", "token_mint"),
    )


class WalletScore(Base):
    """Computed score for a wallet based on historical analysis."""
    __tablename__ = "wallet_scores"

    id = Column(Integer, primary_key=True, autoincrement=True)
    wallet_address = Column(String(44), ForeignKey("wallets.address"), nullable=False)

    # Component scores (0-100 each)
    timing_score = Column(Float, default=0.0)
    profit_score = Column(Float, default=0.0)
    frequency_score = Column(Float, default=0.0)
    consistency_score = Column(Float, default=0.0)

    # Composite
    overall_score = Column(Float, default=0.0)

    # Context
    tokens_analyzed = Column(Integer, default=0)
    scored_at = Column(DateTime, default=datetime.utcnow)

    # Bot detection
    is_bot = Column(Boolean, default=False)
    total_trades = Column(Integer, default=0)
    dust_trade_ratio = Column(Float)

    # Profit/hold classification
    tokens_profitable = Column(Integer, default=0)
    tokens_holding = Column(Integer, default=0)
    tokens_at_loss = Column(Integer, default=0)
    realized_profit_sol = Column(Float, default=0.0)
    outcome_summary = Column(JSON)  # Per-token: {mint: {status, sol_spent, sol_received, ...}}

    # Strict filter result
    passes_strict_filter = Column(Boolean, default=False)

    wallet = relationship("Wallet", back_populates="scores")

    __table_args__ = (
        Index("ix_wallet_scores_overall", "overall_score"),
        Index("ix_wallet_scores_wallet", "wallet_address"),
    )


class TokenSignal(Base):
    """A signal generated when a new token matches patterns."""
    __tablename__ = "token_signals"

    id = Column(Integer, primary_key=True, autoincrement=True)
    token_mint = Column(String(44), ForeignKey("tokens.mint_address"), nullable=False)

    signal_type = Column(String(30), nullable=False)  # wallet_match, pattern_match, composite
    score = Column(Float, nullable=False)
    triggered_at = Column(DateTime, default=datetime.utcnow)

    # Why it was flagged (human-readable)
    reason = Column(Text)

    # Detailed breakdown
    details = Column(JSON)
    # Example: {
    #   "wallets_matched": [{"address": "...", "wallet_score": 85}],
    #   "patterns_matched": ["buy_clustering", "early_timing"],
    #   "component_scores": {"wallet": 80, "clustering": 65, ...}
    # }

    # Was this signal correct? (filled in later for backtesting)
    outcome = Column(String(20))   # hit, miss, pending

    __table_args__ = (
        Index("ix_signals_token", "token_mint"),
        Index("ix_signals_score", "score"),
        Index("ix_signals_triggered", "triggered_at"),
    )


class FundingLink(Base):
    """Tracks where a wallet got its SOL from (funding source analysis)."""
    __tablename__ = "funding_links"

    id = Column(Integer, primary_key=True, autoincrement=True)
    wallet_address = Column(String(44), ForeignKey("wallets.address"), nullable=False)
    funder_address = Column(String(44), nullable=False)
    amount_sol = Column(Float)
    tx_signature = Column(String(88))
    timestamp = Column(DateTime)

    wallet = relationship("Wallet", back_populates="funding_received",
                          foreign_keys=[wallet_address])

    __table_args__ = (
        Index("ix_funding_wallet", "wallet_address"),
        Index("ix_funding_funder", "funder_address"),
    )
