"""Wallet scoring helpers.

Pure scoring functions used by insider_ranker to compute component scores.
Main scoring pipeline lives in insider_ranker.rank_insider_wallets().
"""

from src.constants import TIMING_BUCKETS


def score_timing(seconds_before: list[int]) -> float:
    """Score how early the wallet tends to buy before announcements.

    Args:
        seconds_before: List of seconds-before-announcement for each early buy.
                        Positive = before announcement.

    Returns:
        Score 0-100. Higher = consistently earlier.
    """
    if not seconds_before:
        return 0.0

    scores = []
    for secs in seconds_before:
        if secs <= 0:
            scores.append(0)
            continue
        score = 10  # Default for very early (> 7 days)
        for threshold, bucket_score in TIMING_BUCKETS:
            if secs <= threshold:
                score = bucket_score
                break
        scores.append(score)

    return sum(scores) / len(scores)
