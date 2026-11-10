"""campos opcionais na consulta

Revision ID: 0003_campos_opcionais_consulta
Revises: 0002_idempotencia_por_entidade
Create Date: 2026-11-10

O evento mínimo de consulta da Granatech traz só id_consulta, cpf, status e
tipo. ``user_id`` e ``corban_id`` passam a aceitar NULL.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0003_campos_opcionais_consulta"
down_revision: str | Sequence[str] | None = "0002_idempotencia_por_entidade"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_TABELA = "granatech_consultas"


def _alterar_nullable(*, nullable: bool) -> None:
    if op.get_bind().dialect.name == "sqlite":
        with op.batch_alter_table(_TABELA) as batch_op:
            batch_op.alter_column("user_id", existing_type=sa.String(length=255), nullable=nullable)
            batch_op.alter_column("corban_id", existing_type=sa.Integer(), nullable=nullable)
        return

    op.alter_column(_TABELA, "user_id", existing_type=sa.String(length=255), nullable=nullable)
    op.alter_column(_TABELA, "corban_id", existing_type=sa.Integer(), nullable=nullable)


def upgrade() -> None:
    _alterar_nullable(nullable=True)


def downgrade() -> None:
    # Voltar a NOT NULL falha se existir consulta sem os campos, e é assim que
    # deve ser: quem reverter precisa decidir o que fazer com essas linhas.
    # Não preenchemos valores inventados aqui.
    _alterar_nullable(nullable=False)
