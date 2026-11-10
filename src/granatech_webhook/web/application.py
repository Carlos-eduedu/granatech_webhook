"""Fábrica da aplicação FastAPI, handlers de exceção e log de requisições."""

import logging
import time
from collections.abc import Awaitable, Callable
from typing import Any

from fastapi import FastAPI, Request, Response
from fastapi.responses import JSONResponse

from ..log import contexto_request
from ..settings import Settings, get_settings
from .api.router import router as api_router
from .api.webhooks.dependencies import ip_cliente
from .api.webhooks.exceptions import WebhookError
from .lifespan import lifespan

logger = logging.getLogger(__name__)

# Health check do Dokploy bate a cada 30s: logar só o que interessa.
_ROTAS_SEM_LOG = frozenset({"/health", "/health/db"})


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

    @app.middleware("http")
    async def _log_requisicao(
        request: Request, call_next: Callable[[Request], Awaitable[Response]]
    ) -> Response:
        """Uma linha no início e outra no fim de cada requisição (sem query string)."""
        if request.url.path in _ROTAS_SEM_LOG:
            return await call_next(request)

        inicio = time.perf_counter()
        with contexto_request():
            logger.info(
                "requisição recebida metodo=%s rota=%s ip=%s content_length=%s",
                request.method,
                request.url.path,
                ip_cliente(request, settings),
                request.headers.get("content-length", "-"),
            )
            try:
                resposta = await call_next(request)
            except Exception:
                logger.exception(
                    "falha não tratada metodo=%s rota=%s",
                    request.method,
                    request.url.path,
                )
                raise

            duracao_ms = round((time.perf_counter() - inicio) * 1000, 1)
            logger.log(
                logging.ERROR if resposta.status_code >= 500 else logging.INFO,
                "resposta status=%s duracao_ms=%s metodo=%s rota=%s",
                resposta.status_code,
                duracao_ms,
                request.method,
                request.url.path,
            )
            return resposta

    return app


app = create_app()
