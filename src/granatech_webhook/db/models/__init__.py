"""Modelos SQLAlchemy registrados no metadata."""

from .consulta import Consulta
from .evento import EventoWebhook
from .proposta import Proposta, PropostaHistorico

__all__ = [
    "Consulta",
    "EventoWebhook",
    "Proposta",
    "PropostaHistorico",
]
