"""Estado atual de uma consulta de saldo/margem."""

from datetime import datetime

from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from ..base import Base, agora_utc


class Consulta(Base):
    """Estado atual de uma solicitação de consulta (chave: id_solicitacao)."""

    __tablename__ = "granatech_consultas"

    id_solicitacao: Mapped[str] = mapped_column(String(255), primary_key=True)
    id_proposta: Mapped[str | None] = mapped_column(String(255), nullable=True, index=True)
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
