"""Streamlit dashboard for Moonshot Wallet Intelligence.

Run: streamlit run src/dashboard/app.py
"""

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

import streamlit as st
import pandas as pd
from sqlalchemy import func, distinct

from src.db.engine import SessionLocal
from src.db.models import Token, Wallet, Trade, WalletScore


st.set_page_config(page_title="Moonshot Intel", layout="wide")
st.title("Moonshot Wallet Intelligence")


@st.cache_resource
def get_db():
    return SessionLocal()


db = get_db()

# --- Sidebar ---
st.sidebar.header("Filters")
strict_only = st.sidebar.checkbox("Strict filter only", value=True,
                                  help="Show only wallets that passed bot + profit/hold filters")
min_score = st.sidebar.slider("Min Wallet Score", 0, 100, 0)

# --- Overview ---
col1, col2, col3, col4, col5 = st.columns(5)
col1.metric("Tokens Tracked", db.query(Token).count())
col2.metric("Total Trades", db.query(Trade).count())
col3.metric("Unique Wallets", db.query(func.count(distinct(Trade.wallet_address))).scalar())
col4.metric("Strict Wallets",
            db.query(WalletScore).filter(WalletScore.passes_strict_filter == True).count())
col5.metric("Bots Filtered",
            db.query(WalletScore).filter(WalletScore.is_bot == True).count())

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
if strict_only:
    st.caption("Showing wallets that passed strict filter: non-bot, early buyers who are holding or sold at profit")
else:
    st.caption("Showing all scored wallets (includes bots and losing wallets)")

scores_query = (
    db.query(WalletScore)
    .filter(WalletScore.overall_score >= min_score)
    .order_by(WalletScore.overall_score.desc())
    .limit(50)
)
if strict_only:
    scores_query = scores_query.filter(WalletScore.passes_strict_filter == True)

scores = scores_query.all()

wallet_rows = []
for ws in scores:
    token_symbols = (
        db.query(distinct(Token.symbol))
        .join(Trade, Trade.token_mint == Token.mint_address)
        .filter(Trade.wallet_address == ws.wallet_address)
        .all()
    )
    tokens_str = ", ".join(s[0] for s in token_symbols if s[0])

    wallet_rows.append({
        "Wallet": ws.wallet_address,
        "Score": round(ws.overall_score, 1),
        "Timing": round(ws.timing_score, 1),
        "Profit": ws.tokens_profitable,
        "Hold": ws.tokens_holding,
        "Loss": ws.tokens_at_loss,
        "SOL P/L": round(ws.realized_profit_sol or 0, 3),
        "# Tokens": ws.tokens_analyzed,
        "Tokens": tokens_str,
        "Bot?": "Y" if ws.is_bot else "",
        "Total TX": ws.total_trades,
    })

if wallet_rows:
    df = pd.DataFrame(wallet_rows)
    st.dataframe(df, use_container_width=True, hide_index=True)

    # Wallet detail
    st.subheader("Wallet Detail")
    selected_wallet = st.selectbox(
        "Select a wallet to inspect",
        options=[r["Wallet"] for r in wallet_rows],
    )

    if selected_wallet:
        ws = db.query(WalletScore).filter(WalletScore.wallet_address == selected_wallet).first()

        # Per-token outcome breakdown
        if ws and ws.outcome_summary:
            st.markdown("**Per-token Outcome**")
            outcome_rows = []
            for mint, outcome in ws.outcome_summary.items():
                token = db.get(Token, mint)
                outcome_rows.append({
                    "Token": token.symbol if token else mint[:8],
                    "Status": outcome.get("status", "?"),
                    "Bought (tokens)": round(outcome.get("tokens_bought", 0), 2),
                    "Sold (tokens)": round(outcome.get("tokens_sold", 0), 2),
                    "Remaining": round(outcome.get("tokens_remaining", 0), 2),
                    "SOL Spent": round(outcome.get("sol_spent", 0), 4),
                    "SOL Received": round(outcome.get("sol_received", 0), 4),
                    "Realized P/L (SOL)": round(outcome.get("realized_profit_sol", 0), 4),
                })
            st.dataframe(pd.DataFrame(outcome_rows), use_container_width=True, hide_index=True)

        # All trades for this wallet
        st.markdown("**All Trades**")
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
    st.info("No wallets match the current filters.")

st.divider()

# --- Early Buyer Overlap ---
st.header("Cross-Token Wallet Overlap")
st.caption("Wallets that appear as early buyers in multiple tokens (respects strict filter toggle)")

if len(tokens) >= 2:
    overlap_q = (
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
    )

    if strict_only:
        strict_wallets = {
            row[0] for row in
            db.query(WalletScore.wallet_address).filter(WalletScore.passes_strict_filter == True).all()
        }
        overlap_data = [r for r in overlap_q.limit(500).all() if r.wallet_address in strict_wallets][:30]
    else:
        overlap_data = overlap_q.limit(30).all()

    if overlap_data:
        overlap_rows = []
        for row in overlap_data:
            syms = (
                db.query(distinct(Token.symbol))
                .join(Trade, Trade.token_mint == Token.mint_address)
                .filter(Trade.wallet_address == row.wallet_address, Trade.side == "buy")
                .all()
            )
            overlap_rows.append({
                "Wallet": row.wallet_address,
                "Tokens": row.token_count,
                "Total Buys": row.trade_count,
                "Total SOL": round(row.total_sol, 2) if row.total_sol else 0,
                "Token List": ", ".join(s[0] for s in syms if s[0]),
            })
        st.dataframe(pd.DataFrame(overlap_rows), use_container_width=True, hide_index=True)
    else:
        st.info("No cross-token overlap found with current filters.")
