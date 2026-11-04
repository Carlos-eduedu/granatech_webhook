"""Status conhecidos da Granatech e suas descrições em PT-BR.

Não são usados como enums rígidos nos schemas: a Granatech pode criar status
novos e o webhook deve continuar aceitando o payload.
"""

# ---------------------------------------------------------------------------
# Consultas
# ---------------------------------------------------------------------------

CONSULTA_STATUS_DESCRICOES: dict[str, str] = {
    "AWAITING_CLIENT_AUTHORIZATION": (
        "Aguardando autorização do cliente (assinatura do termo de consentimento)"
    ),
    "PROCESSING": "Em processamento",
    "SUCCESS": "Concluída com sucesso",
    "PENDING": "Pendente",
    "NO_MARGIN": "Cliente sem margem disponível",
    "USED": "Solicitação já utilizada",
    "UNEXPECTED_ERROR": "Erro inesperado no processamento",
}

CONSULTA_STATUS_FINAIS: frozenset[str] = frozenset(
    {"SUCCESS", "NO_MARGIN", "USED", "UNEXPECTED_ERROR"}
)

# ---------------------------------------------------------------------------
# Propostas
# ---------------------------------------------------------------------------
# A combinação (status_da_proposta, tipo_notificacao) é o que define o evento.
# A Granatech usa "PAYED" (grafia deles); não corrigimos o valor.

PROPOSTA_EVENTOS_DESCRICOES: dict[tuple[str, str], str] = {
    (
        "PENDING_CONFIRMATION",
        "AGUARDANDO_CONFIRMACAO",
    ): "Proposta criada na plataforma",
    (
        "PENDING_USER_REVIEW",
        "AGUARDANDO_REVISAO_USUARIO",
    ): "Pendências na criação da proposta",
    (
        "PENDING_USER_REVIEW",
        "FALHA_PAGAMENTO",
    ): "Falha no pagamento — revisar dados bancários",
    (
        "PENDING_FORMALIZATION",
        "AGUARDANDO_FORMALIZACAO",
    ): "Criada no banco; aguardando formalização/segurança de identidade",
    (
        "PENDING_FORMALIZATION",
        "FORMALIZACAO_EM_ANDAMENTO",
    ): "Saldo bloqueado, aguardando formalização",
    (
        "PENDING_FORMALIZATION",
        "BLOQUEIO_DE_SALDO_EM_ANDAMENTO",
    ): "Bloqueio de saldo em andamento",
    (
        "PENDING_FORMALIZATION",
        "BLOQUEIO_SALDO",
    ): "Saldo bloqueado, pagamento em andamento",
    (
        "PENDING_BANK_ANALYSIS",
        "AGUARDANDO_ANALISE_BANCO",
    ): "Banco analisando a segurança de identidade",
    (
        "PENDING_PAYMENT",
        "SUCESSO_SEGURANCA_IDENTIDADE",
    ): "Segurança de identidade aprovada",
    (
        "PENDING_REFORMALIZATION",
        "REFAZER_SEGURANCA_IDENTIDADE",
    ): "Cliente precisa refazer a segurança de identidade",
    (
        "REPROVED",
        "REPROVADO",
    ): "Segurança de identidade reprovada",
    (
        "CANCELED",
        "PROPOSTA_CANCELADA",
    ): (
        "Cancelada no banco (motivo em informacoes, ex.: sem conta FGTS, "
        "saldo insuficiente, valor indisponível, protocolo removido na CEF)"
    ),
    (
        "CANCELED",
        "BLOQUEIO_DE_SALDO_CANCELADO",
    ): "Bloqueio de saldo cancelado",
    (
        "PAYED",
        "PAGO",
    ): "Proposta paga",
    (
        "PAYED",
        "PROPOSTA_PAGA",
    ): "Proposta paga",
}

PROPOSTA_STATUS_FINAIS: frozenset[str] = frozenset({"PAYED", "CANCELED", "REPROVED"})

TIPOS_CONHECIDOS: frozenset[str] = frozenset({"consulta", "proposta"})

PREFIXO_ERRO_PROCESSAMENTO = "erro ao processar:"
