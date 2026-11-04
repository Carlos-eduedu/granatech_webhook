"""Prova que uma rota síncrona presa no banco não bloqueia o event loop."""

import asyncio
import time
from typing import Any

import pytest
from sqlalchemy.orm import Session

from granatech_webhook.web.api.webhooks import service as services


@pytest.mark.anyio
async def test_health_responde_enquanto_webhook_esta_preso_no_banco(
    client: Any,
    load_payload: Any,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    original = services._processar_consulta_uma_vez

    def processamento_lento(db: Session, evento: Any, payload: Any) -> bool:
        time.sleep(1.0)
        return original(db, evento, payload)

    monkeypatch.setattr(services, "_processar_consulta_uma_vez", processamento_lento)

    payload = load_payload("consulta_SUCCESS.json")
    webhook = asyncio.create_task(client.post("/webhooks/granatech", json=payload))
    await asyncio.sleep(0.15)

    inicio = time.perf_counter()
    health = await client.get("/health")
    duracao = time.perf_counter() - inicio

    assert health.status_code == 200
    assert health.json() == {"status": "ok"}
    assert duracao < 0.5, f"/health demorou {duracao:.2f}s"

    resposta = await webhook
    assert resposta.status_code == 200, resposta.text
