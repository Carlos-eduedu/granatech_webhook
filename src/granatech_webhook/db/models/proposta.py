"""Estado atual e histórico de propostas."""

from datetime import datetime

from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from ..base import Base, agora_utc


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
