"""Testes dos webhooks de consulta."""

from typing import Any

import httpx
import pytest
from sqlalchemy import func, select
from sqlalchemy.orm import Session, sessionmaker

from granatech_webhook.db.models import Consulta, EventoWebhook
from granatech_webhook.web.api.webhooks.constants import (
    CONSULTA_STATUS_DESCRICOES,
    CONSULTA_STATUS_FINAIS,
)

CONSULTAS = [
    ("AWAITING_CLIENT_AUTHORIZATION", False),
    ("PROCESSING", False),
    ("SUCCESS", True),
    ("PENDING", False),
    ("NO_MARGIN", True),
    ("USED", True),
    ("UNEXPECTED_ERROR", True),
]


@pytest.mark.anyio
@pytest.mark.parametrize(("status", "final"), CONSULTAS)
async def test_consulta_por_status(
    client: httpx.AsyncClient,
    load_payload: Any,
    session_factory: sessionmaker[Session],
    status: str,
    final: bool,
) -> None:
    payload = load_payload(f"consulta_{status}.json")

    resposta = await client.post("/webhooks/granatech", json=payload)

    assert resposta.status_code == 200, resposta.text
    corpo = resposta.json()
    assert corpo["recebido"] is True
    assert corpo["duplicado"] is False
    assert isinstance(corpo["evento_id"], int)

    with session_factory() as db:
        consulta = db.get(Consulta, payload["id_solicitacao"])
        assert consulta is not None
        assert consulta.status == status
        assert consulta.status_descricao == CONSULTA_STATUS_DESCRICOES[status]
        assert consulta.status_final is final
        assert consulta.status_final is (status in CONSULTA_STATUS_FINAIS)
        assert consulta.cpf == payload["cpf"]
        assert consulta.user_id == payload["user_id"]
        assert isinstance(consulta.user_id, str)
        assert consulta.corban_id == payload["corban_id"]
        assert consulta.id_proposta == payload["id_proposta"]
        assert consulta.ultimo_evento_id == corpo["evento_id"]

        evento = db.get(EventoWebhook, corpo["evento_id"])
        assert evento is not None
        assert evento.processado is True
        assert evento.status_conhecido is True
        assert evento.tipo == "consulta"
        assert evento.payload == payload
        assert evento.erro is None


@pytest.mark.anyio
async def test_cpf_com_zero_a_esquerda_preservado(
    client: httpx.AsyncClient,
    load_payload: Any,
    session_factory: sessionmaker[Session],
) -> None:
    payload = load_payload("consulta_PENDING.json")
    assert payload["cpf"].startswith("0")

    resposta = await client.post("/webhooks/granatech", json=payload)

    assert resposta.status_code == 200
    with session_factory() as db:
        consulta = db.get(Consulta, payload["id_solicitacao"])
        assert consulta is not None
        assert consulta.cpf == "01234567890"


@pytest.mark.anyio
async def test_user_id_permanece_string(
    client: httpx.AsyncClient,
    load_payload: Any,
    session_factory: sessionmaker[Session],
) -> None:
    payload = load_payload("consulta_AWAITING_CLIENT_AUTHORIZATION.json")
    payload["user_id"] = "12500542068.38"

    resposta = await client.post("/webhooks/granatech", json=payload)

    assert resposta.status_code == 200
    with session_factory() as db:
        consulta = db.get(Consulta, payload["id_solicitacao"])
        assert consulta is not None
        assert consulta.user_id == "12500542068.38"
        assert isinstance(consulta.user_id, str)


@pytest.mark.anyio
async def test_status_desconhecido_e_aceito(
    client: httpx.AsyncClient,
    load_payload: Any,
    session_factory: sessionmaker[Session],
    caplog: pytest.LogCaptureFixture,
) -> None:
    payload = load_payload("consulta_AWAITING_CLIENT_AUTHORIZATION.json")
    payload["status"] = "STATUS_NOVO_QUALQUER"

    resposta = await client.post("/webhooks/granatech", json=payload)

    assert resposta.status_code == 200, resposta.text
    assert resposta.json()["duplicado"] is False
    with session_factory() as db:
        consulta = db.get(Consulta, payload["id_solicitacao"])
        assert consulta is not None
        assert consulta.status == "STATUS_NOVO_QUALQUER"
        assert consulta.status_descricao is None
        assert consulta.status_final is False

        evento = db.get(EventoWebhook, resposta.json()["evento_id"])
        assert evento is not None
        assert evento.processado is True
        assert evento.status_conhecido is False
    assert "desconhecido" in caplog.text


@pytest.mark.anyio
async def test_payload_sem_campo_obrigatorio_grava_evento(
    client: httpx.AsyncClient,
    load_payload: Any,
    session_factory: sessionmaker[Session],
) -> None:
    payload = load_payload("consulta_AWAITING_CLIENT_AUTHORIZATION.json")
    del payload["cpf"]

    resposta = await client.post("/webhooks/granatech", json=payload)

    assert resposta.status_code == 422
    with session_factory() as db:
        evento = db.scalars(select(EventoWebhook).order_by(EventoWebhook.id.desc())).first()
        assert evento is not None
        assert evento.processado is False
        assert evento.status_conhecido is False
        assert evento.erro is not None
        assert "cpf" in evento.erro
        assert evento.payload == payload
        assert db.get(Consulta, payload["id_solicitacao"]) is None
        total_eventos = db.scalar(select(func.count()).select_from(EventoWebhook))
        assert total_eventos == 1


@pytest.mark.anyio
async def test_tipo_desconhecido_grava_evento(
    client: httpx.AsyncClient,
    load_payload: Any,
    session_factory: sessionmaker[Session],
) -> None:
    payload = load_payload("consulta_AWAITING_CLIENT_AUTHORIZATION.json")
    payload["tipo"] = "OUTRO_EVENTO"

    resposta = await client.post("/webhooks/granatech", json=payload)

    assert resposta.status_code == 422
    with session_factory() as db:
        evento = db.scalars(select(EventoWebhook).order_by(EventoWebhook.id.desc())).first()
        assert evento is not None
        assert evento.tipo == "outro_evento"
        assert evento.processado is False
        assert "tipo desconhecido" in (evento.erro or "")
        assert evento.payload == payload


@pytest.mark.anyio
async def test_tipo_ausente_grava_evento(
    client: httpx.AsyncClient,
    load_payload: Any,
    session_factory: sessionmaker[Session],
) -> None:
    payload = load_payload("consulta_AWAITING_CLIENT_AUTHORIZATION.json")
    del payload["tipo"]

    resposta = await client.post("/webhooks/granatech", json=payload)

    assert resposta.status_code == 422
    with session_factory() as db:
        evento = db.scalars(select(EventoWebhook).order_by(EventoWebhook.id.desc())).first()
        assert evento is not None
        assert evento.tipo is None
        assert evento.processado is False
        assert "tipo" in (evento.erro or "")


@pytest.mark.anyio
async def test_json_malformado_responde_400(
    client: httpx.AsyncClient, session_factory: sessionmaker[Session]
) -> None:
    corpo_invalido = b'{"id_solicitacao": "x", '

    resposta = await client.post(
        "/webhooks/granatech",
        content=corpo_invalido,
        headers={"Content-Type": "application/json"},
    )

    assert resposta.status_code == 400
    with session_factory() as db:
        evento = db.scalars(select(EventoWebhook).order_by(EventoWebhook.id.desc())).first()
        assert evento is not None
        assert evento.processado is False
        assert evento.erro == "JSON malformado"
        assert evento.payload["_raw"] == corpo_invalido.decode()


@pytest.mark.anyio
async def test_payload_duplicado_nao_reprocessa(
    client: httpx.AsyncClient,
    load_payload: Any,
    session_factory: sessionmaker[Session],
) -> None:
    payload = load_payload("consulta_SUCCESS.json")

    primeira = await client.post("/webhooks/granatech", json=payload)
    segunda = await client.post("/webhooks/granatech", json=payload)

    assert primeira.status_code == 200
    assert segunda.status_code == 200
    assert primeira.json()["duplicado"] is False
    assert segunda.json()["duplicado"] is True
    assert segunda.json()["evento_id"] == primeira.json()["evento_id"]

    with session_factory() as db:
        total_consultas = db.scalar(select(func.count()).select_from(Consulta))
        total_eventos = db.scalar(select(func.count()).select_from(EventoWebhook))
        assert total_consultas == 1
        assert total_eventos == 1


@pytest.mark.anyio
async def test_campos_extras_ficam_no_evento_bruto(
    client: httpx.AsyncClient,
    load_payload: Any,
    session_factory: sessionmaker[Session],
) -> None:
    payload = load_payload("consulta_SUCCESS.json")
    payload["campo_novo"] = {"origem": "granatech", "versao": 2}
    payload["outro_campo"] = "valor livre"

    resposta = await client.post("/webhooks/granatech", json=payload)

    assert resposta.status_code == 200
    with session_factory() as db:
        evento = db.get(EventoWebhook, resposta.json()["evento_id"])
        assert evento is not None
        assert evento.payload["campo_novo"] == {
            "origem": "granatech",
            "versao": 2,
        }
        assert evento.payload["outro_campo"] == "valor livre"


@pytest.mark.anyio
@pytest.mark.parametrize("tipo", ["CONSULTA", "consulta", "Consulta"])
async def test_tipo_consulta_case_insensitive(
    client: httpx.AsyncClient, load_payload: Any, tipo: str
) -> None:
    payload = load_payload("consulta_PROCESSING.json")
    payload["tipo"] = tipo

    resposta = await client.post("/webhooks/granatech", json=payload)

    assert resposta.status_code == 200, resposta.text
    assert resposta.json()["duplicado"] is False


@pytest.mark.anyio
async def test_alias_consultas_forca_tipo(client: httpx.AsyncClient, load_payload: Any) -> None:
    payload = load_payload("consulta_PROCESSING.json")
    payload.pop("tipo")

    resposta = await client.post("/webhooks/granatech/consultas", json=payload)

    assert resposta.status_code == 200, resposta.text
    assert resposta.json()["duplicado"] is False


@pytest.mark.anyio
async def test_corpo_json_que_nao_e_objeto(
    client: httpx.AsyncClient, session_factory: sessionmaker[Session]
) -> None:
    resposta = await client.post("/webhooks/granatech", json=["nao", "e", "objeto"])

    assert resposta.status_code == 422
    with session_factory() as db:
        evento = db.scalars(select(EventoWebhook).order_by(EventoWebhook.id.desc())).first()
        assert evento is not None
        assert evento.processado is False
        assert evento.payload == ["nao", "e", "objeto"]
