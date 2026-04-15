"""Scoring weights and thresholds. Tune these as you gather data."""

# --- Wallet Score Weights (must sum to 1.0) ---
WALLET_TIMING_WEIGHT = 0.30
WALLET_PROFIT_WEIGHT = 0.25
WALLET_FREQUENCY_WEIGHT = 0.25
WALLET_CONSISTENCY_WEIGHT = 0.20

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

# "Early" = bought within this many seconds before announcement
MAX_SECONDS_BEFORE_ANNOUNCEMENT = 86400 * 7  # 7 days

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
]

# --- Clustering ---
# If N+ wallets buy within this window, it's a cluster
CLUSTER_WINDOW_SECONDS = 600  # 10 minutes
CLUSTER_MIN_WALLETS = 3
