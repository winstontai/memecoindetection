"""Streamlit dashboard for Moonshot Wallet Intelligence.

Run: streamlit run src/dashboard/app.py
"""

import streamlit as st
import pandas as pd
from datetime import datetime
from sqlalchemy import func, distinct

from src.db.engine import SessionLocal
from src.db.models import Token, Wallet, Trade, WalletScore, TokenSignal


st.set_page_config(page_title="Moonshot Intel", layout="wide")
st.title("Moonshot Wallet Intelligence")


@st.cache_resource
def get_db():
    return SessionLocal()


db = get_db()

# --- Sidebar ---
st.sidebar.header("Filters")
min_score = st.sidebar.slider("Min Wallet Score", 0, 100, 30)

# --- Overview ---
col1, col2, col3, col4 = st.columns(4)
col1.metric("Tokens Tracked", db.query(Token).count())
col2.metric("Total Trades", db.query(Trade).count())
col3.metric("Unique Wallets", db.query(func.count(distinct(Trade.wallet_address))).scalar())
col4.metric("Scored Wallets", db.query(WalletScore).filter(WalletScore.overall_score >= min_score).count())

st.divider()

# --- Token Summary ---
st.header("Token Overview")
tokens = db.query(Token).all()
token_data = []
for t in tokens:
    trades = db.query(Trade).filter(Trade.token_mint == t.mint_address)
    pre_ann = trades.filter(Trade.seconds_before_announcement > 0).count()
    total = trades.count()
    buys = trades.filter(Trade.side == "buy").count()
    wallets = db.query(func.count(distinct(Trade.wallet_address))).filter(
        Trade.token_mint == t.mint_address
    ).scalar()
    earliest = db.query(func.min(Trade.timestamp)).filter(
        Trade.token_mint == t.mint_address
    ).scalar()

    hrs_before = 0
    if earliest and t.announced_at:
        hrs_before = (t.announced_at - earliest).total_seconds() / 3600

    token_data.append({
        "Symbol": t.symbol,
        "Name": t.name,
        "Announced": t.announced_at.strftime("%Y-%m-%d %H:%M") if t.announced_at else "N/A",
        "Total Trades": total,
        "Pre-Announcement": pre_ann,
        "Buys": buys,
        "Unique Wallets": wallets,
        "Earliest (hrs before)": f"{hrs_before:.1f}",
    })

st.dataframe(pd.DataFrame(token_data), use_container_width=True, hide_index=True)

st.divider()

# --- Wallet Leaderboard ---
st.header("Wallet Leaderboard")
st.caption("Wallets that bought early across multiple tokens, ranked by composite score")

scores = (
    db.query(WalletScore)
    .filter(WalletScore.overall_score >= min_score)
    .order_by(WalletScore.overall_score.desc())
    .limit(50)
    .all()
)

wallet_rows = []
for ws in scores:
    # Get per-token breakdown
    token_symbols = (
        db.query(distinct(Token.symbol))
        .join(Trade, Trade.token_mint == Token.mint_address)
        .filter(Trade.wallet_address == ws.wallet_address)
        .all()
    )
    tokens_str = ", ".join(s[0] for s in token_symbols if s[0])

    total_sol_in = (
        db.query(func.sum(Trade.amount_sol))
        .filter(Trade.wallet_address == ws.wallet_address, Trade.side == "buy")
        .scalar() or 0
    )
    total_sol_out = (
        db.query(func.sum(Trade.amount_sol))
        .filter(Trade.wallet_address == ws.wallet_address, Trade.side == "sell")
        .scalar() or 0
    )

    wallet_rows.append({
        "Wallet": ws.wallet_address[:16] + "...",
        "Full Address": ws.wallet_address,
        "Score": round(ws.overall_score, 1),
        "Timing": round(ws.timing_score, 1),
        "Profit": round(ws.profit_score, 1),
        "Frequency": round(ws.frequency_score, 1),
        "Consistency": round(ws.consistency_score, 1),
        "Tokens": tokens_str,
        "SOL In": round(total_sol_in, 2),
        "SOL Out": round(total_sol_out, 2),
        "# Tokens": ws.tokens_analyzed,
    })

if wallet_rows:
    df = pd.DataFrame(wallet_rows)
    st.dataframe(
        df.drop(columns=["Full Address"]),
        use_container_width=True,
        hide_index=True,
    )

    # Wallet detail expander
    st.subheader("Wallet Detail")
    selected_wallet = st.selectbox(
        "Select a wallet to inspect",
        options=[r["Full Address"] for r in wallet_rows],
        format_func=lambda x: x[:20] + "...",
    )

    if selected_wallet:
        trades = (
            db.query(Trade)
            .filter(Trade.wallet_address == selected_wallet)
            .order_by(Trade.timestamp.asc())
            .all()
        )

        trade_rows = []
        for t in trades:
            token = db.get(Token, t.token_mint)
            hrs = t.seconds_before_announcement / 3600 if t.seconds_before_announcement else 0
            trade_rows.append({
                "Time": t.timestamp.strftime("%Y-%m-%d %H:%M:%S"),
                "Token": token.symbol if token else t.token_mint[:8],
                "Side": t.side.upper(),
                "SOL": round(t.amount_sol, 4) if t.amount_sol else 0,
                "Tokens": round(t.amount_tokens, 2) if t.amount_tokens else 0,
                "Price USD": f"${t.price_usd:.8f}" if t.price_usd else "N/A",
                "Hrs Before Ann.": round(hrs, 1),
                "TX": t.tx_signature[:16] + "...",
            })

        st.dataframe(pd.DataFrame(trade_rows), use_container_width=True, hide_index=True)
else:
    st.info("No wallets found above the minimum score threshold.")

st.divider()

# --- Early Buyer Overlap ---
st.header("Cross-Token Wallet Overlap")
st.caption("Wallets that appear as early buyers in multiple tokens")

if len(tokens) >= 2:
    overlap_data = (
        db.query(
            Trade.wallet_address,
            func.count(distinct(Trade.token_mint)).label("token_count"),
            func.count(Trade.id).label("trade_count"),
            func.sum(Trade.amount_sol).label("total_sol"),
        )
        .filter(Trade.seconds_before_announcement > 0, Trade.side == "buy")
        .group_by(Trade.wallet_address)
        .having(func.count(distinct(Trade.token_mint)) >= 2)
        .order_by(func.count(distinct(Trade.token_mint)).desc(), func.sum(Trade.amount_sol).desc())
        .limit(30)
        .all()
    )

    if overlap_data:
        overlap_rows = []
        for row in overlap_data:
            # Get which tokens
            syms = (
                db.query(distinct(Token.symbol))
                .join(Trade, Trade.token_mint == Token.mint_address)
                .filter(Trade.wallet_address == row.wallet_address, Trade.side == "buy")
                .all()
            )
            overlap_rows.append({
                "Wallet": row.wallet_address[:20] + "...",
                "Tokens": row.token_count,
                "Total Buys": row.trade_count,
                "Total SOL": round(row.total_sol, 2) if row.total_sol else 0,
                "Token List": ", ".join(s[0] for s in syms if s[0]),
            })
        st.dataframe(pd.DataFrame(overlap_rows), use_container_width=True, hide_index=True)
    else:
        st.info("No cross-token overlap found.")
