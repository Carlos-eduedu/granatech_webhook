"""Modelos SQLAlchemy 2.x (estilo Mapped/mapped_column)."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from sqlalchemy import (
    JSON,
    Boolean,
    DateTime,
    ForeignKey,
    Integer,
    String,
    Text,
)
from sqlalchemy.orm import Mapped, mapped_column

from .database import Base


def agora_utc() -> datetime:
    """Timestamp UTC com timezone (não usar ``datetime.utcnow()``)."""
    return datetime.now(UTC)


class EventoWebhook(Base):
    """Log bruto de tudo que chega ao webhook."""

    __tablename__ = "granatech_webhook_eventos"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    recebido_em: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=agora_utc, nullable=False
    )
    tipo: Mapped[str | None] = mapped_column(String(255), nullable=True)
    rota: Mapped[str] = mapped_column(String(255), nullable=False)
    ip_origem: Mapped[str | None] = mapped_column(String(128), nullable=True)
    headers: Mapped[dict[str, str]] = mapped_column(JSON, default=dict, nullable=False)
    payload: Mapped[Any] = mapped_column(JSON, nullable=False)
    payload_hash: Mapped[str] = mapped_column(
        String(64), unique=True, index=True, nullable=False
    )
    processado: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    erro: Mapped[str | None] = mapped_column(Text, nullable=True)
    status_conhecido: Mapped[bool] = mapped_column(
        Boolean, default=False, nullable=False
    )


class Consulta(Base):
    """Estado atual de uma solicitação de consulta (chave: id_solicitacao)."""

    __tablename__ = "granatech_consultas"

    id_solicitacao: Mapped[str] = mapped_column(String(255), primary_key=True)
    id_proposta: Mapped[str | None] = mapped_column(
        String(255), nullable=True, index=True
    )
    cpf: Mapped[str] = mapped_column(String(11), nullable=False, index=True)
    user_id: Mapped[str] = mapped_column(String(255), nullable=False)
    corban_id: Mapped[int] = mapped_column(Integer, nullable=False)
    status: Mapped[str] = mapped_column(String(128), nullable=False)
    status_descricao: Mapped[str | None] = mapped_column(String(512), nullable=True)
    status_final: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    criado_em: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=agora_utc, nullable=False
    )
    atualizado_em: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=agora_utc, onupdate=agora_utc, nullable=False
    )
    ultimo_evento_id: Mapped[int | None] = mapped_column(
        ForeignKey("granatech_webhook_eventos.id"), nullable=True
    )


class Proposta(Base):
    """Estado atual de uma proposta (chave: id_proposta)."""

    __tablename__ = "granatech_propostas"

    id_proposta: Mapped[str] = mapped_column(String(255), primary_key=True)
    status_da_proposta: Mapped[str] = mapped_column(String(128), nullable=False)
    tipo_notificacao: Mapped[str] = mapped_column(String(128), nullable=False)
    informacoes: Mapped[str] = mapped_column(Text, nullable=False)
    status_descricao: Mapped[str | None] = mapped_column(String(512), nullable=True)
    status_final: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    cpf: Mapped[str | None] = mapped_column(String(11), nullable=True, index=True)
    criado_em: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=agora_utc, nullable=False
    )
    atualizado_em: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=agora_utc, onupdate=agora_utc, nullable=False
    )
    ultimo_evento_id: Mapped[int | None] = mapped_column(
        ForeignKey("granatech_webhook_eventos.id"), nullable=True
    )


class PropostaHistorico(Base):
    """Uma linha por notificação de proposta recebida."""

    __tablename__ = "granatech_propostas_historico"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    id_proposta: Mapped[str] = mapped_column(String(255), nullable=False, index=True)
    status_da_proposta: Mapped[str] = mapped_column(String(128), nullable=False)
    tipo_notificacao: Mapped[str] = mapped_column(String(128), nullable=False)
    informacoes: Mapped[str] = mapped_column(Text, nullable=False)
    recebido_em: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=agora_utc, nullable=False
    )
    evento_id: Mapped[int | None] = mapped_column(
        ForeignKey("granatech_webhook_eventos.id"), nullable=True, index=True
    )


# Aliases curtos para conveniência de imports em testes/consumidores.
Evento = EventoWebhook
HistoricoProposta = PropostaHistorico
