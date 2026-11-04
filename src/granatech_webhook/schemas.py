"""Schemas Pydantic v2 dos payloads da Granatech."""

from __future__ import annotations

import logging
import re
import uuid

from pydantic import BaseModel, ConfigDict, ValidationError, field_validator

logger = logging.getLogger(__name__)

_NAO_DIGITOS = re.compile(r"\D")


class PayloadGranatech(BaseModel):
    """Base tolerante: campos novos não quebram o recebimento."""

    model_config = ConfigDict(extra="allow", str_strip_whitespace=True)


def normalizar_uuid_tolerante(valor: str, campo: str) -> str:
    """Valida o UUID de forma tolerante; se inválido, mantém a string e avisa."""
    try:
        uuid.UUID(valor)
    except (ValueError, AttributeError, TypeError):
        logger.warning(
            "campo %s não é um UUID válido; mantendo como string", campo
        )
    return valor


def normalizar_cpf(valor: str) -> str:
    """Remove pontuação e preserva zeros à esquerda (completa com zfill)."""
    digitos = _NAO_DIGITOS.sub("", valor)
    if not digitos:
        raise ValueError("CPF vazio")
    if len(digitos) > 11:
        raise ValueError("CPF com mais de 11 dígitos")
    return digitos.zfill(11)


class ConsultaPayload(PayloadGranatech):
    """Payload de consulta (status da solicitação de saldo/margem)."""

    id_solicitacao: str
    id_proposta: str | None = None
    cpf: str
    status: str
    user_id: str
    corban_id: int
    tipo: str

    @field_validator("id_solicitacao")
    @classmethod
    def _validar_id_solicitacao(cls, valor: str) -> str:
        return normalizar_uuid_tolerante(valor, "id_solicitacao")

    @field_validator("id_proposta", mode="before")
    @classmethod
    def _id_proposta_vazio_e_nulo(cls, valor: object) -> object:
        if isinstance(valor, str) and not valor.strip():
            return None
        return valor

    @field_validator("id_proposta")
    @classmethod
    def _validar_id_proposta(cls, valor: str | None) -> str | None:
        if valor is None:
            return None
        return normalizar_uuid_tolerante(valor, "id_proposta")

    @field_validator("cpf")
    @classmethod
    def _normalizar_cpf(cls, valor: str) -> str:
        return normalizar_cpf(valor)

    @field_validator("tipo")
    @classmethod
    def _normalizar_tipo(cls, valor: str) -> str:
        return valor.lower()


class PropostaPayload(PayloadGranatech):
    """Payload de proposta (ciclo de vida da proposta)."""

    tipo: str
    status_da_proposta: str
    tipo_notificacao: str
    id_proposta: str
    informacoes: str

    @field_validator("id_proposta")
    @classmethod
    def _validar_id_proposta(cls, valor: str) -> str:
        return normalizar_uuid_tolerante(valor, "id_proposta")

    @field_validator("tipo")
    @classmethod
    def _normalizar_tipo(cls, valor: str) -> str:
        return valor.lower()


def resumir_erros_validacao(exc: ValidationError) -> str:
    """Resume os erros sem incluir os valores de entrada (evita vazar CPF)."""
    partes: list[str] = []
    for erro in exc.errors():
        local = ".".join(str(parte) for parte in erro.get("loc", ()))
        mensagem = str(erro.get("msg", "valor inválido"))
        partes.append(f"{local}: {mensagem}" if local else mensagem)
    resumo = "; ".join(partes) or "payload inválido"
    return resumo[:2000]
