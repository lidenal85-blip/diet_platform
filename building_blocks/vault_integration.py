"""Vault Integration — подключение diet_platform к Secrets Vault.

Использует универсальный VaultClient из vault_client_v2.
"""
from __future__ import annotations

import logging
import os
from pathlib import Path
from typing import Any, Dict, Optional

import sys
sys.path.insert(0, "/opt/secrets_vault/client")

from vault_client_v2 import VaultClient as _VaultClient

logger = logging.getLogger("diet_platform.vault")

VAULT_URL = os.getenv("VAULT_URL", "http://127.0.0.1:8400")
PROJECT_ID = os.getenv("VAULT_PROJECT_ID", "diet_platform")
API_KEY = os.getenv("VAULT_API_KEY", "")  # ключ только через env — урок инцидента 2026-09 (никаких секретов в коде)


class VaultSecretLoader:
    """Загрузчик секретов из Vault (обёртка над VaultClient)."""

    def __init__(
        self,
        vault_url: str = VAULT_URL,
        project_id: str = PROJECT_ID,
        api_key: str = API_KEY,
    ):
        self._client = _VaultClient(
            vault_url=vault_url,
            project_id=project_id,
            api_key=api_key,
        )

    # ── делегирование VaultClient ──

    @property
    def vault_url(self) -> str:
        return self._client.vault_url

    @property
    def project_id(self) -> str:
        return self._client.project_id or ""

    def get_secret(self, key_name: str) -> Optional[str]:
        return self._client.get_secret(key_name)

    def load_all(self) -> Dict[str, str]:
        return self._client.load_all()

    def list_secrets(self) -> Dict[str, Any]:
        """Возвращает имена ключей как dict (для совместимости)."""
        keys = self._client.list_keys()
        return {k: {} for k in keys}

    def set_secret(self, key_name: str, value: str) -> bool:
        return self._client.set_secret(key_name, value)

    def set_secrets_batch(self, secrets: Dict[str, str]) -> int:
        return self._client.set_secrets_batch(secrets)

    def health(self) -> bool:
        return self._client.health()

    def close(self):
        self._client.close()

    # ── миграция ──

    def migrate_from_env(
        self,
        env_path: str = "/opt/diet_platform/.env",
        keys: Optional[list[str]] = None,
    ) -> int:
        """Мигрировать секреты из .env файла в Vault."""
        if keys is None:
            keys = [
                "GEMINI_API_KEY", "GEMINI_KEYS", "GEMINI_MODEL",
                "TELEGRAM_BOT_TOKEN",
                "SERPAPI_KEY", "VAULT_API_KEY",
            ]

        path = Path(env_path)
        if not path.exists():
            logger.warning(".env not found at %s", env_path)
            return 0

        secrets: Dict[str, str] = {}
        for line in path.read_text().splitlines():
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, _, val = line.partition("=")
            key = key.strip()
            val = val.strip().strip("\"'")
            if key in keys and val:
                secrets[key] = val

        if not secrets:
            logger.info("No secrets to migrate from .env")
            return 0

        saved = self.set_secrets_batch(secrets)
        logger.info("Migrated %d/%d secrets to Vault", saved, len(secrets))
        return saved
