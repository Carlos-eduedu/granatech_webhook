"""Fábrica da aplicação FastAPI e handlers de exceção."""

import logging
from typing import Any

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from ..settings import Settings, get_settings
from .api.router import router as api_router
from .api.webhooks.exceptions import WebhookError
from .lifespan import lifespan

logger = logging.getLogger(__name__)


def _corpo_erro(erro: WebhookError) -> dict[str, Any]:
    """Mantém exatamente o corpo de erro do contrato antigo."""
    corpo: dict[str, Any] = {"detail": erro.detail}
    if erro.evento_id is not None:
        corpo["evento_id"] = erro.evento_id
    if erro.erro is not None:
        corpo["erro"] = erro.erro
    return corpo


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or get_settings()
    app = FastAPI(
        title="Granatech Webhook",
        description=("Receptor de webhooks da Granatech (consultas e propostas) — MEX Promotora"),
        version="0.1.0",
        lifespan=lifespan,
        docs_url="/docs" if settings.exibir_docs else None,
        redoc_url="/redoc" if settings.exibir_docs else None,
        openapi_url="/openapi.json" if settings.exibir_docs else None,
    )
    app.state.settings = settings
    app.dependency_overrides[get_settings] = lambda: settings
    app.include_router(api_router)

    @app.exception_handler(WebhookError)
    async def _webhook_error_handler(_request: Request, exc: WebhookError) -> JSONResponse:
        return JSONResponse(status_code=exc.status_code, content=_corpo_erro(exc))

    return app


app = create_app()
