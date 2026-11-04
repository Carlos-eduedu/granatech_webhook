"""Testes dos webhooks de proposta."""

from typing import Any

import httpx
import pytest
from sqlalchemy import func, select
from sqlalchemy.orm import Session, sessionmaker

from granatech_webhook.db.models import (
    Consulta,
    EventoWebhook,
    Proposta,
    PropostaHistorico,
)
from granatech_webhook.web.api.webhooks.constants import (
    PROPOSTA_EVENTOS_DESCRICOES,
    PROPOSTA_STATUS_FINAIS,
)

PROPOSTAS = [
    ("PENDING_CONFIRMATION", "AGUARDANDO_CONFIRMACAO"),
    ("PENDING_USER_REVIEW", "AGUARDANDO_REVISAO_USUARIO"),
    ("PENDING_USER_REVIEW", "FALHA_PAGAMENTO"),
    ("PENDING_FORMALIZATION", "AGUARDANDO_FORMALIZACAO"),
    ("PENDING_FORMALIZATION", "FORMALIZACAO_EM_ANDAMENTO"),
    ("PENDING_FORMALIZATION", "BLOQUEIO_DE_SALDO_EM_ANDAMENTO"),
    ("PENDING_FORMALIZATION", "BLOQUEIO_SALDO"),
    ("PENDING_BANK_ANALYSIS", "AGUARDANDO_ANALISE_BANCO"),
    ("PENDING_PAYMENT", "SUCESSO_SEGURANCA_IDENTIDADE"),
    ("PENDING_REFORMALIZATION", "REFAZER_SEGURANCA_IDENTIDADE"),
    ("REPROVED", "REPROVADO"),
    ("CANCELED", "PROPOSTA_CANCELADA"),
    ("CANCELED", "BLOQUEIO_DE_SALDO_CANCELADO"),
    ("PAYED", "PAGO"),
    ("PAYED", "PROPOSTA_PAGA"),
]


def _nome_fixture(status: str, notificacao: str) -> str:
    return f"proposta_{status}__{notificacao}.json"


@pytest.mark.anyio
@pytest.mark.parametrize(("status", "notificacao"), PROPOSTAS)
async def test_proposta_por_combinacao(
    client: httpx.AsyncClient,
    load_payload: Any,
    session_factory: sessionmaker[Session],
    status: str,
    notificacao: str,
) -> None:
    payload = load_payload(_nome_fixture(status, notificacao))

    resposta = await client.post("/webhooks/granatech", json=payload)

    assert resposta.status_code == 200, resposta.text
    corpo = resposta.json()
    assert corpo["recebido"] is True
    assert corpo["duplicado"] is False

    with session_factory() as db:
        proposta = db.get(Proposta, payload["id_proposta"])
        assert proposta is not None
        assert proposta.status_da_proposta == status
        assert proposta.tipo_notificacao == notificacao
        assert proposta.informacoes == payload["informacoes"]
        assert proposta.status_descricao == PROPOSTA_EVENTOS_DESCRICOES[(status, notificacao)]
        assert proposta.status_final is (status in PROPOSTA_STATUS_FINAIS)
        assert proposta.ultimo_evento_id == corpo["evento_id"]

        historico = db.scalars(
            select(PropostaHistorico).where(PropostaHistorico.id_proposta == payload["id_proposta"])
        ).all()
        assert len(historico) == 1
        assert historico[0].status_da_proposta == status
        assert historico[0].tipo_notificacao == notificacao
        assert historico[0].informacoes == payload["informacoes"]

        evento = db.get(EventoWebhook, corpo["evento_id"])
        assert evento is not None
        assert evento.processado is True
        assert evento.status_conhecido is True
        assert evento.tipo == "proposta"
        assert evento.payload == payload


@pytest.mark.anyio
async def test_sequencia_completa_ate_pago(
    client: httpx.AsyncClient,
    load_payload: Any,
    session_factory: sessionmaker[Session],
) -> None:
    sequencia = [
        ("PENDING_CONFIRMATION", "AGUARDANDO_CONFIRMACAO"),
        ("PENDING_FORMALIZATION", "AGUARDANDO_FORMALIZACAO"),
        ("PENDING_BANK_ANALYSIS", "AGUARDANDO_ANALISE_BANCO"),
        ("PENDING_PAYMENT", "SUCESSO_SEGURANCA_IDENTIDADE"),
        ("PAYED", "PAGO"),
    ]

    for status, notificacao in sequencia:
        payload = load_payload(_nome_fixture(status, notificacao))
        resposta = await client.post("/webhooks/granatech", json=payload)
        assert resposta.status_code == 200, resposta.text
        assert resposta.json()["duplicado"] is False

    payload_final = load_payload(_nome_fixture("PAYED", "PAGO"))
    with session_factory() as db:
        proposta = db.get(Proposta, payload_final["id_proposta"])
        assert proposta is not None
        assert proposta.status_da_proposta == "PAYED"
        assert proposta.tipo_notificacao == "PAGO"
        assert proposta.status_final is True

        historico = db.scalars(
            select(PropostaHistorico)
            .where(PropostaHistorico.id_proposta == payload_final["id_proposta"])
            .order_by(PropostaHistorico.id)
        ).all()
        assert len(historico) == 5
        assert [linha.status_da_proposta for linha in historico] == [
            status for status, _ in sequencia
        ]
        assert [linha.tipo_notificacao for linha in historico] == [
            notificacao for _, notificacao in sequencia
        ]


@pytest.mark.anyio
async def test_idas_e_voltas_nao_sao_rejeitadas(
    client: httpx.AsyncClient,
    load_payload: Any,
    session_factory: sessionmaker[Session],
) -> None:
    banco = load_payload(_nome_fixture("PENDING_BANK_ANALYSIS", "AGUARDANDO_ANALISE_BANCO"))
    pagamento = load_payload(_nome_fixture("PENDING_PAYMENT", "SUCESSO_SEGURANCA_IDENTIDADE"))
    banco_de_novo = {**banco, "informacoes": "Banco pediu nova análise"}
    reprovado = load_payload(_nome_fixture("REPROVED", "REPROVADO"))

    for payload in (banco, pagamento, banco_de_novo, reprovado):
        resposta = await client.post("/webhooks/granatech", json=payload)
        assert resposta.status_code == 200, resposta.text
        assert resposta.json()["duplicado"] is False

    with session_factory() as db:
        proposta = db.get(Proposta, banco["id_proposta"])
        assert proposta is not None
        assert proposta.status_da_proposta == "REPROVED"
        assert proposta.status_final is True
        total = db.scalar(
            select(func.count())
            .select_from(PropostaHistorico)
            .where(PropostaHistorico.id_proposta == banco["id_proposta"])
        )
        assert total == 4


@pytest.mark.anyio
async def test_evento_apos_status_final_gera_warning(
    client: httpx.AsyncClient,
    load_payload: Any,
    session_factory: sessionmaker[Session],
    caplog: pytest.LogCaptureFixture,
) -> None:
    pago = load_payload(_nome_fixture("PAYED", "PAGO"))
    cancelado = load_payload(_nome_fixture("CANCELED", "PROPOSTA_CANCELADA"))

    assert (await client.post("/webhooks/granatech", json=pago)).status_code == 200
    caplog.clear()
    caplog.set_level("WARNING")
    resposta = await client.post("/webhooks/granatech", json=cancelado)

    assert resposta.status_code == 200
    assert "após status final" in caplog.text
    with session_factory() as db:
        proposta = db.get(Proposta, pago["id_proposta"])
        assert proposta is not None
        assert proposta.status_da_proposta == "CANCELED"
        assert proposta.status_final is True


@pytest.mark.anyio
async def test_payload_duplicado_nao_cria_historico(
    client: httpx.AsyncClient,
    load_payload: Any,
    session_factory: sessionmaker[Session],
) -> None:
    payload = load_payload(_nome_fixture("PENDING_CONFIRMATION", "AGUARDANDO_CONFIRMACAO"))

    primeira = await client.post("/webhooks/granatech", json=payload)
    segunda = await client.post("/webhooks/granatech", json=payload)

    assert primeira.status_code == 200
    assert segunda.status_code == 200
    assert segunda.json()["duplicado"] is True
    assert segunda.json()["evento_id"] == primeira.json()["evento_id"]

    with session_factory() as db:
        total = db.scalar(
            select(func.count())
            .select_from(PropostaHistorico)
            .where(PropostaHistorico.id_proposta == payload["id_proposta"])
        )
        assert total == 1
        total_eventos = db.scalar(select(func.count()).select_from(EventoWebhook))
        assert total_eventos == 1


@pytest.mark.anyio
async def test_status_desconhecido_de_proposta_e_aceito(
    client: httpx.AsyncClient,
    load_payload: Any,
    session_factory: sessionmaker[Session],
) -> None:
    payload = load_payload(_nome_fixture("PENDING_CONFIRMATION", "AGUARDANDO_CONFIRMACAO"))
    payload["status_da_proposta"] = "STATUS_NOVO_QUALQUER"
    payload["tipo_notificacao"] = "NOTIFICACAO_NOVA"

    resposta = await client.post("/webhooks/granatech", json=payload)

    assert resposta.status_code == 200
    with session_factory() as db:
        proposta = db.get(Proposta, payload["id_proposta"])
        assert proposta is not None
        assert proposta.status_da_proposta == "STATUS_NOVO_QUALQUER"
        assert proposta.tipo_notificacao == "NOTIFICACAO_NOVA"
        assert proposta.status_descricao is None
        assert proposta.status_final is False

        evento = db.get(EventoWebhook, resposta.json()["evento_id"])
        assert evento is not None
        assert evento.status_conhecido is False


@pytest.mark.anyio
async def test_cpf_da_consulta_preenche_proposta(
    client: httpx.AsyncClient,
    load_payload: Any,
    session_factory: sessionmaker[Session],
) -> None:
    consulta = load_payload("consulta_AWAITING_CLIENT_AUTHORIZATION.json")
    proposta = load_payload(_nome_fixture("PENDING_CONFIRMATION", "AGUARDANDO_CONFIRMACAO"))
    assert consulta["id_proposta"] == proposta["id_proposta"]

    assert (await client.post("/webhooks/granatech", json=consulta)).status_code == 200
    assert (await client.post("/webhooks/granatech", json=proposta)).status_code == 200

    with session_factory() as db:
        registro = db.get(Proposta, proposta["id_proposta"])
        assert registro is not None
        assert registro.cpf == consulta["cpf"]


@pytest.mark.anyio
async def test_consulta_preenche_proposta_ja_criada(
    client: httpx.AsyncClient,
    load_payload: Any,
    session_factory: sessionmaker[Session],
) -> None:
    proposta = load_payload(_nome_fixture("PENDING_CONFIRMATION", "AGUARDANDO_CONFIRMACAO"))
    consulta = load_payload("consulta_AWAITING_CLIENT_AUTHORIZATION.json")

    assert (await client.post("/webhooks/granatech", json=proposta)).status_code == 200
    with session_factory() as db:
        registro = db.get(Proposta, proposta["id_proposta"])
        assert registro is not None
        assert registro.cpf is None

    assert (await client.post("/webhooks/granatech", json=consulta)).status_code == 200

    with session_factory() as db:
        registro = db.get(Proposta, proposta["id_proposta"])
        assert registro is not None
        assert registro.cpf == consulta["cpf"]
        consulta_db = db.get(Consulta, consulta["id_solicitacao"])
        assert consulta_db is not None


@pytest.mark.anyio
async def test_campos_extras_em_proposta(
    client: httpx.AsyncClient,
    load_payload: Any,
    session_factory: sessionmaker[Session],
) -> None:
    payload = load_payload(_nome_fixture("PAYED", "PROPOSTA_PAGA"))
    payload["novo_campo"] = {"a": [1, 2, 3]}
    payload["timestamp_banco"] = "2026-11-04T12:00:00Z"

    resposta = await client.post("/webhooks/granatech", json=payload)

    assert resposta.status_code == 200
    with session_factory() as db:
        evento = db.get(EventoWebhook, resposta.json()["evento_id"])
        assert evento is not None
        assert evento.payload["novo_campo"] == {"a": [1, 2, 3]}
        assert evento.payload["timestamp_banco"] == "2026-11-04T12:00:00Z"


@pytest.mark.anyio
@pytest.mark.parametrize("tipo", ["proposta", "PROPOSTA", "Proposta"])
async def test_tipo_proposta_case_insensitive(
    client: httpx.AsyncClient, load_payload: Any, tipo: str
) -> None:
    payload = load_payload(_nome_fixture("PENDING_CONFIRMATION", "AGUARDANDO_CONFIRMACAO"))
    payload["tipo"] = tipo

    resposta = await client.post("/webhooks/granatech", json=payload)

    assert resposta.status_code == 200, resposta.text
    assert resposta.json()["duplicado"] is False


@pytest.mark.anyio
async def test_alias_propostas_forca_tipo(client: httpx.AsyncClient, load_payload: Any) -> None:
    payload = load_payload(_nome_fixture("PENDING_CONFIRMATION", "AGUARDANDO_CONFIRMACAO"))
    payload.pop("tipo")

    resposta = await client.post("/webhooks/granatech/propostas", json=payload)

    assert resposta.status_code == 200, resposta.text


@pytest.mark.anyio
async def test_proposta_sem_campo_obrigatorio_grava_evento(
    client: httpx.AsyncClient,
    load_payload: Any,
    session_factory: sessionmaker[Session],
) -> None:
    payload = load_payload(_nome_fixture("PENDING_CONFIRMATION", "AGUARDANDO_CONFIRMACAO"))
    del payload["id_proposta"]

    resposta = await client.post("/webhooks/granatech", json=payload)

    assert resposta.status_code == 422
    with session_factory() as db:
        evento = db.scalars(select(EventoWebhook).order_by(EventoWebhook.id.desc())).first()
        assert evento is not None
        assert evento.processado is False
        assert "id_proposta" in (evento.erro or "")
        assert evento.payload == payload
