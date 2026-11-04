"""Validação do token compartilhado, do IP de origem e redação de headers."""

from __future__ import annotations

import hmac

from fastapi import Request

from .config import Settings

_HEADERS_SENSIVEIS = frozenset(
    {"authorization", "cookie", "set-cookie", "x-api-key", "proxy-authorization"}
)


def obter_ip_cliente(request: Request, settings: Settings) -> str | None:
    """IP real do cliente (mesma função usada na allowlist e em ``ip_origem``).

    Atrás do Traefik do Dokploy (``TRUST_PROXY=true``), o primeiro IP de
    ``X-Forwarded-For`` é o cliente. Sem proxy, usa ``request.client.host``.
    """
    if settings.trust_proxy:
        encaminhado = request.headers.get("x-forwarded-for")
        if encaminhado:
            primeiro = encaminhado.split(",", 1)[0].strip()
            if primeiro:
                return primeiro
    if request.client is None:
        return None
    return request.client.host


def token_valido(request: Request, settings: Settings) -> bool:
    """Confere o token no header configurado ou em ``?token=``."""
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
            # Tipos inesperados nunca devem autenticar.
            continue
    return False


def ip_permitido(ip: str | None, settings: Settings) -> bool:
    """Aplica ``ALLOWED_IPS`` (vazio = libera todos; ``*`` também libera)."""
    permitidos = {item.strip() for item in settings.allowed_ips if item.strip()}
    if not permitidos or "*" in permitidos:
        return True
    return bool(ip) and ip in permitidos


def headers_para_evento(request: Request, settings: Settings) -> dict[str, str]:
    """Copia os headers para o log bruto, mascarando token e credenciais."""
    header_token = settings.webhook_token_header.strip().lower()
    headers: dict[str, str] = {}
    for nome, valor in request.headers.items():
        chave = nome.lower()
        if chave == header_token or chave in _HEADERS_SENSIVEIS:
            headers[nome] = "***"
        else:
            headers[nome] = valor
    return headers
