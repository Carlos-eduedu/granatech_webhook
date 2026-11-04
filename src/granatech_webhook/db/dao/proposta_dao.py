"""Queries de propostas e histórico (sem regra de negócio)."""

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..models import Proposta, PropostaHistorico


def buscar(db: Session, id_proposta: str) -> Proposta | None:
    return db.get(Proposta, id_proposta)


def bloquear(db: Session, id_proposta: str) -> Proposta | None:
    """``SELECT ... FOR UPDATE``; ignorado fora do PostgreSQL."""
    if db.bind is None or db.bind.dialect.name != "postgresql":
        return None
    return db.execute(
        select(Proposta).where(Proposta.id_proposta == id_proposta).with_for_update()
    ).scalar_one_or_none()


def adicionar(db: Session, proposta: Proposta) -> None:
    db.add(proposta)


def adicionar_historico(db: Session, historico: PropostaHistorico) -> None:
    db.add(historico)
