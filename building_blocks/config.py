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

    # Vault (Secrets Vault integration)
    vault_url: str = "http://127.0.0.1:8400"
    vault_api_key: str = ""
    vault_project_id: str = "diet_platform"
    vault_enabled: bool = True  # загружать секреты из Vault

    class Config:
        env_file = "/opt/diet_platform/.env"
        env_file_encoding = "utf-8"
        extra = "ignore"

    def load_vault_secrets(self) -> dict[str, str]:
        """Загрузить секреты из Vault и вернуть как dict."""
        if not self.vault_enabled:
            return {}
        try:
            from building_blocks.vault_integration import VaultSecretLoader
            vault = VaultSecretLoader(
                vault_url=self.vault_url,
                project_id=self.vault_project_id,
                api_key=self.vault_api_key or None,
            )
            secrets = vault.load_all()
            vault.close()
            return secrets
        except Exception as e:
            import logging
            logging.getLogger("diet_platform.config").warning(
                "Vault secrets load failed: %s", e
            )
            return {}

    def apply_vault_overrides(self):
        """Перезаписать поля из Vault (vault-значения приоритетнее .env)."""
        vault_secrets = self.load_vault_secrets()
        if not vault_secrets:
            return
        for key, val in vault_secrets.items():
            # Маппинг env-имён в snake_case поля Settings
            field_map = {
                "GEMINI_API_KEY": "gemini_api_key",
                "GEMINI_KEYS": "gemini_keys",
                "GEMINI_MODEL": "gemini_model",
                "TELEGRAM_BOT_TOKEN": "telegram_bot_token",
                "USERBOT_RELAY_TOKEN": "userbot_relay_token",
                "SERPAPI_KEY": "serpapi_key",
                "DATABASE_PATH": "database_path",
                "VAULT_API_KEY": "vault_api_key",
            }
            field = field_map.get(key, key.lower())
            if hasattr(self, field) and val:
                setattr(self, field, val)


@lru_cache()
def get_settings() -> Settings:
    s = Settings()
    s.apply_vault_overrides()  # vault перезаписывает .env
    return s