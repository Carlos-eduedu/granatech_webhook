"""Schemas Pydantic v2 dos payloads e das respostas do webhook."""

from pydantic import BaseModel, ConfigDict, field_validator

from .utils import normalizar_cpf, normalizar_uuid_tolerante


class PayloadGranatech(BaseModel):
    """Base tolerante: campos novos não quebram o recebimento."""

    model_config = ConfigDict(extra="allow", str_strip_whitespace=True)


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
    informacoes: str = ""

    @field_validator("informacoes", mode="before")
    @classmethod
    def _informacoes_tolerante(cls, valor: object) -> object:
        if valor is None:
            return ""
        return valor

    @field_validator("id_proposta")
    @classmethod
    def _validar_id_proposta(cls, valor: str) -> str:
        return normalizar_uuid_tolerante(valor, "id_proposta")

    @field_validator("tipo")
    @classmethod
    def _normalizar_tipo(cls, valor: str) -> str:
        return valor.lower()


class RespostaWebhook(BaseModel):
    """Corpo de sucesso, mantido igual ao contrato antigo."""

    recebido: bool = True
    evento_id: int
    duplicado: bool


class RespostaErro(BaseModel):
    """Formato dos erros de negócio."""

    detail: str
    evento_id: int | None = None
    erro: str | None = None
