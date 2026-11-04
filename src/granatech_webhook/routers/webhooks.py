"""Endpoints de recebimento dos webhooks da Granatech."""

from __future__ import annotations

import json
import logging
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import JSONResponse
from pydantic import ValidationError
from sqlalchemy.orm import Session

from ..config import Settings, get_settings
from ..database import get_db
from ..schemas import (
    ConsultaPayload,
    PropostaPayload,
    resumir_erros_validacao,
)
from ..security import (
    headers_para_evento,
    ip_permitido,
    obter_ip_cliente,
    token_valido,
)
from ..services import (
    ResultadoRegistro,
    chave_entidade_consulta,
    chave_entidade_proposta,
    hash_corpo_bytes,
    hash_payload,
    marcar_evento_falha,
    processar_consulta,
    processar_proposta,
    registrar_evento,
)

logger = logging.getLogger(__name__)

router = APIRouter(tags=["webhooks"])


async def corpo_bruto(
    request: Request, settings: Settings = Depends(get_settings)
) -> bytes:
    """Lê o corpo no event loop (assíncrono), com limite de tamanho.

    As rotas são síncronas para que o acesso síncrono ao SQLAlchemy rode no
    threadpool do FastAPI e não bloqueie o event loop.
    """
    limite = max(0, settings.max_body_bytes)
    corpo = bytearray()
    async for parte in request.stream():
        corpo.extend(parte)
        if len(corpo) > limite:
            raise HTTPException(status_code=413, detail="corpo muito grande")
    return bytes(corpo)


def _normalizar_tipo(valor: object) -> str | None:
    """Aceita ``CONSULTA``, ``consulta``, ``Proposta`` etc. (case-insensitive)."""
    if not isinstance(valor, str):
        return None
    tipo = valor.strip().lower()
    if tipo in {"consulta", "consultas"}:
        return "consulta"
    if tipo in {"proposta", "propostas"}:
        return "proposta"
    return None


def _tipo_para_log(valor: object) -> str | None:
    if not isinstance(valor, str):
        return None
    return valor.strip().lower()[:255] or None


def _resposta_ok(evento_id: int, duplicado: bool) -> dict[str, Any]:
    return {"recebido": True, "evento_id": evento_id, "duplicado": duplicado}


def _resposta_erro(
    status_code: int,
    detalhe: str,
    evento_id: int | None = None,
    extra: dict[str, Any] | None = None,
) -> JSONResponse:
    conteudo: dict[str, Any] = {"detail": detalhe}
    if evento_id is not None:
        conteudo["evento_id"] = evento_id
    if extra:
        conteudo.update(extra)
    return JSONResponse(status_code=status_code, content=conteudo)


def _registrar_ou_erro(
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
) -> ResultadoRegistro | JSONResponse:
    """Grava o evento bruto; em falha de banco devolve uma resposta 500."""
    try:
        return registrar_evento(
            db,
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
    except Exception as exc:  # noqa: BLE001 - nunca expor detalhe do banco
        logger.error(
            "falha ao gravar evento bruto rota=%s ip=%s erro=%s",
            rota,
            ip_origem,
            type(exc).__name__,
        )
        return _resposta_erro(500, "erro ao registrar o evento")


def _log_evento(
    tipo: str | None,
    identificador: str | None,
    status: str | None,
    tipo_notificacao: str | None,
    evento_id: int,
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


def _receber(
    request: Request,
    body: bytes,
    db: Session,
    *,
    tipo_forcado: str | None,
) -> Any:
    settings: Settings = get_settings()
    rota = request.url.path
    ip_origem = obter_ip_cliente(request, settings)

    if not token_valido(request, settings):
        logger.warning("token inválido ou ausente rota=%s ip=%s", rota, ip_origem)
        return _resposta_erro(401, "token inválido ou ausente")

    if not ip_permitido(ip_origem, settings):
        logger.warning("IP não permitido rota=%s ip=%s", rota, ip_origem)
        return _resposta_erro(403, "IP não permitido")

    headers = headers_para_evento(request, settings)

    # ------------------------------------------------------------------
    # JSON malformado: guarda o corpo cru e responde 400 (sem processar).
    # ------------------------------------------------------------------
    try:
        dados = json.loads(body)
    except (ValueError, UnicodeDecodeError):
        texto_cru = body.decode("utf-8", errors="replace")
        registrado = _registrar_ou_erro(
            db,
            tipo=None,
            rota=rota,
            ip_origem=ip_origem,
            headers=headers,
            payload={"_raw": texto_cru},
            payload_hash=hash_corpo_bytes(body),
            erro="JSON malformado",
        )
        if isinstance(registrado, JSONResponse):
            return registrado
        evento = registrado.evento
        logger.warning(
            "JSON malformado rota=%s ip=%s tamanho=%s evento_id=%s duplicado=%s",
            rota,
            ip_origem,
            len(body),
            evento.id,
            "sim" if registrado.duplicado else "não",
        )
        return _resposta_erro(400, "JSON malformado", evento.id)

    # ------------------------------------------------------------------
    # Corpo precisa ser um objeto JSON.
    # ------------------------------------------------------------------
    if not isinstance(dados, dict):
        erro = "payload deve ser um objeto JSON"
        registrado = _registrar_ou_erro(
            db,
            tipo=None,
            rota=rota,
            ip_origem=ip_origem,
            headers=headers,
            payload=dados,
            payload_hash=hash_payload(dados),
            erro=erro,
        )
        if isinstance(registrado, JSONResponse):
            return registrado
        evento = registrado.evento
        logger.warning(
            "payload inválido rota=%s ip=%s erro=%s evento_id=%s",
            rota,
            ip_origem,
            erro,
            evento.id,
        )
        return _resposta_erro(422, "payload inválido", evento.id, {"erro": erro})

    # ------------------------------------------------------------------
    # Identificação do tipo (endpoint único) ou tipo forçado pelos aliases.
    # ------------------------------------------------------------------
    tipo_bruto = dados.get("tipo")
    if tipo_forcado is not None:
        tipo = tipo_forcado
        dados_para_validar = {**dados, "tipo": tipo}
    else:
        tipo = _normalizar_tipo(tipo_bruto)
        dados_para_validar = dados

    if tipo is None:
        if tipo_bruto is None:
            erro = "campo obrigatório ausente: tipo"
        else:
            erro = f"tipo desconhecido: {str(tipo_bruto)[:100]}"
        tipo_evento = _tipo_para_log(tipo_bruto)

        registrado = _registrar_ou_erro(
            db,
            tipo=tipo_evento,
            rota=rota,
            ip_origem=ip_origem,
            headers=headers,
            payload=dados,
            payload_hash=hash_payload(dados),
            erro=erro,
        )
        if isinstance(registrado, JSONResponse):
            return registrado
        evento = registrado.evento
        logger.warning(
            "tipo desconhecido rota=%s ip=%s tipo=%s evento_id=%s",
            rota,
            ip_origem,
            tipo_evento or "-",
            evento.id,
        )
        return _resposta_erro(422, "payload inválido", evento.id, {"erro": erro})

    # ------------------------------------------------------------------
    # Validação Pydantic (status/tipo_notificacao são strings livres).
    # ------------------------------------------------------------------
    modelo = ConsultaPayload if tipo == "consulta" else PropostaPayload
    try:
        payload = modelo.model_validate(dados_para_validar)
    except ValidationError as exc:
        resumo = resumir_erros_validacao(exc)
        registrado = _registrar_ou_erro(
            db,
            tipo=tipo,
            rota=rota,
            ip_origem=ip_origem,
            headers=headers,
            payload=dados,
            payload_hash=hash_payload(dados),
            erro=resumo,
        )
        if isinstance(registrado, JSONResponse):
            return registrado
        evento = registrado.evento
        logger.warning(
            "payload inválido tipo=%s rota=%s ip=%s erro=%s evento_id=%s duplicado=%s",
            tipo,
            rota,
            ip_origem,
            resumo,
            evento.id,
            "sim" if registrado.duplicado else "não",
        )
        return _resposta_erro(
            422, "payload inválido", evento.id, {"erro": resumo}
        )

    # ------------------------------------------------------------------
    # Grava o evento bruto (transação própria) antes de processar.
    # ------------------------------------------------------------------
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

    registrado = _registrar_ou_erro(
        db,
        tipo=tipo,
        rota=rota,
        ip_origem=ip_origem,
        headers=headers,
        payload=dados,
        payload_hash=hash_payload(dados),
        chave_entidade=chave_entidade,
    )
    if isinstance(registrado, JSONResponse):
        return registrado
    evento = registrado.evento

    if registrado.duplicado:
        _log_evento(
            tipo, identificador, status, tipo_notificacao, evento.id, duplicado=True
        )
        return _resposta_ok(evento.id, duplicado=True)

    try:
        if isinstance(payload, ConsultaPayload):
            processar_consulta(db, evento, payload)
        else:
            processar_proposta(db, evento, payload)
    except Exception as exc:  # noqa: BLE001 - detalhe só no log interno
        logger.error(
            "falha ao processar evento tipo=%s id=%s evento_id=%s erro=%s",
            tipo,
            identificador,
            evento.id,
            type(exc).__name__,
        )
        marcar_evento_falha(
            db, evento.id, f"erro ao processar: {type(exc).__name__}"
        )
        return _resposta_erro(500, "erro ao processar o evento", evento.id)

    _log_evento(
        tipo, identificador, status, tipo_notificacao, evento.id, duplicado=False
    )
    return _resposta_ok(evento.id, duplicado=False)


@router.post("/webhooks/granatech")
def webhook_granatech(
    request: Request,
    body: bytes = Depends(corpo_bruto),
    db: Session = Depends(get_db),
) -> Any:
    """Endpoint único: identifica consulta/proposta pelo campo ``tipo``."""
    return _receber(request, body, db, tipo_forcado=None)


@router.post("/webhooks/granatech/consultas")
def webhook_consultas(
    request: Request,
    body: bytes = Depends(corpo_bruto),
    db: Session = Depends(get_db),
) -> Any:
    """Alias que força o tipo consulta."""
    return _receber(request, body, db, tipo_forcado="consulta")


@router.post("/webhooks/granatech/propostas")
def webhook_propostas(
    request: Request,
    body: bytes = Depends(corpo_bruto),
    db: Session = Depends(get_db),
) -> Any:
    """Alias que força o tipo proposta."""
    return _receber(request, body, db, tipo_forcado="proposta")
