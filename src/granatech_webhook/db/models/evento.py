"""Log bruto de todos os webhooks recebidos."""

from datetime import datetime
from typing import Any

from sqlalchemy import JSON, Boolean, DateTime, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from ..base import Base, agora_utc


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
    payload_hash: Mapped[str] = mapped_column(String(64), index=True, nullable=False)
    # Entidade afetada pelo evento ("consulta:<id>" ou "proposta:<id>").
    # Eventos sem entidade (JSON malformado, tipo desconhecido, validação)
    # continuam deduplicados apenas pelo hash.
    chave_entidade: Mapped[str | None] = mapped_column(String(255), nullable=True, index=True)
    processado: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    erro: Mapped[str | None] = mapped_column(Text, nullable=True)
    status_conhecido: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
