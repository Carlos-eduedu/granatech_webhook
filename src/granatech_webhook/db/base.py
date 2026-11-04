"""Base declarativa, convenção de nomes e criação da engine."""

from datetime import UTC, datetime

from sqlalchemy import MetaData, create_engine
from sqlalchemy.engine import Engine
from sqlalchemy.orm import DeclarativeBase

NAMING_CONVENTION = {
    "ix": "ix_%(column_0_label)s",
    "uq": "uq_%(table_name)s_%(column_0_name)s",
    "ck": "ck_%(table_name)s_%(constraint_name)s",
    "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
    "pk": "pk_%(table_name)s",
}


class Base(DeclarativeBase):
    """Base declarativa de todos os modelos."""

    metadata = MetaData(naming_convention=NAMING_CONVENTION)


def agora_utc() -> datetime:
    """Timestamp UTC com timezone (não usar ``datetime.utcnow()``)."""
    return datetime.now(UTC)


def criar_engine(database_url: str) -> Engine:
    """Cria a engine com opções adequadas a SQLite (local/testes) ou PostgreSQL.

    Esta função é chamada no lifespan, nunca no import dos módulos.
    """
    if database_url.startswith("sqlite"):
        return create_engine(
            database_url,
            connect_args={"check_same_thread": False},
        )
    return create_engine(database_url, pool_pre_ping=True)
