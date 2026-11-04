"""Configuração da aplicação via pydantic-settings.

Os nomes das variáveis de ambiente são os campos em maiúsculas (sem prefixo),
preservando o contrato já configurado no Dokploy.
"""

import re
from collections.abc import Mapping
from functools import lru_cache
from typing import Annotated, Any

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, NoDecode, SettingsConfigDict

DATABASE_URL_PADRAO = "sqlite:///./granatech_webhook.db"

_POSTGRES_SCHEME = re.compile(r"^(postgres|postgresql)://", re.IGNORECASE)


def normalizar_database_url(url: str) -> str:
    """Normaliza URLs do PostgreSQL para o driver psycopg 3."""
    valor = url.strip()
    if _POSTGRES_SCHEME.match(valor):
        return _POSTGRES_SCHEME.sub("postgresql+psycopg://", valor, count=1)
    return valor


class Settings(BaseSettings):
    """Configuração tipada, lida do ambiente e, opcionalmente, de ``.env``."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,
    )

    database_url: str = DATABASE_URL_PADRAO
    webhook_token: str = ""
    webhook_token_header: str = "X-Webhook-Token"  # noqa: S105
    allowed_ips: Annotated[list[str], NoDecode] = Field(default_factory=list)
    trust_proxy: bool = False
    app_env: str = "development"
    log_level: str = "INFO"
    host: str = "0.0.0.0"  # noqa: S104
    port: int = 8000
    max_body_bytes: int = 262144

    @field_validator("database_url", mode="before")
    @classmethod
    def _normalizar_url_banco(cls, valor: str | None) -> str:
        if valor is None or not str(valor).strip():
            return DATABASE_URL_PADRAO
        return normalizar_database_url(str(valor))

    @field_validator("allowed_ips", mode="before")
    @classmethod
    def _parse_allowed_ips(cls, valor: object) -> object:
        if isinstance(valor, str):
            return [item.strip() for item in valor.split(",") if item.strip()]
        return valor

    @field_validator("trust_proxy", mode="before")
    @classmethod
    def _parse_bool_tolerante(cls, valor: object) -> object:
        if isinstance(valor, str):
            return valor.strip().lower() in {
                "1",
                "true",
                "t",
                "yes",
                "y",
                "on",
                "sim",
            }
        return valor

    @field_validator("port", "max_body_bytes", mode="before")
    @classmethod
    def _parse_inteiro_tolerante(cls, valor: object, info: Any) -> object:
        if valor is None:
            return 8000 if info.field_name == "port" else 262144
        try:
            return int(str(valor))
        except TypeError, ValueError:
            return 8000 if info.field_name == "port" else 262144

    @field_validator(
        "webhook_token",
        "webhook_token_header",
        "app_env",
        "host",
    )
    @classmethod
    def _limpar_strings(cls, valor: str) -> str:
        return valor.strip()

    @field_validator("log_level")
    @classmethod
    def _normalizar_log_level(cls, valor: str) -> str:
        return valor.strip().upper()

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
    def from_env(cls, env: Mapping[str, str] | None = None) -> Settings:
        """Compatibilidade com a API antiga (útil em testes)."""
        if env is None:
            return cls()
        # Valores explícitos para todos os campos: um mapeamento vazio deve
        # valer como "usar padrões", sem ler o ambiente real.
        return cls(
            database_url=env.get("DATABASE_URL") or DATABASE_URL_PADRAO,
            webhook_token=env.get("WEBHOOK_TOKEN", ""),
            webhook_token_header=env.get("WEBHOOK_TOKEN_HEADER", "X-Webhook-Token"),
            allowed_ips=env.get("ALLOWED_IPS", ""),
            trust_proxy=env.get("TRUST_PROXY", "false"),
            app_env=env.get("APP_ENV", "development"),
            log_level=env.get("LOG_LEVEL", "INFO"),
            host=env.get("HOST", "0.0.0.0"),  # noqa: S104
            port=env.get("PORT", "8000"),
            max_body_bytes=env.get("MAX_BODY_BYTES", "262144"),
        )


@lru_cache
def get_settings() -> Settings:
    """Configuração cacheada; nos testes use ``dependency_overrides``."""
    return Settings()
