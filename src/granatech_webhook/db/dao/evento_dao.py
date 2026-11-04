"""Queries de eventos brutos (sem regra de negócio)."""

from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..models import EventoWebhook


def buscar_ultimo_por_entidade(db: Session, chave_entidade: str) -> EventoWebhook | None:
    return db.scalar(
        select(EventoWebhook)
        .where(EventoWebhook.chave_entidade == chave_entidade)
        .order_by(EventoWebhook.id.desc())
        .limit(1)
    )


def buscar_ultimo_por_hash(db: Session, payload_hash: str) -> EventoWebhook | None:
    return db.scalar(
        select(EventoWebhook)
        .where(EventoWebhook.payload_hash == payload_hash)
        .order_by(EventoWebhook.id.desc())
        .limit(1)
    )


def criar(
    db: Session,
    *,
    tipo: str | None,
    rota: str,
    ip_origem: str | None,
    headers: dict[str, str],
    payload: Any,
    payload_hash: str,
    chave_entidade: str | None,
    erro: str | None = None,
) -> EventoWebhook:
    evento = EventoWebhook(
        tipo=tipo,
        rota=rota,
        ip_origem=ip_origem,
        headers=headers,
        payload=payload,
        payload_hash=payload_hash,
        chave_entidade=chave_entidade,
        processado=False,
        erro=erro,
        status_conhecido=False,
    )
    db.add(evento)
    db.flush()
    return evento
