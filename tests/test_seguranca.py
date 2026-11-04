"""Testes de token, IP/proxy e LGPD nos logs."""

from __future__ import annotations

import json
import logging
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, select
from sqlalchemy.orm import Session, sessionmaker

from granatech_webhook.config import get_settings
from granatech_webhook.models import EventoWebhook


def _consulta(load_payload: Any) -> dict[str, Any]:
    return load_payload("consulta_AWAITING_CLIENT_AUTHORIZATION.json")


def test_sem_token_configurado_aceita_tudo(
    client: TestClient, load_payload: Any
) -> None:
    resposta = client.post("/webhooks/granatech", json=_consulta(load_payload))

    assert resposta.status_code == 200


def test_token_configurado(
    client: TestClient,
    load_payload: Any,
    session_factory: sessionmaker[Session],
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    token = "segredo-super-secreto"
    monkeypatch.setenv("WEBHOOK_TOKEN", token)
    get_settings.cache_clear()
    caplog.set_level(logging.INFO)

    payload = _consulta(load_payload)
    sem_token = client.post("/webhooks/granatech", json=payload)
    token_errado = client.post(
        "/webhooks/granatech",
        json=payload,
        headers={"X-Webhook-Token": "errado"},
    )

    assert sem_token.status_code == 401
    assert token_errado.status_code == 401
    with session_factory() as db:
        assert (
            db.scalar(select(func.count()).select_from(EventoWebhook)) == 0
        )

    com_token = client.post(
        "/webhooks/granatech",
        json=payload,
        headers={"X-Webhook-Token": token},
    )
    assert com_token.status_code == 200
    assert com_token.json()["duplicado"] is False

    outra = load_payload("consulta_PROCESSING.json")
    por_query = client.post(
        f"/webhooks/granatech?token={token}", json=outra
    )
    assert por_query.status_code == 200
    assert por_query.json()["duplicado"] is False

    with session_factory() as db:
        eventos = db.scalars(
            select(EventoWebhook).order_by(EventoWebhook.id)
        ).all()
        assert len(eventos) == 2
        for evento in eventos:
            assert token not in json.dumps(evento.headers)
            assert evento.rota == "/webhooks/granatech"

    assert token not in caplog.text


def test_token_em_header_customizado(
    client: TestClient,
    load_payload: Any,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("WEBHOOK_TOKEN", "abc123")
    monkeypatch.setenv("WEBHOOK_TOKEN_HEADER", "X-Meu-Token")
    get_settings.cache_clear()

    sem = client.post("/webhooks/granatech", json=_consulta(load_payload))
    com_header_antigo = client.post(
        "/webhooks/granatech",
        json=_consulta(load_payload),
        headers={"X-Webhook-Token": "abc123"},
    )
    com_header_novo = client.post(
        "/webhooks/granatech",
        json=_consulta(load_payload),
        headers={"X-Meu-Token": "abc123"},
    )

    assert sem.status_code == 401
    assert com_header_antigo.status_code == 401
    assert com_header_novo.status_code == 200


def test_allowlist_de_ip(
    make_client: Any,
    load_payload: Any,
    session_factory: sessionmaker[Session],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("ALLOWED_IPS", "10.0.0.1")
    get_settings.cache_clear()

    permitido = make_client(client_addr=("10.0.0.1", 5000))
    negado = make_client(client_addr=("10.0.0.2", 5000))
    payload = _consulta(load_payload)

    resposta_negada = negado.post("/webhooks/granatech", json=payload)
    assert resposta_negada.status_code == 403
    with session_factory() as db:
        assert (
            db.scalar(select(func.count()).select_from(EventoWebhook)) == 0
        )

    resposta_permitida = permitido.post("/webhooks/granatech", json=payload)
    assert resposta_permitida.status_code == 200

    with session_factory() as db:
        evento = db.scalars(select(EventoWebhook)).one()
        assert evento.ip_origem == "10.0.0.1"


def test_trust_proxy_usa_primeiro_ip_do_x_forwarded_for(
    make_client: Any,
    load_payload: Any,
    session_factory: sessionmaker[Session],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("TRUST_PROXY", "true")
    monkeypatch.setenv("ALLOWED_IPS", "203.0.113.7")
    get_settings.cache_clear()

    cliente = make_client(client_addr=("10.0.0.9", 5000))
    payload = _consulta(load_payload)

    negado = cliente.post(
        "/webhooks/granatech",
        json=payload,
        headers={"X-Forwarded-For": "198.51.100.9, 10.0.0.9"},
    )
    assert negado.status_code == 403

    aceito = cliente.post(
        "/webhooks/granatech",
        json=payload,
        headers={"X-Forwarded-For": "203.0.113.7, 10.0.0.9"},
    )
    assert aceito.status_code == 200

    with session_factory() as db:
        evento = db.scalars(select(EventoWebhook)).one()
        assert evento.ip_origem == "203.0.113.7"


def test_sem_trust_proxy_ignora_x_forwarded_for(
    make_client: Any,
    load_payload: Any,
    session_factory: sessionmaker[Session],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("TRUST_PROXY", "false")
    monkeypatch.setenv("ALLOWED_IPS", "10.0.0.9")
    get_settings.cache_clear()

    cliente = make_client(client_addr=("10.0.0.9", 5000))
    payload = _consulta(load_payload)

    resposta = cliente.post(
        "/webhooks/granatech",
        json=payload,
        headers={"X-Forwarded-For": "203.0.113.7, 10.0.0.9"},
    )

    assert resposta.status_code == 200
    with session_factory() as db:
        evento = db.scalars(select(EventoWebhook)).one()
        assert evento.ip_origem == "10.0.0.9"


def test_cpf_completo_nao_aparece_nos_logs(
    client: TestClient,
    load_payload: Any,
    caplog: pytest.LogCaptureFixture,
) -> None:
    caplog.set_level(logging.DEBUG)
    payload = _consulta(load_payload)
    cpf = payload["cpf"]

    resposta = client.post("/webhooks/granatech", json=payload)

    assert resposta.status_code == 200
    assert cpf not in caplog.text
    # Também não logamos o CPF mascarado; o importante é nunca o completo.
    assert "33179781041" not in caplog.text


def test_cpf_invalido_nao_vaza_nos_logs(
    client: TestClient,
    load_payload: Any,
    caplog: pytest.LogCaptureFixture,
) -> None:
    caplog.set_level(logging.DEBUG)
    payload = _consulta(load_payload)
    cpf_invalido = "331797810411"
    payload["cpf"] = cpf_invalido

    resposta = client.post("/webhooks/granatech", json=payload)

    assert resposta.status_code == 422
    assert cpf_invalido not in caplog.text
