"""Ciclo de vida da aplicação: engine, session factory e logging."""

import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from sqlalchemy.orm import sessionmaker

from ..db.base import criar_engine
from ..log import configurar_logging
from ..settings import get_settings

logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    """Cria a engine no startup e a descarta no shutdown.

    Nenhum módulo cria engine no import: isso mantém testes e CLI leves e
    evita conexões abertas antes do processo estar pronto.
    """
    settings = getattr(app.state, "settings", None) or get_settings()
    configurar_logging(settings)

    if settings.producao and not settings.webhook_token:
        logger.warning(
            "ATENÇÃO: APP_ENV=production e WEBHOOK_TOKEN vazio. "
            "O endpoint POST /webhooks/granatech está público na internet."
        )

    engine = criar_engine(settings.database_url)
    app.state.engine = engine
    app.state.session_factory = sessionmaker(
        bind=engine,
        autoflush=False,
        autocommit=False,
        expire_on_commit=False,
    )

    logger.info(
        "webhook Granatech iniciado app_env=%s banco=%s",
        settings.app_env,
        "postgresql" if settings.banco_postgres else "sqlite",
    )
    try:
        yield
    finally:
        engine.dispose()
        logger.info("webhook Granatech encerrado")
