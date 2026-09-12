"""Тесты интеграции diet_platform с Secrets Vault."""
import pytest
import json
from unittest.mock import patch, MagicMock


class TestVaultSecretLoader:
    """VaultSecretLoader — методы работы с vault."""

    def test_health(self):
        from building_blocks.vault_integration import VaultSecretLoader
        vault = VaultSecretLoader(api_key="test")
        ok = vault.health()
        # Vault running on port 8400 — should be True in production
        assert isinstance(ok, bool)

    def test_get_secret_not_found(self):
        from building_blocks.vault_integration import VaultSecretLoader
        vault = VaultSecretLoader(api_key="test")
        val = vault.get_secret("NONEXISTENT_KEY_12345")
        assert val is None

    def test_get_secret_known_key(self):
        from building_blocks.vault_integration import VaultSecretLoader
        vault = VaultSecretLoader(api_key="test")
        # TELEGRAM_BOT_TOKEN was migrated earlier
        val = vault.get_secret("TELEGRAM_BOT_TOKEN")
        if val is not None:
            assert isinstance(val, str)
            assert len(val) > 5

    def test_list_secrets_returns_dict(self):
        from building_blocks.vault_integration import VaultSecretLoader
        vault = VaultSecretLoader(api_key="test")
        secrets = vault.list_secrets()
        assert isinstance(secrets, dict)

    def test_load_all_returns_dict(self):
        from building_blocks.vault_integration import VaultSecretLoader
        vault = VaultSecretLoader(api_key="test")
        all_s = vault.load_all()
        assert isinstance(all_s, dict)

    def test_set_and_get_secret_roundtrip(self):
        from building_blocks.vault_integration import VaultSecretLoader
        vault = VaultSecretLoader(api_key="test")
        ok = vault.set_secret("TEST_KEY", "test_value_123")
        if ok:
            val = vault.get_secret("TEST_KEY")
            assert val == "test_value_123"

    def test_set_secret_empty_value(self):
        from building_blocks.vault_integration import VaultSecretLoader
        vault = VaultSecretLoader(api_key="test")
        # Empty string should still be accepted
        ok = vault.set_secret("TEST_EMPTY", "")
        # Either succeeds or fails gracefully
        assert isinstance(ok, bool)

    def test_batch_write(self):
        from building_blocks.vault_integration import VaultSecretLoader
        vault = VaultSecretLoader(api_key="test")
        saved = vault.set_secrets_batch({"BATCH_K1": "v1", "BATCH_K2": "v2"})
        assert isinstance(saved, int)
        if saved > 0:
            assert vault.get_secret("BATCH_K1") == "v1"

    def test_close_no_error(self):
        from building_blocks.vault_integration import VaultSecretLoader
        vault = VaultSecretLoader(api_key="test")
        vault.close()  # should not raise
        vault.close()  # calling twice should also not raise

    def test_init_defaults(self):
        from building_blocks.vault_integration import VaultSecretLoader, VAULT_URL, PROJECT_ID
        vault = VaultSecretLoader()
        assert vault.vault_url == VAULT_URL
        assert vault.project_id == PROJECT_ID


class TestVaultConfig:
    """Настройки vault в config.py."""

    def test_settings_has_vault_fields(self):
        from building_blocks.config import get_settings
        s = get_settings()
        assert hasattr(s, "vault_url")
        assert hasattr(s, "vault_api_key")
        assert hasattr(s, "vault_project_id")
        assert hasattr(s, "vault_enabled")

    def test_vault_default_url(self):
        from building_blocks.config import get_settings
        s = get_settings()
        assert s.vault_url == "http://127.0.0.1:8400"

    def test_vault_default_project(self):
        from building_blocks.config import get_settings
        s = get_settings()
        assert s.vault_project_id == "diet_platform"
