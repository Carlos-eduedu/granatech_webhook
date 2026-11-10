"""Regras de negócio do webhook: idempotência, upsert e histórico."""

import json
import logging
from dataclasses import dataclass
from typing import Any

from pydantic import ValidationError
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from ....db.base import agora_utc
from ....db.dao import consulta_dao, evento_dao, proposta_dao
from ....db.models import (
    Consulta,
    EventoWebhook,
    Proposta,
    PropostaHistorico,
)
from . import constants
from .exceptions import (
    FalhaProcessamento,
    FalhaRegistro,
    PayloadInvalido,
    PayloadMalformado,
)
from .schemas import ConsultaPayload, PropostaPayload
from .utils import (
    chave_entidade_consulta,
    chave_entidade_proposta,
    hash_corpo_bytes,
    hash_payload,
    normalizar_tipo,
    resumir_erros_validacao,
    tipo_para_log,
)

logger = logging.getLogger(__name__)

# Alias de compatibilidade para testes/consumidores do módulo.
PREFIXO_ERRO_PROCESSAMENTO = constants.PREFIXO_ERRO_PROCESSAMENTO


@dataclass(frozen=True)
class ResultadoWebhook:
    evento_id: int
    duplicado: bool


@dataclass(frozen=True)
class ResultadoRegistro:
    """Resultado do registro do evento bruto."""

    evento: EventoWebhook
    duplicado: bool
    reprocessar: bool = False


# ---------------------------------------------------------------------------
# Evento bruto
# ---------------------------------------------------------------------------


def _bloquear_entidade(db: Session, chave_entidade: str | None) -> None:
    if not chave_entidade:
        return
    prefixo, _, identificador = chave_entidade.partition(":")
    if not identificador:
        return
    if prefixo == "consulta":
        consulta_dao.bloquear(db, identificador)
    elif prefixo == "proposta":
        proposta_dao.bloquear(db, identificador)


def _falhou_no_processamento(evento: EventoWebhook) -> bool:
    return bool(evento.erro and evento.erro.startswith(constants.PREFIXO_ERRO_PROCESSAMENTO))


def _buscar_existente(
    db: Session, chave_entidade: str | None, payload_hash: str
) -> EventoWebhook | None:
    if chave_entidade is not None:
        return evento_dao.buscar_ultimo_por_entidade(db, chave_entidade)
    return evento_dao.buscar_ultimo_por_hash(db, payload_hash)


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
    erro: str | None = None,
) -> ResultadoRegistro:
    """Grava o evento bruto e aplica a regra de idempotência por entidade."""
    _bloquear_entidade(db, chave_entidade)

    existente = _buscar_existente(db, chave_entidade, payload_hash)
    if existente is not None:
        if chave_entidade is None:
            return ResultadoRegistro(existente, duplicado=True)
        if existente.payload_hash == payload_hash:
            if existente.processado:
                return ResultadoRegistro(existente, duplicado=True)
            if _falhou_no_processamento(existente):
                return ResultadoRegistro(existente, duplicado=False, reprocessar=True)
            return ResultadoRegistro(existente, duplicado=True)
        # O último evento da entidade é diferente: ida e volta. Grava novo.

    evento = evento_dao.criar(
        db,
        tipo=tipo,
        rota=rota,
        ip_origem=ip_origem,
        headers=headers,
        payload=payload,
        payload_hash=payload_hash,
        chave_entidade=chave_entidade,
        erro=erro,
    )
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        existente = _buscar_existente(db, chave_entidade, payload_hash)
        if existente is not None:
            return ResultadoRegistro(existente, duplicado=True)
        raise

    db.refresh(evento)
    return ResultadoRegistro(evento, duplicado=False)


def _registrar_bruto(
    db: Session,
    *,
    tipo: str | None,
    rota: str,
    ip_origem: str | None,
    headers: dict[str, str],
    payload: Any,
    payload_hash: str,
    chave_entidade: str | None = None,
    erro: str | None = None,
) -> ResultadoRegistro:
    """Chama o registro; qualquer falha de banco vira ``FalhaRegistro``."""
    try:
        resultado = registrar_evento(
            db,
            tipo=tipo,
            rota=rota,
            ip_origem=ip_origem,
            headers=headers,
            payload=payload,
            payload_hash=payload_hash,
            chave_entidade=chave_entidade,
            erro=erro,
        )
    except Exception as exc:
        logger.exception("falha ao gravar evento bruto rota=%s ip=%s", rota, ip_origem)
        raise FalhaRegistro from exc

    logger.info(
        "evento bruto gravado evento_id=%s rota=%s duplicado=%s",
        resultado.evento.id,
        rota,
        "sim" if resultado.duplicado else "não",
    )
    return resultado


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
    except Exception:
        db.rollback()
        logger.exception("não foi possível marcar falha do evento_id=%s", evento_id)


# ---------------------------------------------------------------------------
# Consultas
# ---------------------------------------------------------------------------


def _processar_consulta_uma_vez(
    db: Session, evento: EventoWebhook, payload: ConsultaPayload
) -> bool:
    status = payload.status
    descricao = constants.CONSULTA_STATUS_DESCRICOES.get(status)
    conhecido = status in constants.CONSULTA_STATUS_DESCRICOES
    final = status in constants.CONSULTA_STATUS_FINAIS
    agora = agora_utc()

    consulta = consulta_dao.buscar(db, payload.id_solicitacao)
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
        consulta_dao.adicionar(db, consulta)
    else:
        consulta.cpf = payload.cpf
        # Campos opcionais: um evento mínimo não apaga o que já se sabe.
        if payload.user_id is not None:
            consulta.user_id = payload.user_id
        if payload.corban_id is not None:
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
        proposta = proposta_dao.buscar(db, payload.id_proposta)
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


def processar_consulta(db: Session, evento: EventoWebhook, payload: ConsultaPayload) -> bool:
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
                # Sem exc_info: a mensagem do driver pode conter o CPF.
                logger.warning(
                    "concorrência ao gravar consulta; tentando novamente evento_id=%s",
                    evento_id,
                )
                evento = db.get(EventoWebhook, evento_id) or evento
                continue
            raise
    raise RuntimeError("não foi possível processar a consulta")


# ---------------------------------------------------------------------------
# Propostas
# ---------------------------------------------------------------------------


def _processar_proposta_uma_vez(
    db: Session, evento: EventoWebhook, payload: PropostaPayload
) -> bool:
    status = payload.status_da_proposta
    tipo_notificacao = payload.tipo_notificacao
    chave = (status, tipo_notificacao)
    descricao = constants.PROPOSTA_EVENTOS_DESCRICOES.get(chave)
    conhecido = chave in constants.PROPOSTA_EVENTOS_DESCRICOES
    final = status in constants.PROPOSTA_STATUS_FINAIS
    agora = agora_utc()

    proposta = proposta_dao.buscar(db, payload.id_proposta)
    status_anterior_final = bool(proposta is not None and proposta.status_final)
    status_anterior = proposta.status_da_proposta if proposta is not None else None

    if proposta is None:
        cpf = consulta_dao.buscar_cpf_por_proposta(db, payload.id_proposta)
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
        proposta_dao.adicionar(db, proposta)
    else:
        if not proposta.cpf:
            proposta.cpf = consulta_dao.buscar_cpf_por_proposta(db, payload.id_proposta)
        proposta.status_da_proposta = status
        proposta.tipo_notificacao = tipo_notificacao
        proposta.informacoes = payload.informacoes
        proposta.status_descricao = descricao
        proposta.status_final = final
        proposta.atualizado_em = agora
        proposta.ultimo_evento_id = evento.id

    proposta_dao.adicionar_historico(
        db,
        PropostaHistorico(
            id_proposta=payload.id_proposta,
            status_da_proposta=status,
            tipo_notificacao=tipo_notificacao,
            informacoes=payload.informacoes,
            recebido_em=agora,
            evento_id=evento.id,
        ),
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


def processar_proposta(db: Session, evento: EventoWebhook, payload: PropostaPayload) -> bool:
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
                # Sem exc_info: a mensagem do driver pode conter o CPF.
                logger.warning(
                    "concorrência ao gravar proposta; tentando novamente evento_id=%s",
                    evento_id,
                )
                evento = db.get(EventoWebhook, evento_id) or evento
                continue
            raise
    raise RuntimeError("não foi possível processar a proposta")


# ---------------------------------------------------------------------------
# Orquestração do webhook
# ---------------------------------------------------------------------------


def _log_evento(
    tipo: str | None,
    identificador: str | None,
    status: str | None,
    tipo_notificacao: str | None,
    evento_id: int,
    *,
    duplicado: bool,
) -> None:
    logger.info(
        "evento tipo=%s id=%s status=%s tipo_notificacao=%s evento_id=%s duplicado=%s",
        tipo or "-",
        identificador or "-",
        status or "-",
        tipo_notificacao or "-",
        evento_id,
        "sim" if duplicado else "não",
    )


def processar_webhook(
    db: Session,
    *,
    corpo: bytes,
    rota: str,
    ip_origem: str | None,
    headers: dict[str, str],
    tipo_forcado: str | None,
) -> ResultadoWebhook:
    """Registra o corpo bruto e, se for o caso, processa consulta/proposta."""
    try:
        dados = json.loads(corpo)
    except ValueError, UnicodeDecodeError:
        texto_cru = corpo.decode("utf-8", errors="replace")
        registrado = _registrar_bruto(
            db,
            tipo=None,
            rota=rota,
            ip_origem=ip_origem,
            headers=headers,
            payload={"_raw": texto_cru},
            payload_hash=hash_corpo_bytes(corpo),
            erro="JSON malformado",
        )
        logger.warning(
            "JSON malformado rota=%s ip=%s tamanho=%s evento_id=%s duplicado=%s",
            rota,
            ip_origem,
            len(corpo),
            registrado.evento.id,
            "sim" if registrado.duplicado else "não",
        )
        raise PayloadMalformado(evento_id=registrado.evento.id) from None

    if not isinstance(dados, dict):
        erro = "payload deve ser um objeto JSON"
        registrado = _registrar_bruto(
            db,
            tipo=None,
            rota=rota,
            ip_origem=ip_origem,
            headers=headers,
            payload=dados,
            payload_hash=hash_payload(dados),
            erro=erro,
        )
        logger.warning(
            "payload inválido rota=%s ip=%s erro=%s evento_id=%s",
            rota,
            ip_origem,
            erro,
            registrado.evento.id,
        )
        raise PayloadInvalido(evento_id=registrado.evento.id, erro=erro)

    tipo_bruto = dados.get("tipo")
    tipo: str | None
    if tipo_forcado is not None:
        tipo = tipo_forcado
        dados_para_validar = {**dados, "tipo": tipo}
    else:
        tipo = normalizar_tipo(tipo_bruto)
        dados_para_validar = dados

    if tipo is None:
        if tipo_bruto is None:
            erro = "campo obrigatório ausente: tipo"
        else:
            erro = f"tipo desconhecido: {str(tipo_bruto)[:100]}"
        tipo_evento = tipo_para_log(tipo_bruto)

        registrado = _registrar_bruto(
            db,
            tipo=tipo_evento,
            rota=rota,
            ip_origem=ip_origem,
            headers=headers,
            payload=dados,
            payload_hash=hash_payload(dados),
            erro=erro,
        )
        logger.warning(
            "tipo desconhecido rota=%s ip=%s tipo=%s evento_id=%s",
            rota,
            ip_origem,
            tipo_evento or "-",
            registrado.evento.id,
        )
        raise PayloadInvalido(evento_id=registrado.evento.id, erro=erro)

    modelo = ConsultaPayload if tipo == "consulta" else PropostaPayload
    try:
        payload = modelo.model_validate(dados_para_validar)
    except ValidationError as exc:
        resumo = resumir_erros_validacao(exc)
        registrado = _registrar_bruto(
            db,
            tipo=tipo,
            rota=rota,
            ip_origem=ip_origem,
            headers=headers,
            payload=dados,
            payload_hash=hash_payload(dados),
            erro=resumo,
        )
        logger.warning(
            "payload inválido tipo=%s rota=%s ip=%s erro=%s evento_id=%s duplicado=%s",
            tipo,
            rota,
            ip_origem,
            resumo,
            registrado.evento.id,
            "sim" if registrado.duplicado else "não",
        )
        raise PayloadInvalido(evento_id=registrado.evento.id, erro=resumo) from None

    if isinstance(payload, ConsultaPayload):
        identificador = payload.id_solicitacao
        status = payload.status
        tipo_notificacao = None
        chave_entidade = chave_entidade_consulta(identificador)
    else:
        identificador = payload.id_proposta
        status = payload.status_da_proposta
        tipo_notificacao = payload.tipo_notificacao
        chave_entidade = chave_entidade_proposta(identificador)

    logger.info(
        "payload validado tipo=%s id=%s status=%s",
        tipo,
        identificador,
        status,
    )
    registrado = _registrar_bruto(
        db,
        tipo=tipo,
        rota=rota,
        ip_origem=ip_origem,
        headers=headers,
        payload=dados,
        payload_hash=hash_payload(dados),
        chave_entidade=chave_entidade,
    )
    evento = registrado.evento

    if registrado.duplicado:
        _log_evento(
            tipo,
            identificador,
            status,
            tipo_notificacao,
            evento.id,
            duplicado=True,
        )
        return ResultadoWebhook(evento_id=evento.id, duplicado=True)

    try:
        if isinstance(payload, ConsultaPayload):
            processar_consulta(db, evento, payload)
        else:
            processar_proposta(db, evento, payload)
    except Exception as exc:
        logger.exception(
            "falha ao processar evento tipo=%s id=%s evento_id=%s",
            tipo,
            identificador,
            evento.id,
        )
        marcar_evento_falha(
            db,
            evento.id,
            f"{constants.PREFIXO_ERRO_PROCESSAMENTO} {type(exc).__name__}",
        )
        raise FalhaProcessamento(evento_id=evento.id) from exc

    _log_evento(
        tipo,
        identificador,
        status,
        tipo_notificacao,
        evento.id,
        duplicado=False,
    )
    return ResultadoWebhook(evento_id=evento.id, duplicado=False)
