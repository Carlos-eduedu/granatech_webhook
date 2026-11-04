"""Regras de persistência dos webhooks da Granatech."""

from __future__ import annotations

import hashlib
import json
import logging
from dataclasses import dataclass
from typing import Any

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from .enums import (
    CONSULTA_STATUS_DESCRICOES,
    CONSULTA_STATUS_FINAIS,
    PROPOSTA_EVENTOS_DESCRICOES,
    PROPOSTA_STATUS_FINAIS,
)
from .models import (
    Consulta,
    EventoWebhook,
    Proposta,
    PropostaHistorico,
    agora_utc,
)
from .schemas import ConsultaPayload, PropostaPayload

logger = logging.getLogger(__name__)

PREFIXO_ERRO_PROCESSAMENTO = "erro ao processar:"


@dataclass(frozen=True)
class ResultadoRegistro:
    """Resultado do registro do evento bruto.

    ``duplicado`` indica que o evento é uma retentativa idêntica e não deve ser
    processado. ``reprocessar`` indica que o evento existente falhou no
    processamento (não na validação) e deve ser reaproveitado.
    """

    evento: EventoWebhook
    duplicado: bool
    reprocessar: bool = False


# ---------------------------------------------------------------------------
# Utilitários
# ---------------------------------------------------------------------------


def hash_payload(payload: Any) -> str:
    """SHA-256 do JSON canonizado (``sort_keys=True``) para idempotência."""
    canonico = json.dumps(payload, sort_keys=True)
    return hashlib.sha256(canonico.encode("utf-8")).hexdigest()


def hash_corpo_bytes(body: bytes) -> str:
    """Hash do corpo cru, usado quando o JSON é malformado."""
    return hashlib.sha256(body).hexdigest()


def chave_entidade_consulta(id_solicitacao: str) -> str:
    return f"consulta:{id_solicitacao}"[:255]


def chave_entidade_proposta(id_proposta: str) -> str:
    return f"proposta:{id_proposta}"[:255]


def mascarar_cpf(cpf: str | None) -> str:
    """Retorna o CPF mascarado (``331.***.***-41``); nunca o valor completo."""
    if not cpf:
        return "***"
    apenas_digitos = "".join(caractere for caractere in cpf if caractere.isdigit())
    if len(apenas_digitos) < 5:
        return "***"
    return f"{apenas_digitos[:3]}.***.***-{apenas_digitos[-2:]}"


# ---------------------------------------------------------------------------
# Evento bruto
# ---------------------------------------------------------------------------


def _bloquear_entidade(db: Session, chave_entidade: str | None) -> None:
    """Serializa requisições concorrentes da mesma entidade no PostgreSQL.

    SQLite não suporta ``SELECT ... FOR UPDATE``; nele a serialização fica a
    cargo da transação de escrita (e o volume de produção é PostgreSQL).
    """
    if not chave_entidade or db.bind is None or db.bind.dialect.name != "postgresql":
        return

    prefixo, _, identificador = chave_entidade.partition(":")
    if not identificador:
        return
    if prefixo == "consulta":
        db.execute(
            select(Consulta)
            .where(Consulta.id_solicitacao == identificador)
            .with_for_update()
        ).scalar_one_or_none()
    elif prefixo == "proposta":
        db.execute(
            select(Proposta)
            .where(Proposta.id_proposta == identificador)
            .with_for_update()
        ).scalar_one_or_none()


def _falhou_no_processamento(evento: EventoWebhook) -> bool:
    return bool(evento.erro and evento.erro.startswith(PREFIXO_ERRO_PROCESSAMENTO))


def _ultimo_evento(db: Session, chave_entidade: str | None, payload_hash: str) -> EventoWebhook | None:
    if chave_entidade is not None:
        return db.scalar(
            select(EventoWebhook)
            .where(EventoWebhook.chave_entidade == chave_entidade)
            .order_by(EventoWebhook.id.desc())
            .limit(1)
        )
    return db.scalar(
        select(EventoWebhook)
        .where(EventoWebhook.payload_hash == payload_hash)
        .order_by(EventoWebhook.id.desc())
        .limit(1)
    )


def registrar_evento(
    db: Session,
    *,
    tipo: str | None,
    rota: str,
    ip_origem: str | None,
    headers: dict[str, str],
    payload: Any,
    payload_hash: str,
    chave_entidade: str | None = None,
    processado: bool = False,
    erro: str | None = None,
    status_conhecido: bool = False,
) -> ResultadoRegistro:
    """Grava o evento bruto em transação própria.

    A deduplicação é por entidade: só é duplicado quando o **último** evento da
    mesma consulta/proposta tem o mesmo hash. Sem entidade (JSON malformado,
    ``tipo`` desconhecido, falha de validação), deduplica pelo hash global.
    """
    _bloquear_entidade(db, chave_entidade)

    existente = _ultimo_evento(db, chave_entidade, payload_hash)
    if existente is not None:
        if chave_entidade is None:
            return ResultadoRegistro(existente, duplicado=True)
        if existente.payload_hash == payload_hash:
            if existente.processado:
                return ResultadoRegistro(existente, duplicado=True)
            if _falhou_no_processamento(existente):
                return ResultadoRegistro(
                    existente, duplicado=False, reprocessar=True
                )
            return ResultadoRegistro(existente, duplicado=True)
        # O último evento da entidade é diferente: pode ser uma ida e volta
        # (ex.: PENDING_BANK_ANALYSIS -> PENDING_PAYMENT -> PENDING_BANK_ANALYSIS).
        # Grava como evento novo mesmo que o hash já exista no passado.

    evento = EventoWebhook(
        tipo=tipo,
        rota=rota,
        ip_origem=ip_origem,
        headers=headers,
        payload=payload,
        payload_hash=payload_hash,
        chave_entidade=chave_entidade,
        processado=processado,
        erro=erro,
        status_conhecido=status_conhecido,
    )
    db.add(evento)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        existente = _ultimo_evento(db, chave_entidade, payload_hash)
        if existente is not None:
            return ResultadoRegistro(existente, duplicado=True)
        raise

    db.refresh(evento)
    return ResultadoRegistro(evento, duplicado=False)


def marcar_evento_falha(db: Session, evento_id: int, erro: str) -> None:
    """Marca o evento como não processado, em transação separada."""
    try:
        db.rollback()
        evento = db.get(EventoWebhook, evento_id)
        if evento is None:
            return
        evento.processado = False
        evento.erro = erro[:4000]
        db.commit()
    except Exception as exc:  # noqa: BLE001 - falha ao logar não pode derrubar a resposta
        db.rollback()
        logger.error(
            "não foi possível marcar falha do evento_id=%s: %s",
            evento_id,
            type(exc).__name__,
        )


# ---------------------------------------------------------------------------
# Consultas
# ---------------------------------------------------------------------------


def _processar_consulta_uma_vez(
    db: Session, evento: EventoWebhook, payload: ConsultaPayload
) -> bool:
    status = payload.status
    descricao = CONSULTA_STATUS_DESCRICOES.get(status)
    conhecido = status in CONSULTA_STATUS_DESCRICOES
    final = status in CONSULTA_STATUS_FINAIS
    agora = agora_utc()

    consulta = db.get(Consulta, payload.id_solicitacao)
    if consulta is None:
        consulta = Consulta(
            id_solicitacao=payload.id_solicitacao,
            id_proposta=payload.id_proposta,
            cpf=payload.cpf,
            user_id=payload.user_id,
            corban_id=payload.corban_id,
            status=status,
            status_descricao=descricao,
            status_final=final,
            criado_em=agora,
            atualizado_em=agora,
            ultimo_evento_id=evento.id,
        )
        db.add(consulta)
    else:
        consulta.cpf = payload.cpf
        consulta.user_id = payload.user_id
        consulta.corban_id = payload.corban_id
        consulta.status = status
        consulta.status_descricao = descricao
        consulta.status_final = final
        consulta.atualizado_em = agora
        consulta.ultimo_evento_id = evento.id
        # id_proposta é opcional no payload: não apaga o vínculo anterior.
        if payload.id_proposta is not None:
            consulta.id_proposta = payload.id_proposta

    # Se já existe uma proposta com esse id e sem CPF, completa o CPF.
    if payload.id_proposta:
        proposta = db.get(Proposta, payload.id_proposta)
        if proposta is not None and not proposta.cpf:
            proposta.cpf = payload.cpf

    evento.processado = True
    evento.status_conhecido = conhecido
    evento.erro = None
    db.flush()

    if not conhecido:
        logger.warning(
            "status de consulta desconhecido id_solicitacao=%s status=%s evento_id=%s",
            payload.id_solicitacao,
            status,
            evento.id,
        )
    return conhecido


def processar_consulta(
    db: Session, evento: EventoWebhook, payload: ConsultaPayload
) -> bool:
    """Upsert da consulta com retry para corrida de PK (SQLite e PostgreSQL)."""
    evento_id = evento.id
    for tentativa in range(2):
        try:
            conhecido = _processar_consulta_uma_vez(db, evento, payload)
            db.commit()
            return conhecido
        except IntegrityError:
            db.rollback()
            if tentativa == 0:
                evento = db.get(EventoWebhook, evento_id) or evento
                continue
            raise
    raise RuntimeError("não foi possível processar a consulta")


# ---------------------------------------------------------------------------
# Propostas
# ---------------------------------------------------------------------------


def _cpf_da_consulta(db: Session, id_proposta: str) -> str | None:
    return db.scalar(
        select(Consulta.cpf)
        .where(Consulta.id_proposta == id_proposta, Consulta.cpf.is_not(None))
        .order_by(Consulta.atualizado_em.desc())
        .limit(1)
    )


def _processar_proposta_uma_vez(
    db: Session, evento: EventoWebhook, payload: PropostaPayload
) -> bool:
    status = payload.status_da_proposta
    tipo_notificacao = payload.tipo_notificacao
    chave = (status, tipo_notificacao)
    descricao = PROPOSTA_EVENTOS_DESCRICOES.get(chave)
    conhecido = chave in PROPOSTA_EVENTOS_DESCRICOES
    final = status in PROPOSTA_STATUS_FINAIS
    agora = agora_utc()

    proposta = db.get(Proposta, payload.id_proposta)
    status_anterior_final = bool(proposta is not None and proposta.status_final)
    status_anterior = proposta.status_da_proposta if proposta is not None else None

    if proposta is None:
        cpf = _cpf_da_consulta(db, payload.id_proposta)
        proposta = Proposta(
            id_proposta=payload.id_proposta,
            status_da_proposta=status,
            tipo_notificacao=tipo_notificacao,
            informacoes=payload.informacoes,
            status_descricao=descricao,
            status_final=final,
            cpf=cpf,
            criado_em=agora,
            atualizado_em=agora,
            ultimo_evento_id=evento.id,
        )
        db.add(proposta)
    else:
        if not proposta.cpf:
            proposta.cpf = _cpf_da_consulta(db, payload.id_proposta)
        proposta.status_da_proposta = status
        proposta.tipo_notificacao = tipo_notificacao
        proposta.informacoes = payload.informacoes
        proposta.status_descricao = descricao
        proposta.status_final = final
        proposta.atualizado_em = agora
        proposta.ultimo_evento_id = evento.id

    db.add(
        PropostaHistorico(
            id_proposta=payload.id_proposta,
            status_da_proposta=status,
            tipo_notificacao=tipo_notificacao,
            informacoes=payload.informacoes,
            recebido_em=agora,
            evento_id=evento.id,
        )
    )

    evento.processado = True
    evento.status_conhecido = conhecido
    evento.erro = None
    db.flush()

    if not conhecido:
        logger.warning(
            "status de proposta desconhecido id_proposta=%s "
            "status_da_proposta=%s tipo_notificacao=%s evento_id=%s",
            payload.id_proposta,
            status,
            tipo_notificacao,
            evento.id,
        )

    # Eventos não são estritamente sequenciais; não rejeitamos a transição,
    # apenas avisamos quando chega algo depois de um status final.
    if status_anterior_final:
        logger.warning(
            "evento após status final id_proposta=%s status_anterior=%s "
            "novo_status=%s tipo_notificacao=%s evento_id=%s",
            payload.id_proposta,
            status_anterior,
            status,
            tipo_notificacao,
            evento.id,
        )
    return conhecido


def processar_proposta(
    db: Session, evento: EventoWebhook, payload: PropostaPayload
) -> bool:
    """Upsert da proposta + histórico com retry para corrida de PK."""
    evento_id = evento.id
    for tentativa in range(2):
        try:
            conhecido = _processar_proposta_uma_vez(db, evento, payload)
            db.commit()
            return conhecido
        except IntegrityError:
            db.rollback()
            if tentativa == 0:
                evento = db.get(EventoWebhook, evento_id) or evento
                continue
            raise
    raise RuntimeError("não foi possível processar a proposta")

