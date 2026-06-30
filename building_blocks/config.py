"""Config: pydantic-settings для всего проекта."""
from pydantic_settings import BaseSettings
from pydantic import Field
from functools import lru_cache


class Settings(BaseSettings):
    # App
    app_host: str = "0.0.0.0"
    app_port: int = 8150
    debug: bool = False

    # DB
    database_path: str = "/opt/diet_platform/diet_platform.db"

    # Gemini
    gemini_api_key: str = ""
    gemini_keys: str = ""  # comma-separated pool
    gemini_model: str = "gemini-3.1-flash-lite"

    # Telegram
    telegram_bot_token: str = ""

    # Userbot Relay (den4ik-claude) — см. CONFLICT-01 в TEAM_NOTES.md
    userbot_relay_token: str = ""

    # Search
    serpapi_key: str = ""
    max_urls_per_query: int = 5
    search_cache_ttl_hours: int = 24

    # Scraper
    scraper_timeout_seconds: int = 15
    scraper_max_retries: int = 3
    scraper_user_agent: str = (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/120.0.0.0 Safari/537.36"
    )

    # Worker
    worker_poll_interval_seconds: int = 3
    worker_max_concurrent: int = 3

    # Registry
    min_confidence_score: float = 0.15
    auto_publish_threshold: float = 0.75

    class Config:
        env_file = "/opt/diet_platform/.env"
        env_file_encoding = "utf-8"
        extra = "ignore"


@lru_cache()
def get_settings() -> Settings:
    return Settings()