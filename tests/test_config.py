import pytest

from securities_master.config import Settings


def test_from_env_builds_settings(monkeypatch):
    monkeypatch.setenv("DATABASE_URL", "postgresql+psycopg://u:p@h:5433/d")
    monkeypatch.setenv("SEC_USER_AGENT", "Ada Lovelace ada@example.com")
    settings = Settings.from_env()
    assert settings.database_url == "postgresql+psycopg://u:p@h:5433/d"
    assert settings.sec_user_agent == "Ada Lovelace ada@example.com"


def test_from_env_requires_database_url(monkeypatch):
    monkeypatch.delenv("DATABASE_URL", raising=False)
    monkeypatch.setenv("SEC_USER_AGENT", "Ada Lovelace ada@example.com")
    with pytest.raises(RuntimeError, match="DATABASE_URL"):
        Settings.from_env()


def test_from_env_requires_sec_user_agent(monkeypatch):
    monkeypatch.setenv("DATABASE_URL", "postgresql+psycopg://u:p@h:5433/d")
    monkeypatch.delenv("SEC_USER_AGENT", raising=False)
    with pytest.raises(RuntimeError, match="SEC_USER_AGENT"):
        Settings.from_env()
