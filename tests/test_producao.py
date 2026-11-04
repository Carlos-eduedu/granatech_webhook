"""Testes de configuração de produção: docs, limite de corpo e tolerância."""

import json
from typing import Any

import httpx
import pytest
from sqlalchemy import func, select
from sqlalchemy.orm import Session, sessionmaker

from granatech_webhook.db.models import EventoWebhook, Proposta
from granatech_webhook.settings import Settings
from granatech_webhook.web.application import create_app


@pytest.mark.anyio
@pytest.mark.parametrize("rota", ["/docs", "/redoc", "/openapi.json"])
async def test_documentacao_oculta_em_producao(rota: str) -> None:
    app = create_app(Settings(app_env="production"))
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        resposta = await client.get(rota)

    assert resposta.status_code == 404


@pytest.mark.anyio
@pytest.mark.parametrize("ambiente", ["development", "test", "staging"])
async def test_documentacao_disponivel_fora_de_producao(ambiente: str) -> None:
    app = create_app(Settings(app_env=ambiente))
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        docs = await client.get("/docs")
        openapi = await client.get("/openapi.json")

    assert docs.status_code == 200
    assert openapi.status_code == 200


@pytest.mark.anyio
async def test_corpo_acima_do_limite_retorna_413_sem_gravar_evento(
    client: httpx.AsyncClient,
    load_payload: Any,
    session_factory: sessionmaker[Session],
    configurar_settings: Any,
) -> None:
    configurar_settings(max_body_bytes=100)
    payload = load_payload("consulta_SUCCESS.json")
    corpo = json.dumps(payload).encode()
    assert len(corpo) > 100

    resposta = await client.post(
        "/webhooks/granatech",
        content=corpo,
        headers={"Content-Type": "application/json"},
    )

    assert resposta.status_code == 413
    with session_factory() as db:
        assert db.scalar(select(func.count()).select_from(EventoWebhook)) == 0


@pytest.mark.anyio
async def test_corpo_dentro_do_limite_e_aceito(
    client: httpx.AsyncClient,
    load_payload: Any,
) -> None:
    payload = load_payload("consulta_SUCCESS.json")

    resposta = await client.post("/webhooks/granatech", json=payload)

    assert resposta.status_code == 200, resposta.text


@pytest.mark.anyio
@pytest.mark.parametrize("modo", ["null", "ausente"])
async def test_informacoes_aceita_null_ou_ausente(
    client: httpx.AsyncClient,
    load_payload: Any,
    session_factory: sessionmaker[Session],
    modo: str,
) -> None:
    payload = load_payload("proposta_PENDING_CONFIRMATION__AGUARDANDO_CONFIRMACAO.json")
    if modo == "null":
        payload["informacoes"] = None
    else:
        del payload["informacoes"]

    resposta = await client.post("/webhooks/granatech", json=payload)

    assert resposta.status_code == 200, resposta.text
    assert resposta.json()["duplicado"] is False
    with session_factory() as db:
        proposta = db.get(Proposta, payload["id_proposta"])
        assert proposta is not None
        assert proposta.informacoes == ""
