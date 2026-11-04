"""Testes da configuração (normalização de URL e variáveis de ambiente)."""

from __future__ import annotations

import pytest

from granatech_webhook.config import (
    DATABASE_URL_PADRAO,
    Settings,
    normalizar_database_url,
)


@pytest.mark.parametrize(
    ("entrada", "esperado"),
    [
        (
            "postgres://usuario:senha@postgres:5432/granatech",
            "postgresql+psycopg://usuario:senha@postgres:5432/granatech",
        ),
        (
            "postgresql://usuario:senha@postgres:5432/granatech",
            "postgresql+psycopg://usuario:senha@postgres:5432/granatech",
        ),
        (
            "  postgresql://usuario:senha@postgres/granatech?sslmode=require  ",
            "postgresql+psycopg://usuario:senha@postgres/granatech?sslmode=require",
        ),
        (
            "postgresql+psycopg://usuario:senha@postgres/granatech",
            "postgresql+psycopg://usuario:senha@postgres/granatech",
        ),
        ("sqlite:///./granatech_webhook.db", "sqlite:///./granatech_webhook.db"),
    ],
)
def test_normalizar_database_url(entrada: str, esperado: str) -> None:
    assert normalizar_database_url(entrada) == esperado


def test_settings_normaliza_postgres_ao_instanciar() -> None:
    settings = Settings(database_url="postgres://u:p@host/db")

    assert settings.database_url == "postgresql+psycopg://u:p@host/db"
    assert settings.banco_postgres is True
    assert settings.trust_proxy is False


def test_settings_from_env() -> None:
    settings = Settings.from_env(
        {
            "DATABASE_URL": "postgresql://u:p@host/db",
            "WEBHOOK_TOKEN": "token",
            "WEBHOOK_TOKEN_HEADER": "X-Token",
            "ALLOWED_IPS": " 10.0.0.1, 203.0.113.7 ,, ",
            "TRUST_PROXY": "true",
            "APP_ENV": "production",
            "LOG_LEVEL": "debug",
            "HOST": "127.0.0.1",
            "PORT": "9000",
        }
    )

    assert settings.database_url == "postgresql+psycopg://u:p@host/db"
    assert settings.webhook_token == "token"
    assert settings.webhook_token_header == "X-Token"
    assert settings.allowed_ips == ["10.0.0.1", "203.0.113.7"]
    assert settings.trust_proxy is True
    assert settings.producao is True
    assert settings.log_level == "DEBUG"
    assert settings.host == "127.0.0.1"
    assert settings.port == 9000


def test_settings_defaults() -> None:
    settings = Settings.from_env({})

    assert settings.database_url == DATABASE_URL_PADRAO
    assert settings.webhook_token == ""
    assert settings.webhook_token_header == "X-Webhook-Token"
    assert settings.allowed_ips == []
    assert settings.trust_proxy is False
    assert settings.app_env == "development"
    assert settings.producao is False
    assert settings.port == 8000
