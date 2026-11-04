"""ASGI de compatibilidade: ``granatech_webhook.main:app``.

A implementação real vive em :mod:`granatech_webhook.web.application`.
"""

from .web.application import app, create_app

__all__ = ["app", "create_app"]
