"""Queries de consultas (sem regra de negócio)."""

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..models import Consulta


def buscar(db: Session, id_solicitacao: str) -> Consulta | None:
    return db.get(Consulta, id_solicitacao)


def bloquear(db: Session, id_solicitacao: str) -> Consulta | None:
    """``SELECT ... FOR UPDATE``; ignorado fora do PostgreSQL."""
    if db.bind is None or db.bind.dialect.name != "postgresql":
        return None
    return db.execute(
        select(Consulta).where(Consulta.id_solicitacao == id_solicitacao).with_for_update()
    ).scalar_one_or_none()


def buscar_cpf_por_proposta(db: Session, id_proposta: str) -> str | None:
    return db.scalar(
        select(Consulta.cpf)
        .where(Consulta.id_proposta == id_proposta, Consulta.cpf.is_not(None))
        .order_by(Consulta.atualizado_em.desc())
        .limit(1)
    )


def adicionar(db: Session, consulta: Consulta) -> None:
    db.add(consulta)
