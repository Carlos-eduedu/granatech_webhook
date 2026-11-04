"""Configuração de logging em stdout e mascaramento de CPF."""

import logging
import re
import sys

from .settings import Settings

_CPF_RE = re.compile(r"(?<!\d)(\d{3})\.?\d{3}\.?\d{3}-?(\d{2})(?!\d)")
_FORMATO = "%(asctime)s %(levelname)s %(name)s %(message)s"
_LOGGERS_UVICORN = ("uvicorn", "uvicorn.error", "uvicorn.access")


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


def _adicionar_filtro_cpf() -> None:
    for handler in logging.getLogger().handlers:
        handler.addFilter(FiltroCpf())


def configurar_logging(settings: Settings) -> None:
    """Logs de uma linha por evento, sempre em stdout (Dokploy lê os logs)."""
    nivel = getattr(logging, settings.log_level.upper(), logging.INFO)
    if not logging.getLogger().handlers:
        logging.basicConfig(level=nivel, format=_FORMATO, stream=sys.stdout)
    else:
        logging.getLogger().setLevel(nivel)

    # O uvicorn configura os próprios handlers em stderr. O Dokploy lê stdout;
    # redireciona os logs do servidor sem perder o formato de uma linha.
    for nome_logger in _LOGGERS_UVICORN:
        for handler in logging.getLogger(nome_logger).handlers:
            if isinstance(handler, logging.StreamHandler) and not isinstance(
                handler, logging.FileHandler
            ):
                handler.setStream(sys.stdout)
                handler.setFormatter(logging.Formatter(_FORMATO))

    _adicionar_filtro_cpf()
