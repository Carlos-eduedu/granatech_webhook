"""Configuração lida diretamente das variáveis de ambiente."""

from __future__ import annotations

import os
import re
from collections.abc import Mapping
from pydantic import BaseModel, Field, field_validator

DATABASE_URL_PADRAO = "sqlite:///./granatech_webhook.db"

_POSTGRES_SCHEME = re.compile(r"^(postgres|postgresql)://", re.IGNORECASE)


def normalizar_database_url(url: str) -> str:
    """Normaliza URLs do PostgreSQL para o driver psycopg 3.

    O Dokploy entrega a URL como ``postgresql://...`` (ou, em alguns casos,
    ``postgres://...``). O SQLAlchemy precisa do driver explícito:
    ``postgresql+psycopg://...``.
    """
    valor = url.strip()
    if _POSTGRES_SCHEME.match(valor):
        return _POSTGRES_SCHEME.sub("postgresql+psycopg://", valor, count=1)
    return valor


def _parse_bool(valor: str | None, padrao: bool = False) -> bool:
    if valor is None:
        return padrao
    return valor.strip().lower() in {"1", "true", "t", "yes", "y", "on", "sim"}


def _parse_lista(valor: str | None) -> list[str]:
    if not valor:
        return []
    return [item.strip() for item in valor.split(",") if item.strip()]


def _parse_inteiro(valor: str | None, padrao: int) -> int:
    if valor is None:
        return padrao
    try:
        return int(valor)
    except (TypeError, ValueError):
        return padrao


class Settings(BaseModel):
    """Configuração da aplicação (sem pydantic-settings, só ``os.environ``)."""

    database_url: str = DATABASE_URL_PADRAO
    webhook_token: str = ""
    webhook_token_header: str = "X-Webhook-Token"
    allowed_ips: list[str] = Field(default_factory=list)
    trust_proxy: bool = False
    app_env: str = "development"
    log_level: str = "INFO"
    host: str = "0.0.0.0"
    port: int = 8000
    max_body_bytes: int = 262144

    @field_validator("database_url")
    @classmethod
    def _normalizar_url_banco(cls, valor: str) -> str:
        return normalizar_database_url(valor)

    @field_validator("webhook_token", "webhook_token_header", "app_env", "log_level", "host")
    @classmethod
    def _limpar_strings(cls, valor: str) -> str:
        return valor.strip()

    @property
    def producao(self) -> bool:
        return self.app_env.strip().lower() == "production"

    @property
    def exibir_docs(self) -> bool:
        """Documentação aberta apenas em ambientes não produtivos."""
        return self.app_env.strip().lower() in {
            "development",
            "test",
            "staging",
        }

    @property
    def banco_postgres(self) -> bool:
        return self.database_url.startswith("postgresql")

    @classmethod
    def from_env(cls, env: Mapping[str, str] | None = None) -> "Settings":
        ambiente = os.environ if env is None else env
        porta_bruta = ambiente.get("PORT", "8000")
        try:
            porta = int(porta_bruta)
        except (TypeError, ValueError):
            porta = 8000

        return cls(
            database_url=ambiente.get("DATABASE_URL") or DATABASE_URL_PADRAO,
            webhook_token=ambiente.get("WEBHOOK_TOKEN", ""),
            webhook_token_header=ambiente.get(
                "WEBHOOK_TOKEN_HEADER", "X-Webhook-Token"
            ),
            allowed_ips=_parse_lista(ambiente.get("ALLOWED_IPS", "")),
            trust_proxy=_parse_bool(ambiente.get("TRUST_PROXY")),
            app_env=ambiente.get("APP_ENV", "development"),
            log_level=ambiente.get("LOG_LEVEL", "INFO").upper(),
            host=ambiente.get("HOST", "0.0.0.0"),
            port=porta,
            max_body_bytes=_parse_inteiro(
                ambiente.get("MAX_BODY_BYTES"), 262144
            ),
        )


def get_settings() -> Settings:
    """Retorna a configuração lida do ambiente na hora da chamada.

    Não há cache: assim testes e rotação de configuração enxergam o ambiente
    atual. O custo é desprezível (um modelo Pydantic pequeno por request).
    """
    return Settings.from_env()


def _limpar_cache_settings() -> None:
    """Compatibilidade: não existe cache para limpar."""


get_settings.cache_clear = _limpar_cache_settings  # type: ignore[attr-defined]


# Alias em inglês para quem preferir esse nome (a implementação é a mesma).
normalize_database_url = normalizar_database_url
