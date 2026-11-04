"""Testes de configuração de produção: docs, limite de corpo e tolerância."""

from __future__ import annotations

import json
from typing import Any

import httpx
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, select
from sqlalchemy.orm import Session, sessionmaker

from granatech_webhook.config import Settings
from granatech_webhook.main import create_app
from granatech_webhook.models import EventoWebhook, Proposta


@pytest.mark.anyio
@pytest.mark.parametrize("rota", ["/docs", "/redoc", "/openapi.json"])
async def test_documentacao_oculta_em_producao(rota: str) -> None:
    app = create_app(Settings(app_env="production"))
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(
        transport=transport, base_url="http://test"
    ) as client:
        resposta = await client.get(rota)

    assert resposta.status_code == 404


@pytest.mark.anyio
@pytest.mark.parametrize("ambiente", ["development", "test", "staging"])
async def test_documentacao_disponivel_fora_de_producao(ambiente: str) -> None:
    app = create_app(Settings(app_env=ambiente))
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(
        transport=transport, base_url="http://test"
    ) as client:
        docs = await client.get("/docs")
        openapi = await client.get("/openapi.json")

    assert docs.status_code == 200
    assert openapi.status_code == 200


def test_corpo_acima_do_limite_retorna_413_sem_gravar_evento(
    client: TestClient,
    load_payload: Any,
    session_factory: sessionmaker[Session],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("MAX_BODY_BYTES", "100")
    payload = load_payload("consulta_SUCCESS.json")
    corpo = json.dumps(payload).encode()
    assert len(corpo) > 100

    resposta = client.post(
        "/webhooks/granatech",
        content=corpo,
        headers={"Content-Type": "application/json"},
    )

    assert resposta.status_code == 413
    with session_factory() as db:
        assert db.scalar(select(func.count()).select_from(EventoWebhook)) == 0


def test_corpo_dentro_do_limite_e_aceito(
    client: TestClient,
    load_payload: Any,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    payload = load_payload("consulta_SUCCESS.json")
    monkeypatch.setenv("MAX_BODY_BYTES", "100000")

    resposta = client.post("/webhooks/granatech", json=payload)

    assert resposta.status_code == 200, resposta.text


@pytest.mark.parametrize("modo", ["null", "ausente"])
def test_informacoes_aceita_null_ou_ausente(
    client: TestClient,
    load_payload: Any,
    session_factory: sessionmaker[Session],
    modo: str,
) -> None:
    payload = load_payload(
        "proposta_PENDING_CONFIRMATION__AGUARDANDO_CONFIRMACAO.json"
    )
    if modo == "null":
        payload["informacoes"] = None
    else:
        del payload["informacoes"]

    resposta = client.post("/webhooks/granatech", json=payload)

    assert resposta.status_code == 200, resposta.text
    assert resposta.json()["duplicado"] is False
    with session_factory() as db:
        proposta = db.get(Proposta, payload["id_proposta"])
        assert proposta is not None
        assert proposta.informacoes == ""
