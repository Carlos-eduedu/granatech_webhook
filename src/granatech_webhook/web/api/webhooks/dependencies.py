"""Dependências HTTP: corpo, token e IP (encadeadas)."""

import hmac
from typing import Annotated

from fastapi import Depends, HTTPException, Request

from ....settings import Settings, get_settings


async def corpo_bruto(
    request: Request,
    settings: Annotated[Settings, Depends(get_settings)],
) -> bytes:
    """Lê o corpo no event loop (assíncrono), com limite de tamanho."""
    limite = max(0, settings.max_body_bytes)
    corpo = bytearray()
    async for parte in request.stream():
        corpo.extend(parte)
        if len(corpo) > limite:
            raise HTTPException(status_code=413, detail="corpo muito grande")
    return bytes(corpo)


def ip_cliente(
    request: Request,
    settings: Annotated[Settings, Depends(get_settings)],
) -> str | None:
    """IP real do cliente (mesma função usada na allowlist e em ``ip_origem``)."""
    if settings.trust_proxy:
        encaminhado = request.headers.get("x-forwarded-for")
        if encaminhado:
            primeiro = encaminhado.split(",", 1)[0].strip()
            if primeiro:
                return primeiro
    if request.client is None:
        return None
    return request.client.host


def _ip_permitido(ip: str | None, settings: Settings) -> bool:
    permitidos = {item.strip() for item in settings.allowed_ips if item.strip()}
    if not permitidos or "*" in permitidos:
        return True
    return bool(ip) and ip in permitidos


def verificar_ip(
    ip: Annotated[str | None, Depends(ip_cliente)],
    settings: Annotated[Settings, Depends(get_settings)],
) -> str | None:
    if not _ip_permitido(ip, settings):
        raise HTTPException(status_code=403, detail="IP não permitido")
    return ip


def _token_valido(request: Request, settings: Settings) -> bool:
    esperado = settings.webhook_token
    if not esperado:
        return True

    candidatos = [
        request.headers.get(settings.webhook_token_header),
        request.query_params.get("token"),
    ]
    for candidato in candidatos:
        if candidato is None:
            continue
        try:
            if hmac.compare_digest(candidato, esperado):
                return True
        except TypeError:
            continue
    return False


def verificar_token(
    request: Request,
    settings: Annotated[Settings, Depends(get_settings)],
) -> None:
    if not _token_valido(request, settings):
        raise HTTPException(status_code=401, detail="token inválido ou ausente")
