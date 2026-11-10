"""Configuração de logging em stdout, request_id e mascaramento de CPF."""

import logging
import re
import sys
import uuid
from collections.abc import Iterator
from contextlib import contextmanager
from contextvars import ContextVar

from .settings import Settings

_CPF_RE = re.compile(r"(?<!\d)(\d{3})\.?\d{3}\.?\d{3}-?(\d{2})(?!\d)")
_FORMATO = "%(asctime)s %(levelname)s request_id=%(request_id)s logger=%(name)s %(message)s"
_LOGGERS_UVICORN = ("uvicorn", "uvicorn.error", "uvicorn.access")

_request_id: ContextVar[str] = ContextVar("request_id", default="-")


def _mascarar(texto: str) -> str:
    return _CPF_RE.sub(r"\1.***.***-\2", texto)


class FiltroCpf(logging.Filter):
    """Remove CPF completo de mensagens e argumentos de log (LGPD)."""

    def filter(self, record: logging.LogRecord) -> bool:
        if isinstance(record.msg, str):
            record.msg = _mascarar(record.msg)
        if isinstance(record.args, tuple):
            record.args = tuple(
                _mascarar(argumento) if isinstance(argumento, str) else argumento
                for argumento in record.args
            )
        elif isinstance(record.args, dict):
            record.args = {
                chave: _mascarar(valor) if isinstance(valor, str) else valor
                for chave, valor in record.args.items()
            }
        return True


class FiltroContexto(logging.Filter):
    """Inclui o request_id corrente em toda linha (``-`` fora de requisição)."""

    def filter(self, record: logging.LogRecord) -> bool:
        record.request_id = _request_id.get()
        return True


class FormatterComMascara(logging.Formatter):
    """Mascara CPF no texto final — inclusive no stack trace de ``logger.exception``."""

    def format(self, record: logging.LogRecord) -> str:
        if not hasattr(record, "request_id"):
            record.request_id = "-"
        return _mascarar(super().format(record))


@contextmanager
def contexto_request(identificador: str | None = None) -> Iterator[str]:
    """Define o request_id (correlation_id) das linhas emitidas dentro do bloco."""
    atual = identificador or uuid.uuid4().hex[:16]
    token = _request_id.set(atual)
    try:
        yield atual
    finally:
        _request_id.reset(token)


def _handlers_relevantes() -> list[logging.Handler]:
    handlers = list(logging.getLogger().handlers)
    for nome_logger in _LOGGERS_UVICORN:
        handlers.extend(logging.getLogger(nome_logger).handlers)
    return list(dict.fromkeys(handlers))


def configurar_logging(settings: Settings) -> None:
    """Logs de uma linha por evento, sempre em stdout (Dokploy lê os logs)."""
    nivel = getattr(logging, settings.log_level.upper(), logging.INFO)
    root = logging.getLogger()
    if not root.handlers:
        handler = logging.StreamHandler(sys.stdout)
        handler.setFormatter(FormatterComMascara(_FORMATO))
        root.addHandler(handler)
    root.setLevel(nivel)

    # O uvicorn configura os próprios handlers em stderr e com nível fixo em
    # INFO. O Dokploy lê stdout: alinha stream, formato e nível com a app.
    for nome_logger in _LOGGERS_UVICORN:
        logger_uvicorn = logging.getLogger(nome_logger)
        logger_uvicorn.setLevel(nivel)
        for handler_uvicorn in logger_uvicorn.handlers:
            if isinstance(handler_uvicorn, logging.StreamHandler) and not isinstance(
                handler_uvicorn, logging.FileHandler
            ):
                handler_uvicorn.setStream(sys.stdout)
                handler_uvicorn.setFormatter(FormatterComMascara(_FORMATO))

    for handler_final in _handlers_relevantes():
        if not any(isinstance(filtro, FiltroCpf) for filtro in handler_final.filters):
            handler_final.addFilter(FiltroCpf())
        if not any(isinstance(filtro, FiltroContexto) for filtro in handler_final.filters):
            handler_final.addFilter(FiltroContexto())
