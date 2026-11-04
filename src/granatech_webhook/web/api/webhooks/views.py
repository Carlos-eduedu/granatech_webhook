"""Rotas finas do webhook: dependências + service."""

from typing import Annotated, Any

from fastapi import APIRouter, Depends, Request
from sqlalchemy.orm import Session

from ....db.dependencies import get_db_session
from ....settings import Settings, get_settings
from .dependencies import corpo_bruto, verificar_ip, verificar_token
from .schemas import RespostaErro, RespostaWebhook
from .service import processar_webhook
from .utils import headers_para_evento

router = APIRouter(prefix="/webhooks/granatech", tags=["webhooks"])

_RESPOSTAS: dict[int | str, dict[str, Any]] = {
    400: {"model": RespostaErro, "description": "JSON malformado"},
    401: {"model": RespostaErro, "description": "Token inválido ou ausente"},
    403: {"model": RespostaErro, "description": "IP não permitido"},
    413: {"model": RespostaErro, "description": "Corpo acima de MAX_BODY_BYTES"},
    422: {"model": RespostaErro, "description": "Payload inválido"},
    500: {
        "model": RespostaErro,
        "description": "Falha ao registrar ou processar o evento",
    },
}


def _receber(
    request: Request,
    body: bytes,
    ip: str | None,
    db: Session,
    settings: Settings,
    *,
    tipo_forcado: str | None,
) -> RespostaWebhook:
    headers = headers_para_evento(request, settings)
    resultado = processar_webhook(
        db,
        corpo=body,
        rota=request.url.path,
        ip_origem=ip,
        headers=headers,
        tipo_forcado=tipo_forcado,
    )
    return RespostaWebhook(
        recebido=True,
        evento_id=resultado.evento_id,
        duplicado=resultado.duplicado,
    )


@router.post(
    "",
    response_model=RespostaWebhook,
    status_code=200,
    summary="Recebe um webhook da Granatech",
    description=(
        "Endpoint único: identifica consulta ou proposta pelo campo `tipo` "
        "(case-insensitive). O corpo bruto é sempre gravado antes do "
        "processamento."
    ),
    responses=_RESPOSTAS,
)
def webhook_granatech(
    request: Request,
    _token: Annotated[None, Depends(verificar_token)],
    ip: Annotated[str | None, Depends(verificar_ip)],
    body: Annotated[bytes, Depends(corpo_bruto)],
    db: Annotated[Session, Depends(get_db_session)],
    settings: Annotated[Settings, Depends(get_settings)],
) -> RespostaWebhook:
    return _receber(request, body, ip, db, settings, tipo_forcado=None)


@router.post(
    "/consultas",
    response_model=RespostaWebhook,
    status_code=200,
    summary="Recebe um webhook de consulta",
    description="Alias que força o tipo `consulta`, independente do campo `tipo`.",
    responses=_RESPOSTAS,
)
def webhook_consultas(
    request: Request,
    _token: Annotated[None, Depends(verificar_token)],
    ip: Annotated[str | None, Depends(verificar_ip)],
    body: Annotated[bytes, Depends(corpo_bruto)],
    db: Annotated[Session, Depends(get_db_session)],
    settings: Annotated[Settings, Depends(get_settings)],
) -> RespostaWebhook:
    return _receber(request, body, ip, db, settings, tipo_forcado="consulta")


@router.post(
    "/propostas",
    response_model=RespostaWebhook,
    status_code=200,
    summary="Recebe um webhook de proposta",
    description="Alias que força o tipo `proposta`, independente do campo `tipo`.",
    responses=_RESPOSTAS,
)
def webhook_propostas(
    request: Request,
    _token: Annotated[None, Depends(verificar_token)],
    ip: Annotated[str | None, Depends(verificar_ip)],
    body: Annotated[bytes, Depends(corpo_bruto)],
    db: Annotated[Session, Depends(get_db_session)],
    settings: Annotated[Settings, Depends(get_settings)],
) -> RespostaWebhook:
    return _receber(request, body, ip, db, settings, tipo_forcado="proposta")
