"""baseline: schema criado pelo create_all original

Revision ID: 0001_baseline
Revises:
Create Date: 2026-11-04

"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0001_baseline"
down_revision: str | Sequence[str] | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "granatech_webhook_eventos",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("recebido_em", sa.DateTime(timezone=True), nullable=False),
        sa.Column("tipo", sa.String(length=255), nullable=True),
        sa.Column("rota", sa.String(length=255), nullable=False),
        sa.Column("ip_origem", sa.String(length=128), nullable=True),
        sa.Column("headers", sa.JSON(), nullable=False),
        sa.Column("payload", sa.JSON(), nullable=False),
        sa.Column("payload_hash", sa.String(length=64), nullable=False),
        sa.Column("processado", sa.Boolean(), nullable=False),
        sa.Column("erro", sa.Text(), nullable=True),
        sa.Column("status_conhecido", sa.Boolean(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_granatech_webhook_eventos_payload_hash",
        "granatech_webhook_eventos",
        ["payload_hash"],
        unique=True,
    )

    op.create_table(
        "granatech_consultas",
        sa.Column("id_solicitacao", sa.String(length=255), nullable=False),
        sa.Column("id_proposta", sa.String(length=255), nullable=True),
        sa.Column("cpf", sa.String(length=11), nullable=False),
        sa.Column("user_id", sa.String(length=255), nullable=False),
        sa.Column("corban_id", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(length=128), nullable=False),
        sa.Column("status_descricao", sa.String(length=512), nullable=True),
        sa.Column("status_final", sa.Boolean(), nullable=False),
        sa.Column("criado_em", sa.DateTime(timezone=True), nullable=False),
        sa.Column("atualizado_em", sa.DateTime(timezone=True), nullable=False),
        sa.Column("ultimo_evento_id", sa.Integer(), nullable=True),
        sa.ForeignKeyConstraint(
            ["ultimo_evento_id"],
            ["granatech_webhook_eventos.id"],
            name="granatech_consultas_ultimo_evento_id_fkey",
        ),
        sa.PrimaryKeyConstraint("id_solicitacao"),
    )
    op.create_index(
        "ix_granatech_consultas_cpf", "granatech_consultas", ["cpf"]
    )
    op.create_index(
        "ix_granatech_consultas_id_proposta",
        "granatech_consultas",
        ["id_proposta"],
    )

    op.create_table(
        "granatech_propostas",
        sa.Column("id_proposta", sa.String(length=255), nullable=False),
        sa.Column("status_da_proposta", sa.String(length=128), nullable=False),
        sa.Column("tipo_notificacao", sa.String(length=128), nullable=False),
        sa.Column("informacoes", sa.Text(), nullable=False),
        sa.Column("status_descricao", sa.String(length=512), nullable=True),
        sa.Column("status_final", sa.Boolean(), nullable=False),
        sa.Column("cpf", sa.String(length=11), nullable=True),
        sa.Column("criado_em", sa.DateTime(timezone=True), nullable=False),
        sa.Column("atualizado_em", sa.DateTime(timezone=True), nullable=False),
        sa.Column("ultimo_evento_id", sa.Integer(), nullable=True),
        sa.ForeignKeyConstraint(
            ["ultimo_evento_id"],
            ["granatech_webhook_eventos.id"],
            name="granatech_propostas_ultimo_evento_id_fkey",
        ),
        sa.PrimaryKeyConstraint("id_proposta"),
    )
    op.create_index("ix_granatech_propostas_cpf", "granatech_propostas", ["cpf"])

    op.create_table(
        "granatech_propostas_historico",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("id_proposta", sa.String(length=255), nullable=False),
        sa.Column("status_da_proposta", sa.String(length=128), nullable=False),
        sa.Column("tipo_notificacao", sa.String(length=128), nullable=False),
        sa.Column("informacoes", sa.Text(), nullable=False),
        sa.Column("recebido_em", sa.DateTime(timezone=True), nullable=False),
        sa.Column("evento_id", sa.Integer(), nullable=True),
        sa.ForeignKeyConstraint(
            ["evento_id"],
            ["granatech_webhook_eventos.id"],
            name="granatech_propostas_historico_evento_id_fkey",
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_granatech_propostas_historico_id_proposta",
        "granatech_propostas_historico",
        ["id_proposta"],
    )
    op.create_index(
        "ix_granatech_propostas_historico_evento_id",
        "granatech_propostas_historico",
        ["evento_id"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_granatech_propostas_historico_evento_id",
        table_name="granatech_propostas_historico",
    )
    op.drop_index(
        "ix_granatech_propostas_historico_id_proposta",
        table_name="granatech_propostas_historico",
    )
    op.drop_table("granatech_propostas_historico")

    op.drop_index(
        "ix_granatech_propostas_cpf", table_name="granatech_propostas"
    )
    op.drop_table("granatech_propostas")

    op.drop_index(
        "ix_granatech_consultas_id_proposta", table_name="granatech_consultas"
    )
    op.drop_index("ix_granatech_consultas_cpf", table_name="granatech_consultas")
    op.drop_table("granatech_consultas")

    op.drop_index(
        "ix_granatech_webhook_eventos_payload_hash",
        table_name="granatech_webhook_eventos",
    )
    op.drop_table("granatech_webhook_eventos")
