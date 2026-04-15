"""Telegram alert sender."""

import httpx
import structlog
from src.config import settings
from src.db.models import TokenSignal

log = structlog.get_logger()


async def send_signal_alert(signal: TokenSignal) -> bool:
    """Send a formatted signal alert to Telegram."""
    if not settings.telegram_bot_token or not settings.telegram_chat_id:
        log.warning("telegram_not_configured")
        return False

    details = signal.details or {}
    components = details.get("component_scores", {})
    wallets = details.get("wallets_matched", [])
    patterns = details.get("patterns_matched", [])

    wallet_lines = ""
    if wallets:
        top = sorted(wallets, key=lambda w: w["score"], reverse=True)[:5]
        wallet_lines = "\n".join(
            f"  {w['address'][:12]}... (score: {w['score']})"
            for w in top
        )

    text = f"""🚨 *Signal Detected* — Score: {signal.score}

*Token:* `{signal.token_mint}`

*Components:*
  Wallet Match: {components.get('known_wallet', 0)}
  Buy Clustering: {components.get('buy_clustering', 0)}
  Early Timing: {components.get('early_timing', 0)}
  Funding Cluster: {components.get('funding_cluster', 0)}
  Size Pattern: {components.get('size_pattern', 0)}

*Patterns:* {', '.join(patterns) if patterns else 'None'}

*Known Wallets:*
{wallet_lines if wallet_lines else '  None matched'}

*Reason:* {signal.reason}
"""

    url = f"https://api.telegram.org/bot{settings.telegram_bot_token}/sendMessage"
    async with httpx.AsyncClient() as client:
        resp = await client.post(url, json={
            "chat_id": settings.telegram_chat_id,
            "text": text,
            "parse_mode": "Markdown",
        })

    if resp.status_code == 200:
        log.info("telegram_alert_sent", token=signal.token_mint)
        return True
    else:
        log.error("telegram_alert_failed", status=resp.status_code, body=resp.text)
        return False
