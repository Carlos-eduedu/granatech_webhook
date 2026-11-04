"""Testes de regressão da regra de idempotência por entidade."""

from __future__ import annotations

from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, select
from sqlalchemy.orm import Session, sessionmaker

from granatech_webhook import services
from granatech_webhook.models import EventoWebhook, Proposta, PropostaHistorico


def _payload(load_payload: Any, status: str, notificacao: str) -> dict[str, Any]:
    return load_payload(f"proposta_{status}__{notificacao}.json")


def test_retentativa_apos_erro_500_reprocessa_o_mesmo_evento(
    client: TestClient,
    load_payload: Any,
    session_factory: sessionmaker[Session],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    payload = _payload(load_payload, "PAYED", "PAGO")
    original = services._processar_proposta_uma_vez
    chamadas = {"total": 0}

    def falha_uma_vez(db: Session, evento: EventoWebhook, dados: Any) -> bool:
        chamadas["total"] += 1
        if chamadas["total"] == 1:
            raise RuntimeError("falha simulada no processamento")
        return original(db, evento, dados)

    monkeypatch.setattr(services, "_processar_proposta_uma_vez", falha_uma_vez)

    primeira = client.post("/webhooks/granatech", json=payload)
    assert primeira.status_code == 500, primeira.text

    with session_factory() as db:
        evento = db.scalars(select(EventoWebhook)).one()
        assert evento.processado is False
        assert evento.chave_entidade == f"proposta:{payload['id_proposta']}"
        assert (evento.erro or "").startswith(services.PREFIXO_ERRO_PROCESSAMENTO)
        evento_id = evento.id
        assert db.get(Proposta, payload["id_proposta"]) is None

    segunda = client.post("/webhooks/granatech", json=payload)

    assert segunda.status_code == 200, segunda.text
    assert segunda.json() == {
        "recebido": True,
        "evento_id": evento_id,
        "duplicado": False,
    }

    with session_factory() as db:
        evento = db.get(EventoWebhook, evento_id)
        assert evento is not None
        assert evento.processado is True
        assert evento.erro is None
        proposta = db.get(Proposta, payload["id_proposta"])
        assert proposta is not None
        assert proposta.status_da_proposta == "PAYED"
        total_historico = db.scalar(
            select(func.count())
            .select_from(PropostaHistorico)
            .where(PropostaHistorico.id_proposta == payload["id_proposta"])
        )
        assert total_historico == 1
        assert db.scalar(select(func.count()).select_from(EventoWebhook)) == 1


def test_ida_e_volta_com_payload_identico_grava_novo_evento(
    client: TestClient,
    load_payload: Any,
    session_factory: sessionmaker[Session],
) -> None:
    banco = _payload(
        load_payload, "PENDING_BANK_ANALYSIS", "AGUARDANDO_ANALISE_BANCO"
    )
    pagamento = _payload(
        load_payload, "PENDING_PAYMENT", "SUCESSO_SEGURANCA_IDENTIDADE"
    )

    primeira = client.post("/webhooks/granatech", json=banco)
    segunda = client.post("/webhooks/granatech", json=pagamento)
    terceira = client.post("/webhooks/granatech", json=banco)

    assert primeira.status_code == 200
    assert segunda.status_code == 200
    assert terceira.status_code == 200, terceira.text
    assert terceira.json()["duplicado"] is False
    assert terceira.json()["evento_id"] != primeira.json()["evento_id"]

    with session_factory() as db:
        proposta = db.get(Proposta, banco["id_proposta"])
        assert proposta is not None
        assert proposta.status_da_proposta == "PENDING_BANK_ANALYSIS"
        assert proposta.tipo_notificacao == "AGUARDANDO_ANALISE_BANCO"

        historico = db.scalars(
            select(PropostaHistorico)
            .where(PropostaHistorico.id_proposta == banco["id_proposta"])
            .order_by(PropostaHistorico.id)
        ).all()
        assert len(historico) == 3
        assert [linha.status_da_proposta for linha in historico] == [
            "PENDING_BANK_ANALYSIS",
            "PENDING_PAYMENT",
            "PENDING_BANK_ANALYSIS",
        ]

        eventos = db.scalars(
            select(EventoWebhook).order_by(EventoWebhook.id)
        ).all()
        assert len(eventos) == 3
        assert eventos[0].payload_hash == eventos[2].payload_hash
        assert eventos[0].chave_entidade == eventos[2].chave_entidade


def test_mesmo_payload_duas_vezes_seguidas_e_duplicado(
    client: TestClient,
    load_payload: Any,
    session_factory: sessionmaker[Session],
) -> None:
    payload = _payload(load_payload, "PENDING_CONFIRMATION", "AGUARDANDO_CONFIRMACAO")

    primeira = client.post("/webhooks/granatech", json=payload)
    segunda = client.post("/webhooks/granatech", json=payload)

    assert primeira.status_code == 200
    assert segunda.status_code == 200
    assert primeira.json()["duplicado"] is False
    assert segunda.json()["duplicado"] is True
    assert segunda.json()["evento_id"] == primeira.json()["evento_id"]

    with session_factory() as db:
        assert db.scalar(select(func.count()).select_from(EventoWebhook)) == 1
        assert (
            db.scalar(
                select(func.count())
                .select_from(PropostaHistorico)
                .where(PropostaHistorico.id_proposta == payload["id_proposta"])
            )
            == 1
        )


def test_modelo_nao_tem_unique_global_no_hash() -> None:
    coluna = EventoWebhook.__table__.c.payload_hash

    assert coluna.unique is not True
    assert coluna.index is True
    assert "chave_entidade" in EventoWebhook.__table__.c
    assert EventoWebhook.__table__.c.chave_entidade.index is True


def test_payload_invalido_reenviado_continua_422_sem_evento_novo(
    client: TestClient,
    load_payload: Any,
    session_factory: sessionmaker[Session],
) -> None:
    payload = load_payload("consulta_AWAITING_CLIENT_AUTHORIZATION.json")
    del payload["cpf"]

    primeira = client.post("/webhooks/granatech", json=payload)
    segunda = client.post("/webhooks/granatech", json=payload)

    assert primeira.status_code == 422
    assert segunda.status_code == 422
    assert segunda.json()["evento_id"] == primeira.json()["evento_id"]
    with session_factory() as db:
        assert db.scalar(select(func.count()).select_from(EventoWebhook)) == 1
