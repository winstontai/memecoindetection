"""Application configuration loaded from environment variables."""

from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    # Database
    database_url: str = "postgresql://localhost:5432/moonshot"

    # Helius
    helius_api_key: str = ""
    helius_rpc_url: str = ""

    # Birdeye
    birdeye_api_key: str = ""

    # Alerts
    telegram_bot_token: str = ""
    telegram_chat_id: str = ""
    discord_webhook_url: str = ""

    # App
    log_level: str = "INFO"
    signal_threshold: int = 60
    poll_interval_seconds: int = 30

    model_config = {"env_file": ".env", "env_file_encoding": "utf-8"}


settings = Settings()
