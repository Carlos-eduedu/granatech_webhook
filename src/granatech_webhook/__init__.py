"""Receptor de webhooks da Granatech (consultas e propostas)."""


def main() -> None:
    """Sobe o servidor com uvicorn (comando ``granatech-webhook``)."""
    import uvicorn

    from .settings import get_settings

    settings = get_settings()
    # Sem access log do uvicorn: a query string pode conter ?token=.
    # O log por evento (sem token/CPF) já é emitido pela aplicação.
    uvicorn.run(
        "granatech_webhook.web.application:app",
        host=settings.host,
        port=settings.port,
        access_log=False,
    )
