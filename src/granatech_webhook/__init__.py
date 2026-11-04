"""Receptor de webhooks da Granatech (consultas e propostas)."""

from __future__ import annotations

import os


def main() -> None:
    """Sobe o servidor com uvicorn (comando ``granatech-webhook``)."""
    import uvicorn

    host = os.environ.get("HOST", "0.0.0.0")
    try:
        port = int(os.environ.get("PORT", "8000"))
    except ValueError:
        port = 8000

    # Sem access log do uvicorn: a query string pode conter ?token=.
    # O log por evento (sem token/CPF) já é emitido pela aplicação.
    uvicorn.run(
        "granatech_webhook.main:app", host=host, port=port, access_log=False
    )
