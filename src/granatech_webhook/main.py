"""Aplicação FastAPI do receptor de webhooks da Granatech."""

from __future__ import annotations

import logging
import sys
from contextlib import asynccontextmanager
from typing import Any

from fastapi import Depends, FastAPI
from fastapi.responses import JSONResponse
from sqlalchemy import text
from sqlalchemy.orm import Session

from . import models as _models  # noqa: F401 - registra as tabelas no metadata
from .config import Settings, get_settings
from .database import Base, engine, get_db
from .routers import webhooks

logger = logging.getLogger(__name__)


def configurar_logging(settings: Settings) -> None:
    """Logs de uma linha por evento, sempre em stdout (Dokploy lê os logs)."""
    nivel = getattr(logging, settings.log_level.upper(), logging.INFO)
    formato = "%(asctime)s %(levelname)s %(name)s %(message)s"
    if not logging.getLogger().handlers:
        logging.basicConfig(level=nivel, format=formato, stream=sys.stdout)
    else:
        logging.getLogger().setLevel(nivel)

    # O uvicorn configura os próprios handlers em stderr. O Dokploy lê stdout;
    # redireciona os logs do servidor sem perder o formato de uma linha.
    for nome_logger in ("uvicorn", "uvicorn.error", "uvicorn.access"):
        for handler in logging.getLogger(nome_logger).handlers:
            if isinstance(handler, logging.StreamHandler) and not isinstance(
                handler, logging.FileHandler
            ):
                handler.setStream(sys.stdout)
                handler.setFormatter(logging.Formatter(formato))


@asynccontextmanager
async def lifespan(app: FastAPI) -> Any:
    settings = get_settings()
    configurar_logging(settings)

    if settings.producao and not settings.webhook_token:
        logger.warning(
            "ATENÇÃO: APP_ENV=production e WEBHOOK_TOKEN vazio. "
            "O endpoint POST /webhooks/granatech está público na internet."
        )

    Base.metadata.create_all(bind=engine)
    logger.info(
        "webhook Granatech iniciado app_env=%s banco=%s",
        settings.app_env,
        "postgresql" if settings.banco_postgres else "sqlite",
    )
    try:
        yield
    finally:
        logger.info("webhook Granatech encerrado")


def create_app() -> FastAPI:
    app = FastAPI(
        title="Granatech Webhook",
        description=(
            "Receptor de webhooks da Granatech (consultas e propostas) — "
            "MEX Promotora"
        ),
        version="0.1.0",
        lifespan=lifespan,
    )
    app.include_router(webhooks.router)

    @app.get("/health", tags=["health"])
    def health() -> dict[str, str]:
        """Health check do container; não toca no banco."""
        return {"status": "ok"}

    @app.get("/health/db", tags=["health"])
    def health_db(db: Session = Depends(get_db)) -> Any:
        """Verifica a conexão com o banco sem expor detalhes do erro."""
        try:
            db.execute(text("SELECT 1"))
        except Exception as exc:  # noqa: BLE001
            logger.error(
                "health check do banco falhou: %s", type(exc).__name__
            )
            return JSONResponse(status_code=503, content={"db": "erro"})
        return {"db": "ok"}

    return app


app = create_app()
