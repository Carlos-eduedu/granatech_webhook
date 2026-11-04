"""idempotencia por entidade

Revision ID: 0002_idempotencia_por_entidade
Revises: 0001_baseline
Create Date: 2026-11-04

"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0002_idempotencia_por_entidade"
down_revision: str | Sequence[str] | None = "0001_baseline"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_TABELA = "granatech_webhook_eventos"
_INDICE_HASH = "ix_granatech_webhook_eventos_payload_hash"
_INDICE_ENTIDADE = "ix_granatech_webhook_eventos_chave_entidade"


def _nome_indice_hash(bind: sa.engine.Connection) -> str | None:
    """Descobre o nome real do índice (o create_all antigo usava o padrão)."""
    inspetor = sa.inspect(bind)
    for indice in inspetor.get_indexes(_TABELA):
        if indice.get("column_names") == ["payload_hash"]:
            return str(indice["name"])
    return None


def _criar_coluna_e_indices() -> None:
    op.add_column(
        _TABELA,
        sa.Column("chave_entidade", sa.String(length=255), nullable=True),
    )
    op.create_index(_INDICE_ENTIDADE, _TABELA, ["chave_entidade"], unique=False)
    op.create_index(_INDICE_HASH, _TABELA, ["payload_hash"], unique=False)


def upgrade() -> None:
    bind = op.get_bind()
    nome_indice = _nome_indice_hash(bind)
    if nome_indice is not None:
        op.drop_index(nome_indice, table_name=_TABELA)

    if bind.dialect.name == "sqlite":
        with op.batch_alter_table(_TABELA) as batch_op:
            batch_op.add_column(
                sa.Column("chave_entidade", sa.String(length=255), nullable=True)
            )
            batch_op.create_index(
                _INDICE_ENTIDADE, ["chave_entidade"], unique=False
            )
            batch_op.create_index(_INDICE_HASH, ["payload_hash"], unique=False)
    else:
        _criar_coluna_e_indices()


def downgrade() -> None:
    bind = op.get_bind()

    if bind.dialect.name == "sqlite":
        with op.batch_alter_table(_TABELA) as batch_op:
            batch_op.drop_index(_INDICE_ENTIDADE)
            batch_op.drop_index(_INDICE_HASH)
            batch_op.create_index(
                _INDICE_HASH, ["payload_hash"], unique=True
            )
            batch_op.drop_column("chave_entidade")
    else:
        op.drop_index(_INDICE_ENTIDADE, table_name=_TABELA)
        op.drop_index(_INDICE_HASH, table_name=_TABELA)
        op.create_index(_INDICE_HASH, _TABELA, ["payload_hash"], unique=True)
        op.drop_column(_TABELA, "chave_entidade")
