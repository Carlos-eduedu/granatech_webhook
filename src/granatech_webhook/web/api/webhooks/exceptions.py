"""Exceções de domínio do webhook (tratadas em ``web.application``)."""


class WebhookError(Exception):
    """Base de erros que viram respostas JSON do contrato."""

    status_code: int = 500
    detail: str = "erro interno"

    def __init__(
        self,
        *,
        evento_id: int | None = None,
        erro: str | None = None,
    ) -> None:
        super().__init__(self.detail)
        self.evento_id = evento_id
        self.erro = erro


class PayloadMalformado(WebhookError):  # noqa: N818
    status_code = 400
    detail = "JSON malformado"


class PayloadInvalido(WebhookError):  # noqa: N818
    status_code = 422
    detail = "payload inválido"


class FalhaRegistro(WebhookError):  # noqa: N818
    status_code = 500
    detail = "erro ao registrar o evento"


class FalhaProcessamento(WebhookError):  # noqa: N818
    status_code = 500
    detail = "erro ao processar o evento"
