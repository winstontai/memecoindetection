"""Scoring weights and thresholds. Tune these as you gather data."""

# --- Wallet Score Weights (must sum to 1.0) ---
WALLET_TIMING_WEIGHT = 0.30
WALLET_PROFIT_WEIGHT = 0.25
WALLET_FREQUENCY_WEIGHT = 0.25
WALLET_CONSISTENCY_WEIGHT = 0.20

# --- Insider Rank Weights (must sum to 1.0) ---
INSIDER_TIMING_WEIGHT = 0.25
INSIDER_REPEATABILITY_WEIGHT = 0.20
INSIDER_OUTCOME_WEIGHT = 0.30
INSIDER_SELECTIVITY_WEIGHT = 0.15
INSIDER_NETWORK_WEIGHT = 0.10

# --- Token Signal Weights (must sum to 1.0) ---
SIGNAL_KNOWN_WALLET_WEIGHT = 0.35
SIGNAL_BUY_CLUSTERING_WEIGHT = 0.20
SIGNAL_TIMING_PATTERN_WEIGHT = 0.15
SIGNAL_FUNDING_PATTERN_WEIGHT = 0.15
SIGNAL_VOLUME_PATTERN_WEIGHT = 0.15

# --- Thresholds ---
# Minimum wallet score to be considered "interesting"
MIN_WALLET_SCORE = 40

# Minimum number of tokens a wallet must have been early on to be scored
MIN_EARLY_TOKENS = 2

# Minimum number of tokens required for the stricter insider filter
MIN_STRICT_EARLY_TOKENS = 3

# "Early" = bought within this many seconds before announcement
MAX_SECONDS_BEFORE_ANNOUNCEMENT = 86400 * 30  # 30 days

# Minimum token signal score to trigger an alert
SIGNAL_ALERT_THRESHOLD = 60

# --- Timing Score Buckets ---
# Maps "seconds before announcement" to a score (0-100)
# Earlier = higher score
TIMING_BUCKETS = [
    (300, 100),       # < 5 min before = 100
    (3600, 85),       # < 1 hour = 85
    (21600, 70),      # < 6 hours = 70
    (86400, 55),      # < 1 day = 55
    (259200, 40),     # < 3 days = 40
    (604800, 25),     # < 7 days = 25
    (1296000, 18),    # < 15 days = 18
    (2592000, 10),    # < 30 days = 10
]

# --- Bot Detection Thresholds ---
BOT_MAX_TOTAL_TRADES = 500          # Wallets with 500+ trades across all tokens = bot
BOT_MAX_DUST_TRADE_RATIO = 0.5     # >50% of trades are dust = bot
BOT_DUST_THRESHOLD_SOL = 0.01      # Trades below 0.01 SOL are "dust"

# --- Profit/Hold Classification ---
MIN_HOLD_RATIO = 0.1               # Holding 10%+ of bought tokens = "holding"
MIN_PROFITABLE_TOKEN_RATIO = 0.5   # Must be profitable/holding on 50%+ of early-bought tokens
MIN_STRICT_TIMING_SCORE = 25       # Needs at least "within 7 days" quality timing

# --- Clustering ---
# If N+ wallets buy within this window, it's a cluster
CLUSTER_WINDOW_SECONDS = 600  # 10 minutes
CLUSTER_MIN_WALLETS = 3
