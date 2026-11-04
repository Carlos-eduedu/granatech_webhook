"""Utilitários do webhook: hash, CPF, normalizações e headers."""

import hashlib
import json
import logging
import re
import uuid
from typing import Any

from fastapi import Request
from pydantic import ValidationError

from ....settings import Settings

logger = logging.getLogger(__name__)

_NAO_DIGITOS = re.compile(r"\D")
_HEADERS_SENSIVEIS = frozenset(
    {"authorization", "cookie", "set-cookie", "x-api-key", "proxy-authorization"}
)


def hash_payload(payload: Any) -> str:
    """SHA-256 do JSON canonizado (``sort_keys=True``)."""
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


def normalizar_uuid_tolerante(valor: str, campo: str) -> str:
    """Valida o UUID de forma tolerante; se inválido, mantém a string e avisa."""
    try:
        uuid.UUID(valor)
    except ValueError, AttributeError, TypeError:
        logger.warning("campo %s não é um UUID válido; mantendo como string", campo)
    return valor


def normalizar_cpf(valor: str) -> str:
    """Remove pontuação e preserva zeros à esquerda (completa com zfill)."""
    digitos = _NAO_DIGITOS.sub("", valor)
    if not digitos:
        raise ValueError("CPF vazio")
    if len(digitos) > 11:
        raise ValueError("CPF com mais de 11 dígitos")
    return digitos.zfill(11)


def normalizar_tipo(valor: object) -> str | None:
    """Aceita ``CONSULTA``, ``consulta``, ``Proposta`` etc. (case-insensitive)."""
    if not isinstance(valor, str):
        return None
    tipo = valor.strip().lower()
    if tipo in {"consulta", "consultas"}:
        return "consulta"
    if tipo in {"proposta", "propostas"}:
        return "proposta"
    return None


def tipo_para_log(valor: object) -> str | None:
    if not isinstance(valor, str):
        return None
    return valor.strip().lower()[:255] or None


def resumir_erros_validacao(exc: ValidationError) -> str:
    """Resume os erros sem incluir os valores de entrada (evita vazar CPF)."""
    partes: list[str] = []
    for erro in exc.errors():
        local = ".".join(str(parte) for parte in erro.get("loc", ()))
        mensagem = str(erro.get("msg", "valor inválido"))
        partes.append(f"{local}: {mensagem}" if local else mensagem)
    resumo = "; ".join(partes) or "payload inválido"
    return resumo[:2000]


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
