"""Testes do log por requisição: início, fim, request_id e stack trace."""

import io
import logging
from typing import Any

import httpx
import pytest

from granatech_webhook.log import (
    _FORMATO,
    FiltroContexto,
    FormatterComMascara,
    configurar_logging,
    contexto_request,
)
from granatech_webhook.settings import Settings

_APP = "granatech_webhook.web.application"
_SERVICE = "granatech_webhook.web.api.webhooks.service"


def _consulta(load_payload: Any) -> dict[str, Any]:
    payload: dict[str, Any] = load_payload("consulta_AWAITING_CLIENT_AUTHORIZATION.json")
    return payload


def _registros(caplog: pytest.LogCaptureFixture, nome: str) -> list[logging.LogRecord]:
    return [registro for registro in caplog.records if registro.name == nome]


def _mensagens(registros: list[logging.LogRecord]) -> str:
    return "\n".join(registro.getMessage() for registro in registros)


@pytest.fixture
def caplog_contexto(caplog: pytest.LogCaptureFixture) -> Any:
    """Instala o filtro de request_id no handler do pytest (sem lifespan)."""
    filtro = FiltroContexto()
    caplog.handler.addFilter(filtro)
    try:
        yield caplog
    finally:
        caplog.handler.removeFilter(filtro)


@pytest.mark.anyio
async def test_webhook_200_loga_inicio_fim_e_request_id(
    client: httpx.AsyncClient,
    load_payload: Any,
    caplog_contexto: pytest.LogCaptureFixture,
) -> None:
    caplog_contexto.set_level(logging.INFO)

    resposta = await client.post("/webhooks/granatech", json=_consulta(load_payload))

    assert resposta.status_code == 200

    da_app = _registros(caplog_contexto, _APP)
    inicio = [registro for registro in da_app if "requisição recebida" in registro.getMessage()]
    fim = [registro for registro in da_app if "resposta status=" in registro.getMessage()]
    assert len(inicio) == 1
    assert len(fim) == 1
    assert "metodo=POST" in inicio[0].getMessage()
    assert "rota=/webhooks/granatech" in inicio[0].getMessage()
    assert "status=200" in fim[0].getMessage()
    assert "duracao_ms=" in fim[0].getMessage()

    do_service = _registros(caplog_contexto, _SERVICE)
    mensagens = _mensagens(do_service)
    assert "payload validado" in mensagens
    assert "evento bruto gravado" in mensagens

    # O mesmo request_id nas linhas da app e do service (correlação).
    ids = {getattr(registro, "request_id", None) for registro in da_app + do_service}
    assert len(ids) == 1
    assert "-" not in ids


@pytest.mark.anyio
async def test_401_tambem_aparece_no_log(
    client: httpx.AsyncClient,
    load_payload: Any,
    configurar_settings: Any,
    caplog_contexto: pytest.LogCaptureFixture,
) -> None:
    configurar_settings(webhook_token="segredo-do-webhook")
    caplog_contexto.set_level(logging.INFO)

    resposta = await client.post("/webhooks/granatech", json=_consulta(load_payload))

    assert resposta.status_code == 401
    fim = [
        registro
        for registro in _registros(caplog_contexto, _APP)
        if "resposta status=" in registro.getMessage()
    ]
    assert len(fim) == 1
    assert "status=401" in fim[0].getMessage()
    assert "segredo-do-webhook" not in caplog_contexto.text


@pytest.mark.anyio
async def test_query_string_com_token_nao_vai_para_o_log(
    client: httpx.AsyncClient,
    load_payload: Any,
    configurar_settings: Any,
    caplog_contexto: pytest.LogCaptureFixture,
) -> None:
    configurar_settings(webhook_token="token-na-url")
    caplog_contexto.set_level(logging.INFO)

    resposta = await client.post(
        "/webhooks/granatech?token=token-na-url", json=_consulta(load_payload)
    )

    assert resposta.status_code == 200
    assert "token-na-url" not in caplog_contexto.text


@pytest.mark.anyio
async def test_health_nao_polui_o_log(
    client: httpx.AsyncClient,
    caplog_contexto: pytest.LogCaptureFixture,
) -> None:
    caplog_contexto.set_level(logging.INFO)

    resposta = await client.get("/health")

    assert resposta.status_code == 200
    assert _registros(caplog_contexto, _APP) == []


@pytest.mark.anyio
async def test_falha_no_processamento_loga_stack_trace(
    client: httpx.AsyncClient,
    load_payload: Any,
    caplog: pytest.LogCaptureFixture,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    caplog.set_level(logging.INFO)

    def explodir(*_args: Any, **_kwargs: Any) -> bool:
        raise RuntimeError("falha simulada no processamento")

    monkeypatch.setattr(f"{_SERVICE}.processar_consulta", explodir)

    resposta = await client.post("/webhooks/granatech", json=_consulta(load_payload))

    assert resposta.status_code == 500
    erros = [
        registro for registro in _registros(caplog, _SERVICE) if registro.levelno == logging.ERROR
    ]
    assert erros
    assert "falha ao processar evento" in erros[0].getMessage()
    assert erros[0].exc_info is not None
    assert "RuntimeError" in caplog.text


@pytest.mark.anyio
async def test_excecao_nao_tratada_loga_stack_trace(
    client: httpx.AsyncClient,
    load_payload: Any,
    caplog: pytest.LogCaptureFixture,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    caplog.set_level(logging.INFO)

    def explodir(*_args: Any, **_kwargs: Any) -> Any:
        raise RuntimeError("falha inesperada fora do service")

    monkeypatch.setattr("granatech_webhook.web.api.webhooks.views.headers_para_evento", explodir)

    with pytest.raises(RuntimeError, match="falha inesperada"):
        await client.post("/webhooks/granatech", json=_consulta(load_payload))

    erros = [registro for registro in _registros(caplog, _APP) if registro.levelno == logging.ERROR]
    assert erros
    assert "falha não tratada" in erros[0].getMessage()
    assert erros[0].exc_info is not None
    assert "RuntimeError" in caplog.text


@pytest.mark.anyio
async def test_falha_no_registro_loga_stack_trace(
    client: httpx.AsyncClient,
    load_payload: Any,
    caplog: pytest.LogCaptureFixture,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    caplog.set_level(logging.INFO)

    def explodir(*_args: Any, **_kwargs: Any) -> Any:
        raise RuntimeError("falha simulada de banco")

    monkeypatch.setattr(f"{_SERVICE}.registrar_evento", explodir)

    resposta = await client.post("/webhooks/granatech", json=_consulta(load_payload))

    assert resposta.status_code == 500
    erros = [
        registro for registro in _registros(caplog, _SERVICE) if registro.levelno == logging.ERROR
    ]
    assert erros
    assert "falha ao gravar evento bruto" in erros[0].getMessage()
    assert erros[0].exc_info is not None
    assert "RuntimeError" in caplog.text


def test_formatter_mascara_cpf_no_stack_trace() -> None:
    logger = logging.getLogger("granatech_webhook.teste_mascara")
    logger.setLevel(logging.INFO)
    logger.propagate = False
    fluxo = io.StringIO()
    handler = logging.StreamHandler(fluxo)
    handler.setFormatter(FormatterComMascara(_FORMATO))
    logger.addHandler(handler)
    try:
        try:
            raise ValueError("cpf 33179781041 já cadastrado")
        except ValueError:
            logger.exception("falha simulada")
    finally:
        logger.removeHandler(handler)

    saida = fluxo.getvalue()
    assert "Traceback" in saida
    assert "33179781041" not in saida
    assert "331.***.***-41" in saida
    assert "request_id=-" in saida


def test_filtro_contexto_usa_id_do_bloco_e_volta_ao_padrao() -> None:
    filtro = FiltroContexto()

    def _registro() -> logging.LogRecord:
        return logging.LogRecord("teste", logging.INFO, __file__, 1, "msg", (), None)

    fora = _registro()
    filtro.filter(fora)
    assert getattr(fora, "request_id", None) == "-"

    with contexto_request("abc123") as identificador:
        dentro = _registro()
        filtro.filter(dentro)
        assert getattr(dentro, "request_id", None) == "abc123"
        assert identificador == "abc123"

    depois = _registro()
    filtro.filter(depois)
    assert getattr(depois, "request_id", None) == "-"


def test_log_level_alcanca_loggers_do_uvicorn() -> None:
    logger_uvicorn = logging.getLogger("uvicorn.error")
    nivel_uvicorn = logger_uvicorn.level
    nivel_root = logging.getLogger().level
    try:
        configurar_logging(Settings(log_level="WARNING"))

        assert logger_uvicorn.level == logging.WARNING
        assert logging.getLogger().level == logging.WARNING
    finally:
        logger_uvicorn.setLevel(nivel_uvicorn)
        logging.getLogger().setLevel(nivel_root)
